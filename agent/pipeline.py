"""
Run orchestration.

    discover files -> scan signals -> select process boundaries -> extract
    -> validate -> audit quotes -> write CPM, BPMN, Markdown, report -> index

The CPM JSON is written before any projection, and a model that fails the
identity gate is never exported to BPMN.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import render
import sources
import validation
from config import Settings, Target, discover_targets, load_config, slugify
from providers import ProviderError, make_provider


def _select_files(target: Target, settings: Settings, files: list[sources.SourceFile]):
    include = target.include or []
    exclude = target.exclude or []
    if include:
        chosen = [f for f in files
                  if any(sources.glob_match(f.rel, p) for p in include)
                  and not any(sources.glob_match(f.rel, p) for p in exclude)]
        return chosen
    if target.cluster:
        return [f for f in files if _cluster(f.rel) == target.cluster]
    return list(files)


def _cluster(rel: str) -> str:
    from config import cluster_of
    return cluster_of(rel)


def _envelopes(result, target: Target) -> list[dict]:
    envelope = result if isinstance(result, dict) else {}
    processes = [p for p in envelope.get("processes", []) if isinstance(p, dict)]
    if processes:
        return [{"kind": "businessProcess",
                 "classification": envelope.get("classification", {}),
                 "process": process, "processes": [], "rejected": [], "openQuestions": []}
                for process in processes]
    return [envelope]


def _write_process(out_dir: Path, process: dict, envelope: dict, report: dict,
                   audit: dict, meta: dict, repo: Path, raw: str = "") -> dict:
    folder = out_dir / "processes" / slugify(process.get("name") or process.get("id") or "process")
    folder.mkdir(parents=True, exist_ok=True)

    (folder / "cpm.json").write_text(json.dumps(process, indent=2) + "\n", encoding="utf-8")
    (folder / "extraction.json").write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    if raw:
        (folder / "extraction.raw").write_text(raw, encoding="utf-8")
    (folder / "validation.json").write_text(
        json.dumps({"report": report, "evidenceAudit": audit, "run": meta}, indent=2) + "\n",
        encoding="utf-8")

    bpmn_written = False
    if report.get("verdict") != "not_a_process":
        (folder / "process.bpmn").write_text(render.to_bpmn(process), encoding="utf-8")
        bpmn_written = True

    (folder / "process.md").write_text(render.to_markdown(process, report, audit), encoding="utf-8")

    activities = [n for n in process.get("nodes", []) if (n.get("type") or "").endswith("Task")]
    return {
        "id": process.get("id"),
        "name": process.get("name"),
        "domain": process.get("domain"),
        "verdict": report.get("verdict"),
        "score": report.get("score"),
        "pattern": report.get("pattern"),
        "activities": len(activities),
        "lanes": len(process.get("lanes") or []),
        "folder": f"processes/{folder.name}",
        "md": f"processes/{folder.name}/process.md",
        "bpmn": f"processes/{folder.name}/process.bpmn" if bpmn_written else "",
        "cpm": f"processes/{folder.name}/cpm.json",
        "report": f"processes/{folder.name}/validation.json",
        "audit": audit,
        "findings": report.get("findings", []),
        "value": process.get("value"),
        "trigger": (process.get("scope") or {}).get("trigger"),
        "outcome": (process.get("scope") or {}).get("outcome"),
    }


def _write_abstention(out_dir: Path, envelope: dict, report: dict, meta: dict, name: str) -> dict:
    folder = out_dir / "processes" / slugify(name)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "extraction.json").write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    (folder / "validation.json").write_text(
        json.dumps({"report": report, "run": meta}, indent=2) + "\n", encoding="utf-8")
    return {
        "id": None,
        "name": name,
        "domain": "",
        "verdict": report.get("verdict"),
        "score": report.get("score"),
        "pattern": report.get("pattern"),
        "activities": 0,
        "lanes": 0,
        "folder": f"processes/{folder.name}",
        "md": "",
        "bpmn": "",
        "cpm": "",
        "report": f"processes/{folder.name}/validation.json",
        "extraction": f"processes/{folder.name}/extraction.json",
        "audit": {"checked": 0, "matched": 0, "coverage": 1.0, "unresolved": []},
        "findings": report.get("findings", []),
        "value": None,
        "trigger": "",
        "outcome": "",
    }


def run(repo: Path, out: Path, config_path: Path | None = None, provider_name: str = "auto",
        model: str = "", allow_unevidenced: bool = False, dry_run: bool = False,
        quiet: bool = False) -> int:
    repo = Path(repo).expanduser().resolve()
    if not repo.is_dir():
        print(f"error: source directory not found: {repo}")
        return 3

    try:
        settings = load_config(repo, config_path)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}")
        return 3

    if dry_run:
        files = list(sources.walk(repo, settings.include, settings.exclude,
                                  settings.max_file_bytes, settings.max_files))
        targets = discover_targets(settings, files, [])
        signals = sources.scan(files, validation.is_action_label)
        targets = discover_targets(settings, files, signals)
        print(f"Scanned {len(files)} files, found {len(signals)} signals.")
        for target in targets:
            chosen = _select_files(target, settings, files)
            own = [s for s in signals if s.file in {f.rel for f in chosen}]
            print(f"  {target.name:<32} {len(chosen):>4} files  {len(own):>3} signals  "
                  f"{'configured' if target.declared else 'auto'}")
        return 0

    try:
        provider, note = make_provider(provider_name, model)
    except ProviderError as exc:
        print(f"error: {exc}")
        return 3
    if note and not quiet:
        print(f"Provider: {note}")

    if not quiet:
        print(f"Source:  {repo}")
        print(f"Output:  {out}")
        if settings.source:
            print(f"Config:  {settings.source}")

    out = Path(out).expanduser().resolve()
    project_dir = out / settings.project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    render.copy_theme(project_dir / "assets")

    files = list(sources.walk(repo, settings.include, settings.exclude,
                              settings.max_file_bytes, settings.max_files))
    signals = sources.scan(files, validation.is_action_label)
    targets = discover_targets(settings, files, signals)

    if not quiet:
        print(f"Files:   {len(files)} scanned, {len(signals)} process signals")
        print(f"Targets: {len(targets)} process boundar{'y' if len(targets) == 1 else 'ies'}")
        print("")

    entries: list[dict] = []
    errors: list[dict] = []
    prompt_version = "heuristic@1.0.0"

    for target in targets:
        chosen = _select_files(target, settings, files)
        own_signals = [s for s in signals if s.file in {f.rel for f in chosen}]
        if not quiet:
            print(f"[{target.name}] {len(chosen)} files, {len(own_signals)} signals")

        if not chosen or not own_signals:
            report = validation.validate({"nodes": []})
            entry = _write_abstention(project_dir, {
                "kind": "notBusinessProcess",
                "classification": {"isBusinessProcess": False, "pattern": "unstructured",
                                   "confidence": 0.9,
                                   "rationale": "No process-bearing code constructs in scope."},
                "process": None, "processes": [], "rejected": [],
            }, report, {"target": target.id, "error": "no signals"}, target.name)
            entries.append(entry)
            if not quiet:
                print("   no process signals; wrote abstention report")
            continue

        try:
            result = provider.extract(target, chosen, own_signals, settings, repo)
        except ProviderError as exc:
            errors.append({"target": target.id, "name": target.name, "error": str(exc)})
            if not quiet:
                print(f"   provider error: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - keep the run going
            errors.append({"target": target.id, "name": target.name, "error": repr(exc)})
            if not quiet:
                print(f"   extraction failed: {exc}")
            continue

        process_hint = result.envelope.get("process")
        if isinstance(process_hint, dict):
            provenance = process_hint.get("provenance") or {}
            prompt_version = provenance.get("promptVersion") or prompt_version
        meta = {
            "provider": result.provider,
            "model": result.model,
            "target": target.id,
            "usage": result.usage,
            "generatedAt": render.now(),
        }

        for index, envelope in enumerate(_envelopes(result.envelope, target)):
            try:
                report = validation.validate(envelope, source=f"extraction:{target.id}")
            except ValueError as exc:
                errors.append({"target": target.id, "name": target.name, "error": str(exc)})
                if not quiet:
                    print(f"   invalid payload: {exc}")
                continue

            process = envelope.get("process")
            if isinstance(process, dict):
                audit = validation.audit_evidence(process, repo)
                entry = _write_process(project_dir, process, envelope, report, audit, meta, repo, result.raw)
            else:
                name = target.name if index == 0 else f"{target.name} {index + 1}"
                entry = _write_abstention(project_dir, envelope, report, meta, name)

            entries.append(entry)
            if not quiet:
                pill = entry["verdict"].replace("_", " ")
                print(f"   {entry['name']}: {pill} · score {entry['score']} · "
                      f"{entry['activities']} activities · quotes {entry['audit']['matched']}/"
                      f"{entry['audit']['checked']}")

    counts = {
        "business_process": sum(1 for e in entries if e["verdict"] == "business_process"),
        "partial_process": sum(1 for e in entries if e["verdict"] == "partial_process"),
        "not_a_process": sum(1 for e in entries if e["verdict"] == "not_a_process"),
        "error": len(errors),
    }
    manifest = {
        "generatedAt": render.now(),
        "repo": str(repo),
        "config": str(settings.source) if settings.source else None,
        "project": {"id": settings.project_id, "name": settings.project_name, "domain": settings.domain},
        "provider": provider.name,
        "model": provider.model,
        "promptVersion": prompt_version,
        "validatorVersion": validation.validator().VALIDATOR_VERSION,
        "filesScanned": len(files),
        "signalsFound": len(signals),
        "processes": entries,
        "counts": counts,
        "errors": errors,
    }

    (project_dir / "run.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    portfolio = {
        "generatedAt": manifest["generatedAt"],
        "project": manifest["project"],
        "processes": [
            {
                "name": e.get("name"),
                "domain": e.get("domain"),
                "verdict": e.get("verdict"),
                "score": e.get("score"),
                "trigger": e.get("trigger"),
                "outcome": e.get("outcome"),
                "value": e.get("value"),
                "folder": e.get("folder"),
            }
            for e in entries
        ],
    }
    (project_dir / "portfolio.json").write_text(json.dumps(portfolio, indent=2) + "\n", encoding="utf-8")
    (project_dir / "index.html").write_text(render.dashboard(manifest), encoding="utf-8")

    if not quiet:
        print("")
        print("-" * 66)
        print(f"{counts['business_process']} accepted · {counts['partial_process']} partial · "
              f"{counts['not_a_process']} rejected · {counts['error']} error(s)")
        print(f"Dashboard: {project_dir / 'index.html'}")

    if counts["business_process"] == len(entries) and not errors and entries:
        return 0
    if entries and counts["not_a_process"] == len(entries):
        return 2
    if not entries:
        return 2
    return 1


def cleanup(out: Path) -> None:
    """Remove generated output. Kept explicit so a run never deletes silently."""
    out = Path(out).expanduser().resolve()
    if out.is_dir():
        shutil.rmtree(out)
