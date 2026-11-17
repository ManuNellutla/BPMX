"""
Heuristic CPM builder.

This is the offline baseline provider. It turns scanned code signals into a
Canonical Process Model that satisfies the same contract the LLM path must
satisfy — ordered activities, actor lanes, trigger and outcome, one start, at
least one end, and a resolvable locator plus verbatim quote per activity.

It is deliberately conservative. It does not invent decisions, values or
actors: those come from `process-atlas.json` when a human supplies them.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import sources
from config import Settings, Target, cluster_of, slugify, title
from validation import file_hash

CONFIDENCE = {"cron": 0.84, "queue": 0.84, "route": 0.80, "decorator": 0.80, "function": 0.72}


def sid(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def lane_id_for(name: str) -> str:
    return f"lane_{slugify(name)}"


def lane_for(file: str, settings: Settings, fallback: str) -> tuple[str, str]:
    """Resolve a business actor for a file. Returns (laneId, laneName)."""
    for rule in settings.actors:
        if sources.glob_match(file, rule.match):
            return lane_id_for(rule.lane), rule.lane
    name = title(fallback)
    return lane_id_for(name), name


def dedupe(signals: list[sources.Signal]) -> list[sources.Signal]:
    best: dict[str, sources.Signal] = {}
    for signal in signals:
        key = signal.label.lower()
        current = best.get(key)
        if current is None or signal.priority > current.priority:
            best[key] = signal
    return list(best.values())


def order_signals(signals: list[sources.Signal], sequence: list[str]) -> list[sources.Signal]:
    """Apply a configured sequence, then keep discovery order for the rest."""
    remaining = list(signals)
    ordered: list[sources.Signal] = []
    for wanted in sequence:
        key = wanted.strip().lower()
        for signal in remaining:
            if signal.label.lower() == key:
                ordered.append(signal)
                remaining.remove(signal)
                break
    ordered.extend(remaining)
    return ordered


def evidence_for(signal: sources.Signal, source_id: str) -> dict:
    return {
        "sourceId": source_id,
        "kind": "code",
        "locator": {"path": signal.file, "startLine": signal.line, "endLine": signal.line},
        "quote": signal.quote,
        "confidence": CONFIDENCE.get(signal.kind, 0.7),
    }


def value_block(target: Target) -> dict:
    if target.value:
        outcome = target.value.get("outcome")
        return {
            "lever": target.value.get("lever") or ["cycleTime"],
            "outcome": outcome if isinstance(outcome, dict) else None,
            "kpis": target.value.get("kpis") or [],
            "impact": target.value.get("impact"),
            "automationPotential": target.value.get("automationPotential"),
            "automationRationale": target.value.get("automationRationale") or "",
            "noQuantifiedOutcome": None if isinstance(outcome, dict) else {
                "reason": "No quantified outcome was stated in the source."
            },
        }
    return {
        "lever": ["cycleTime"],
        "outcome": None,
        "kpis": [],
        "impact": None,
        "automationPotential": None,
        "automationRationale": "",
        "noQuantifiedOutcome": {
            "reason": "Source is source code; no baseline or target is stated. "
                      "Supply value.outcome in process-atlas.json to quantify it."
        },
    }


def not_a_process(target: Target, signals: list[sources.Signal], repo: Path) -> dict:
    count = len(signals)
    pattern = "single_activity" if count == 1 else "unstructured"
    rationale = (
        "Only one process-bearing construct was found; ordering and hand-off are absent."
        if count == 1 else
        "No ordered, actor-bound activities were found in the selected files."
    )
    return {
        "kind": "notBusinessProcess",
        "classification": {
            "isBusinessProcess": False,
            "pattern": pattern,
            "confidence": 0.8,
            "rationale": rationale,
        },
        "process": None,
        "processes": [],
        "rejected": [
            {"label": target.name, "why": rationale},
        ],
        "openQuestions": [
            f"No process extracted from {repo} for scope '{target.name}'."
        ],
    }


def build_envelope(target: Target, signals: list[sources.Signal], settings: Settings,
                   repo: Path, source_texts: dict[str, str] | None = None) -> dict:
    source_texts = source_texts or {}
    ignored = {label.strip().lower() for label in target.ignore}
    ordered = [s for s in order_signals(dedupe(signals), target.sequence)
               if s.label.lower() not in ignored]
    if len(ordered) < 2:
        return not_a_process(target, ordered, repo)

    lanes: dict[str, dict] = {}
    activities: list[dict] = []
    source_ids: dict[str, str] = {}

    for signal in ordered:
        lane_key, lane_name = lane_for(signal.file, settings, target.cluster or cluster_of(signal.file))
        lanes.setdefault(lane_key, {
            "id": lane_key,
            "name": lane_name,
            "type": next((r.type for r in settings.actors if lane_id_for(r.lane) == lane_key), "internal"),
        })
        if signal.file not in source_ids:
            source_ids[signal.file] = sid("src", signal.file)
        activities.append({
            "id": sid("n", target.id, signal.label.lower(), signal.file, str(signal.line)),
            "type": "serviceTask",
            "name": signal.label,
            "laneId": lane_key,
            "confidence": CONFIDENCE.get(signal.kind, 0.7),
            "systems": [],
            "inputs": [],
            "outputs": [],
            "evidence": [evidence_for(signal, source_ids[signal.file])],
        })

    first, last = activities[0], activities[-1]
    trigger = target.trigger or f"{first['name']} requested"
    outcome = target.outcome or f"{last['name']} completed"

    start = {
        "id": sid("n", target.id, "start"),
        "type": "startEvent",
        "name": trigger,
        "laneId": first["laneId"],
        "confidence": 0.9,
        "evidence": [dict(first["evidence"][0])],
    }
    end = {
        "id": sid("n", target.id, "end"),
        "type": "endEvent",
        "name": outcome,
        "laneId": last["laneId"],
        "confidence": 0.9,
        "evidence": [dict(last["evidence"][0])],
    }

    if target.end_lane:
        wanted = target.end_lane.strip().lower()
        for lane_key, lane in lanes.items():
            if lane["name"].lower() == wanted:
                end["laneId"] = lane_key
                break

    nodes = [start, *activities, end]
    by_label = {node["name"].lower(): node for node in activities}
    edges: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add_edge(src: str, dst: str, condition: str | None = None,
                 is_default: bool = False) -> None:
        if src == dst or (src, dst) in seen:
            return
        seen.add((src, dst))
        edge = {"id": sid("e", src, dst, condition or ""), "from": src, "to": dst}
        if condition:
            edge["condition"] = condition
        if is_default:
            edge["isDefault"] = True
        edges.append(edge)

    previous = start["id"]
    for node in activities:
        add_edge(previous, node["id"])
        previous = node["id"]
    add_edge(previous, end["id"])

    warnings: list[str] = []
    for decision in target.decisions:
        after_label = str(decision.get("after") or "").strip().lower()
        after = by_label.get(after_label)
        if after is None:
            warnings.append(f"Decision '{decision.get('name', '?')}' skipped: "
                            f"no activity named '{decision.get('after')}'.")
            continue
        branches = [b for b in decision.get("branches", []) if isinstance(b, dict)]
        if len(branches) < 1:
            warnings.append(f"Decision '{decision.get('name', '?')}' has no branches; skipped.")
            continue

        gateway = {
            "id": sid("n", target.id, "gateway", str(decision.get("name") or after["name"])),
            "type": "exclusiveGateway",
            "name": str(decision.get("name") or "Decision"),
            "laneId": after["laneId"],
            "confidence": after["confidence"],
            "evidence": [dict(after["evidence"][0])],
        }
        nodes.insert(nodes.index(after) + 1, gateway)

        # Replace the chain edge leaving `after` with an edge into the gateway.
        outgoing = next((e for e in edges if e["from"] == after["id"]), None)
        following = outgoing["to"] if outgoing else end["id"]
        if outgoing:
            edges.remove(outgoing)
            seen.discard((outgoing["from"], outgoing["to"]))
        add_edge(after["id"], gateway["id"])

        covered: set[str] = set()
        for branch in branches:
            raw = str(branch.get("target") or "").strip()
            if raw == "$end":
                target_id = end["id"]
            else:
                node = by_label.get(raw.lower())
                if node is None:
                    warnings.append(f"Decision '{gateway['name']}' branch '{raw}' skipped: "
                                    "no matching activity.")
                    continue
                target_id = node["id"]
            add_edge(gateway["id"], target_id, str(branch.get("condition") or "") or None)
            covered.add(target_id)

        if following not in covered:
            add_edge(gateway["id"], following, None, is_default=True)

    assumptions = [
        "Activities are ordered from process-atlas.json sequence, then from route/job declaration order.",
        "Each code construct is treated as one system-performed activity; actor lanes come from path rules.",
    ]
    if target.declared:
        assumptions.append("Process boundary, trigger and outcome were configured by a human.")
    else:
        assumptions.append(f"Process boundary was auto-discovered from the '{target.cluster}' module.")

    open_questions = list(warnings)
    if not target.declared:
        open_questions.append("Auto-discovered scope: confirm the boundary and actor names.")
    if not target.value:
        open_questions.append("No quantified business outcome configured for this process.")

    process = {
        "schemaVersion": "1.0.0",
        "id": sid("prc", settings.project_id, target.id),
        "projectId": settings.project_id,
        "name": target.name,
        "domain": target.domain,
        "version": 1,
        "status": "draft",
        "summary": target.summary or (
            f"{len(activities)} system activities across {len(lanes)} actor lane(s), "
            f"extracted from {len(source_ids)} source file(s)."
        ),
        "scope": {
            "trigger": trigger,
            "outcome": outcome,
            "inScope": list(dict.fromkeys(s.file for s in ordered)),
            "outOfScope": [],
        },
        "lanes": list(lanes.values()),
        "nodes": nodes,
        "edges": edges,
        "dataObjects": [],
        "systems": [],
        "value": value_block(target),
        "candidates": [],
        "assumptions": assumptions,
        "openQuestions": open_questions,
        "provenance": {
            "runId": sid("run", settings.project_id, target.id,
                         *[file_hash(source_texts.get(p, "")) for p in sorted(source_texts)]),
            "promptVersion": "heuristic@1.0.0",
            "temperature": 0,
            "seed": 0,
            "sourceHashes": [f"{file_hash(source_texts[p])} {p}" for p in sorted(source_texts)],
            "generator": "heuristic",
        },
    }

    confidence = sum(n["confidence"] for n in activities) / len(activities)
    envelope = {
        "kind": "businessProcess",
        "classification": {
            "isBusinessProcess": True,
            "pattern": "process",
            "confidence": round(confidence, 2),
            "rationale": f"{len(activities)} ordered code constructs across "
                         f"{len(lanes)} actor lane(s) with a stated trigger and outcome.",
        },
        "process": process,
        "processes": [],
        "rejected": [],
        "openQuestions": list(open_questions),
    }
    return envelope
