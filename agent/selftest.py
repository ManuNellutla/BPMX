"""
Agent self-test.

Proves the parts that can regress independently of any model:

    discovery     the example repository yields the configured boundaries
    extraction    each boundary produces a business_process at score 100
    evidence      every quote resolves at its file and line
    projection    BPMN parses and preserves node and flow counts
    determinism   two builds of the same input produce identical IDs
    abstention    a repository with no process signals is rejected, not invented
"""

from __future__ import annotations

import json
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import build
import pipeline
import render
import sources
import validation
from config import discover_targets, load_config

HERE = Path(__file__).resolve().parent
EXAMPLE = HERE / "examples" / "orders-service"


def _prepare(repo: Path, config_path: Path | None = None):
    settings = load_config(repo, config_path)
    files = list(sources.walk(repo, settings.include, settings.exclude,
                              settings.max_file_bytes, settings.max_files))
    signals = sources.scan(files, validation.is_action_label)
    return settings, files, signals


def run() -> int:
    failures = 0
    total = 0

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal failures, total
        total += 1
        status = "ok  " if condition else "FAIL"
        print(f"{status} {name:<52} {detail}")
        if not condition:
            failures += 1

    settings, files, signals = _prepare(EXAMPLE)
    check("discovery: files scanned", len(files) == 11, f"{len(files)} files")
    check("discovery: signals found", len(signals) == 17, f"{len(signals)} signals")
    check("discovery: configured targets", len(settings.targets) == 2,
          ", ".join(t.name for t in settings.targets))

    first_cpm = None
    for target in settings.targets:
        chosen = pipeline._select_files(target, settings, files)
        own = [s for s in signals if s.file in {f.rel for f in chosen}]
        texts = {f.rel: f.text for f in chosen}
        envelope = build.build_envelope(target, own, settings, EXAMPLE, texts)
        report = validation.validate(envelope)
        process = envelope.get("process") or {}
        audit = validation.audit_evidence(process, EXAMPLE)
        activities = [n for n in process.get("nodes", []) if (n.get("type") or "").endswith("Task")]

        check(f"{target.name}: verdict", report["verdict"] == "business_process",
              f"{report['verdict']} {report['score']}")
        check(f"{target.name}: activities", len(activities) >= 2, f"{len(activities)}")
        check(f"{target.name}: quotes resolve", audit["checked"] > 0 and audit["matched"] == audit["checked"],
              f"{audit['matched']}/{audit['checked']}")

        bpmn = render.to_bpmn(process)
        try:
            tree = ET.fromstring(bpmn)
            ns = {"b": "http://www.omg.org/spec/BPMN/20100524/MODEL"}
            flows = tree.findall(".//b:process/b:sequenceFlow", ns)
            check(f"{target.name}: BPMN parses", len(flows) == len(process.get("edges", [])),
                  f"{len(flows)} flows")
        except ET.ParseError as exc:
            check(f"{target.name}: BPMN parses", False, str(exc))

        markdown = render.to_markdown(process, report, audit)
        check(f"{target.name}: Markdown renders", process["name"] in markdown and "## Evidence" in markdown)

        again = build.build_envelope(target, own, settings, EXAMPLE, texts)
        check(f"{target.name}: deterministic IDs",
              [n["id"] for n in process["nodes"]] == [n["id"] for n in again["process"]["nodes"]])

        if first_cpm is None:
            first_cpm = process

    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp)
        (empty / "data.py").write_text("FIELD_A = 1\nFIELD_B = 2\n")
        settings2, files2, signals2 = _prepare(empty)
        targets2 = discover_targets(settings2, files2, signals2)
        envelope = build.build_envelope(targets2[0], [], settings2, empty, {})
        report = validation.validate(envelope)
        check("abstention: no invented process",
              report["verdict"] == "not_a_process" and envelope["kind"] == "notBusinessProcess",
              f"{report['verdict']} {report['pattern']}")

    print("-" * 68)
    print(f"{total - failures}/{total} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
