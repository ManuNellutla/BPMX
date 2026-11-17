"""
Validator bridge and evidence audit.

`validate_extraction.py` lives with the specification set and is the single
source of truth for what counts as a business process. This module loads it
without copying its rules, then adds the one check the standalone validator
cannot do: does each quoted line actually exist at the stated location in the
repository?
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = AGENT_DIR.parent / "designs" / "prompts"
VALIDATOR_PATH = PROMPTS_DIR / "validate_extraction.py"

_VALIDATOR = None


def validator():
    """Load the specification validator as a module (cached)."""
    global _VALIDATOR
    if _VALIDATOR is not None:
        return _VALIDATOR
    if not VALIDATOR_PATH.is_file():
        raise FileNotFoundError(f"validator not found at {VALIDATOR_PATH}")
    spec = importlib.util.spec_from_file_location("atlas_validator", VALIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    _VALIDATOR = module
    return module


def is_action_label(label: str) -> bool:
    return validator().is_action_label(label)


def validate(document: dict, source: str = "<memory>") -> dict:
    return validator().validate_document(document, source)


def file_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:16]


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def audit_evidence(process: dict, repo: Path) -> dict:
    """Check every code locator against the repository.

    The standalone validator reports `verbatim: unverified offline` because it
    never reads source files. The agent has the repository, so it can say
    whether each quote is really present at file:line.
    """
    repo = repo.resolve()
    results = []
    node_ids = {n.get("id") for n in process.get("nodes", []) if isinstance(n, dict)}
    checked = matched = 0

    for node in process.get("nodes", []):
        if not isinstance(node, dict):
            continue
        for entry in node.get("evidence", []) or []:
            if not isinstance(entry, dict):
                continue
            locator = entry.get("locator") or {}
            path = locator.get("path") or locator.get("file")
            start = locator.get("startLine")
            end = locator.get("endLine") or start
            quote = entry.get("quote")
            if not isinstance(path, str) or not isinstance(quote, str):
                continue
            checked += 1
            record = {
                "nodeId": node.get("id"),
                "path": path,
                "startLine": start,
                "endLine": end,
                "ok": False,
                "reason": "",
            }
            try:
                target = (repo / path).resolve()
                if repo not in target.parents and target != repo:
                    record["reason"] = "path escapes the repository"
                elif not target.is_file():
                    record["reason"] = "file not found"
                else:
                    lines = target.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if not isinstance(start, int) or start < 1 or start > len(lines):
                        record["reason"] = "line range outside the file"
                    else:
                        snippet = normalise(" ".join(lines[start - 1:min(end, len(lines))]))
                        if normalise(quote) and normalise(quote) in snippet:
                            record["ok"] = True
                            matched += 1
                        else:
                            record["reason"] = "quote not found at the stated location"
                            record["expected"] = normalise(quote)[:200]
                            record["found"] = snippet[:200]
            except OSError as exc:  # pragma: no cover - unreadable file
                record["reason"] = f"unreadable: {exc}"
            results.append(record)

    return {
        "checked": checked,
        "matched": matched,
        "coverage": round(matched / checked, 3) if checked else 1.0,
        "unresolved": [r for r in results if not r["ok"]],
        "results": results,
        "nodeIds": sorted(str(n) for n in node_ids if n),
    }


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
