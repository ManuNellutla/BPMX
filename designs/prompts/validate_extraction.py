#!/usr/bin/env python3
"""
validate_extraction.py — decide whether an extraction payload is a business process.

    python3 validate_extraction.py FILE [--json] [--verbose] [--allow-unevidenced]
    python3 validate_extraction.py --self-test

Two questions are answered separately:

  identity    Is this an ordered, actor-bound, outcome-producing set of activities?
              A payload that fails identity is not a process regardless of shape.
  compliance  Does it satisfy the model contract (lanes, terminals, evidence, value)?
              A payload that passes identity but fails compliance is a process,
              reported as partial rather than rejected.

Exit codes: 0 business_process, 1 partial_process, 2 not_a_process, 3 invalid input.

No third-party dependencies. No network or source-file access, so quotes are
reported as "unverified offline" unless the caller verifies them separately.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, deque
from pathlib import Path

VALIDATOR_VERSION = "1.0.0"

# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #

ACTIVITY_TYPES = {
    "task", "userTask", "serviceTask", "manualTask", "businessRuleTask",
    "sendTask", "receiveTask", "scriptTask", "callActivity", "subProcess",
}
START_TYPES = {"startEvent"}
END_TYPES = {"endEvent"}
EVENT_TYPES = {
    "startEvent", "endEvent", "intermediateCatchEvent", "intermediateThrowEvent",
    "boundaryEvent",
}
GATEWAY_TYPES = {"exclusiveGateway", "parallelGateway", "inclusiveGateway", "eventBasedGateway"}
DATA_TYPES = {"dataObject", "dataObjectReference", "dataStore", "dataStoreReference"}
KNOWN_TYPES = ACTIVITY_TYPES | EVENT_TYPES | GATEWAY_TYPES | DATA_TYPES | {"textAnnotation"}

VERBS = set("""
accept access accommodate account accrue acquire act activate adapt add address adjust administer admit adopt
advance advise allocate amend analyse analyze answer anticipate apply appoint appraise approve archive arrange
assemble assess assign assist attach attend audit authorise authorize automate award balance batch bill book
brief budget build calculate call cancel capture categorise categorize certify change charge check choose
clarify classify clean close collect combine comment commission communicate compare compile complete comply
compose compute conduct confirm consolidate contact contract control convert coordinate copy correct cost
create credit decide decline define delegate delete deliver demand demonstrate deny deploy deposit derive
design detect determine develop dispatch dispute distribute document download draft edit educate elect
eliminate email emit enable enforce engage enhance ensure enter escalate establish estimate evaluate examine
exchange execute expand expedite explain export extract feed file fill finalise finalize finance fix follow
forecast form forward fulfil fulfill gather generate get govern grant group handle hire identify implement
import improve include increase index inform initiate inspect install instruct integrate interview investigate
invoice issue join justify keep launch lease lend license list load locate log mail maintain manage map market
match measure meet merge migrate monitor move negotiate notify obtain offer onboard open operate order organise
organize output overcome override own package pay perform permit place plan post prepare present price print
prioritise prioritize process procure produce profile program promote propose protect prove provide publish
purchase qualify query raise rate reach read receive recognise recognize recommend reconcile record recover
recruit reduce refer refine refund register reimburse reject release remove renew rent repair replace report
request require requisition reschedule reserve reset resolve respond restart restore restrict result retain
retire retrieve return reuse review revise reward route run sample satisfy save schedule score screen seal
search secure select sell send separate serve settle share ship sign split staff standardise standardize start
stop store submit subscribe substitute suggest summarise summarize supply support survey suspend sustain take
task test track trade train transfer transform translate transmit transport trigger triage troubleshoot tune
update upgrade upload use validate value verify view void wait waive withdraw work write
""".split())

HEADING_WORDS = {
    "introduction", "background", "overview", "summary", "scope", "method", "methodology",
    "approach", "results", "findings", "discussion", "conclusion", "conclusions",
    "recommendation", "recommendations", "appendix", "references", "glossary", "agenda",
    "objectives", "context", "purpose", "definition", "definitions", "analysis",
}

ORG_WORDS = {
    "cfo", "ceo", "coo", "cto", "cio", "chro", "vp", "manager", "director", "head",
    "lead", "team", "department", "division", "unit", "officer", "supervisor",
    "coordinator", "analyst", "specialist", "controller", "clerk", "board", "committee",
    "group", "function",
}

FIELD_TAIL_WORDS = {
    "id", "no", "number", "date", "amount", "status", "type", "code", "name", "email",
    "address", "total", "value", "flag", "indicator", "count", "qty", "quantity",
    "currency", "rate", "timestamp", "description", "notes",
}

PATTERNS = {
    "process", "entity_list", "document_summary", "org_chart",
    "single_activity", "multi_process", "unstructured",
}

# --------------------------------------------------------------------------- #
# Rule catalogue: weight, category, remediation
# --------------------------------------------------------------------------- #

RULES = {
    "S03": ("structure", 20, "Duplicate element IDs", "Regenerate IDs; they must be unique within the document."),
    "S04": ("structure", 20, "Dangling edge", "Point every edge at an existing node."),
    "S05": ("compliance", 10, "Unresolved lane reference", "Add the missing lane or fix laneId."),
    "S06": ("compliance", 3, "Duplicate edge", "Remove repeated from/to pairs."),
    "S07": ("compliance", 3, "Unknown node type", "Map to a BPMN 2.0 flow-node type."),
    "S09": ("compliance", 12, "Start event count", "Keep exactly one start event per process."),
    "S10": ("compliance", 12, "Missing end event", "Add the evidenced terminal state."),
    "P01": ("identity", 20, "Process identity", "Name the process from its scope sentence, not the file."),
    "P02": ("identity", 30, "Fewer than two activities", "Extract at least two activities; if none exist, return notBusinessProcess."),
    "P03": ("identity", 30, "No activity-to-activity ordering", "Add evidenced sequence flows between steps."),
    "P04": ("identity", 30, "No start-to-end path", "Rebuild ordering so a path reaches an end event."),
    "P05": ("identity", 20, "Unreachable activity", "Delete or reattach activities outside the path."),
    "P06": ("compliance", 15, "Actor coverage", "Assign every activity to exactly one resolving lane."),
    "P07": ("compliance", 15, "Activity names are not actions", "Rename as verb-object imperative."),
    "P08": ("compliance", 12, "Missing trigger or outcome", "Extract the start condition and business result."),
    "P09": ("compliance", 5, "Outcome looks like a field", "State an observable business result."),
    "P10": ("compliance", 12, "Evidence coverage", "Cite a locator and quote per activity, or demote to candidates."),
    "P11": ("compliance", 6, "Malformed locator", "Use page+bbox, image region, code path+lines or timecode range."),
    "P12": ("compliance", 2, "Candidate promoted", "Move unsupported elements out of nodes[]."),
    "P13": ("compliance", 15, "Multiple processes in one graph", "Split into processes[] with one trigger each."),
    "P14": ("identity", 25, "Nodes are data entities", "Move fields and records to dataObjects[]."),
    "P15": ("compliance", 3, "Label hygiene", "Deduplicate names, shorten to <= 80 chars, drop trailing dots."),
    "P16": ("advisory", 2, "Weak evidence quote", "Quote the sentence that shows behaviour, not the element label."),
    "P17": ("advisory", 3, "Value block empty", "Record a lever and outcome, or set noQuantifiedOutcome."),
    "P18": ("advisory", 2, "Low-confidence node", "Move elements below 0.70 confidence to candidates[]."),
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def as_list(value):
    return value if isinstance(value, list) else []


def as_dict(value):
    return value if isinstance(value, dict) else {}


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def norm_label(label):
    if not isinstance(label, str):
        return ""
    text = label.strip()
    text = re.sub(r"^\s*[\d]+(\.[\d]+)*\s*[.)]?\s*", "", text)  # section numbering
    return text


def words_of(label):
    return re.findall(r"[a-z]+", label.lower())


def is_action_label(label):
    """True when the first meaningful token is a verb, or a verb with a suffix."""
    text = norm_label(label).lower()
    if not text:
        return False
    tokens = re.findall(r"[a-z]+", text)
    if not tokens:
        return False
    first = tokens[0]
    if first in VERBS:
        return True
    if first == "re" and len(tokens) > 1 and tokens[1] in VERBS:
        return True
    if first.startswith("re") and first[2:] in VERBS:
        return True
    for suffix in ("ing", "ed", "es", "s"):
        if first.endswith(suffix) and len(first) > len(suffix) + 2:
            stem = first[: -len(suffix)]
            if stem in VERBS or stem + "e" in VERBS:
                return True
    return False


def looks_entity(label):
    raw = norm_label(label)
    if not raw:
        return False
    low = raw.lower()
    if re.match(r"^[a-z0-9]+(_[a-z0-9]+)+$", low):      # snake_case field
        return True
    if re.match(r"^[A-Z][A-Z0-9_]{2,}$", raw.strip()):  # CONSTANT_CASE
        return True
    tokens = words_of(low)
    if not tokens:
        return False
    if tokens[-1] in FIELD_TAIL_WORDS:
        return True
    return False


def is_heading(label):
    return bool(set(words_of(norm_label(label))) & HEADING_WORDS)


def is_org(label):
    return bool(set(words_of(norm_label(label))) & ORG_WORDS)


KIND_ALIASES = {"pdf": "page", "video": "timecode", "frame": "image",
                "source": "code", "line": "code", "timestamp": "timecode"}


def locator_shape_ok(kind, locator):
    loc = as_dict(locator)
    kind = kind if isinstance(kind, str) else infer_kind(loc)
    kind = KIND_ALIASES.get(kind, kind)
    if kind == "page":
        bbox = loc.get("bbox")
        return (is_number(loc.get("page")) and loc.get("page") >= 1
                and isinstance(bbox, list) and len(bbox) == 4 and all(is_number(v) for v in bbox))
    if kind in ("image", "region"):
        bbox = loc.get("region") or loc.get("bbox")
        return isinstance(bbox, list) and len(bbox) == 4 and all(is_number(v) for v in bbox)
    if kind == "code":
        path = loc.get("path") or loc.get("file")
        return (isinstance(path, str) and bool(path.strip())
                and is_number(loc.get("startLine")) and loc["startLine"] >= 1
                and is_number(loc.get("endLine")) and loc["endLine"] >= loc["startLine"])
    if kind == "timecode":
        return (is_number(loc.get("start")) and loc["start"] >= 0
                and is_number(loc.get("end")) and loc["end"] > loc["start"])
    if kind == "text":
        return any(is_number(loc.get(k)) for k in ("charStart", "charEnd", "offset"))
    return False


def infer_kind(loc):
    if "page" in loc:
        return "page"
    if "path" in loc or "file" in loc or ("startLine" in loc and "endLine" in loc):
        return "code"
    if "start" in loc and "end" in loc:
        return "timecode"
    if "region" in loc or "bbox" in loc:
        return "image"
    return ""


def edge_ends(edge):
    return edge.get("from") or edge.get("source"), edge.get("to") or edge.get("target")


# --------------------------------------------------------------------------- #
# Result container
# --------------------------------------------------------------------------- #

class Report:
    def __init__(self):
        self.findings = []
        self.gates = {"identity": [], "compliance": [], "structure": []}

    def add(self, code, message, element=None, category=None, weight=None):
        rule = RULES.get(code, ("compliance", 0, code, ""))
        cat = category or rule[0]
        w = rule[1] if weight is None else weight
        self.findings.append({
            "code": code,
            "category": cat,
            "severity": ("error" if cat in ("identity", "structure")
                         else "info" if cat == "advisory" else "warning"),
            "message": message,
            "elementId": element,
            "weight": w,
        })
        if cat in self.gates and code not in self.gates[cat]:
            self.gates[cat].append(code)

    def has(self, code):
        return any(f["code"] == code for f in self.findings)


# --------------------------------------------------------------------------- #
# Core validation of a single CPM document
# --------------------------------------------------------------------------- #

def validate_process(process, allow_unevidenced=False):
    rep = Report()
    nodes = [n for n in as_list(process.get("nodes")) if isinstance(n, dict)]
    edges = [e for e in as_list(process.get("edges")) if isinstance(e, dict)]
    lanes = [l for l in as_list(process.get("lanes")) if isinstance(l, dict)]

    by_id = {}
    for node in nodes:
        nid = node.get("id")
        if not isinstance(nid, str) or not nid.strip():
            rep.add("S03", "Node without a usable id", None, category="structure")
            continue
        if nid in by_id:
            rep.add("S03", f"Duplicate node id {nid}", nid, category="structure")
            continue
        by_id[nid] = node

    lane_ids = {l.get("id") for l in lanes if isinstance(l.get("id"), str)}
    activities = [n for n in nodes if n.get("type") in ACTIVITY_TYPES]
    activity_ids = {n.get("id") for n in activities}
    starts = [n for n in nodes if n.get("type") in START_TYPES]
    ends = [n for n in nodes if n.get("type") in END_TYPES]
    gateways = [n for n in nodes if n.get("type") in GATEWAY_TYPES]
    data_nodes = [n for n in nodes if n.get("type") in DATA_TYPES]

    # ---- graph ----------------------------------------------------------
    adjacency = {nid: set() for nid in by_id}
    reverse = {nid: set() for nid in by_id}
    valid_edges = 0
    seen_pairs = set()
    for edge in edges:
        src, dst = edge_ends(edge)
        if src not in by_id or dst not in by_id:
            rep.add("S04", f"Edge {edge.get('id', '?')} references a missing node ({src} -> {dst})",
                    edge.get("id"), category="structure")
            continue
        if src == dst:
            rep.add("S04", f"Self-loop on {src} has no rework condition", edge.get("id"),
                    category="structure")
            continue
        pair = (src, dst)
        if pair in seen_pairs:
            rep.add("S06", f"Duplicate edge {src} -> {dst}", edge.get("id"))
        seen_pairs.add(pair)
        adjacency[src].add(dst)
        reverse[dst].add(src)
        valid_edges += 1

    def bfs(seeds, graph):
        seen, queue = set(), deque(seeds)
        seen.update(seeds)
        while queue:
            cur = queue.popleft()
            for nxt in graph.get(cur, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return seen

    reachable_from_start = bfs([n["id"] for n in starts], adjacency) if starts else set()
    can_reach_end = bfs([n["id"] for n in ends], reverse) if ends else set()
    on_path = {nid for nid in by_id
               if nid in reachable_from_start and nid in can_reach_end}

    # weakly connected components
    undirected = {nid: set(adjacency[nid]) | set(reverse[nid]) for nid in by_id}
    unseen, components = set(by_id), []
    while unseen:
        root = next(iter(unseen))
        comp = bfs([root], undirected)
        components.append(comp)
        unseen -= comp
    active_components = [c for c in components if c & activity_ids]

    # ---- node hygiene ---------------------------------------------------
    unknown_types = [n.get("id") for n in nodes if n.get("type") not in KNOWN_TYPES]
    if unknown_types:
        rep.add("S07", f"{len(unknown_types)} node(s) use an unknown type: "
                       f"{', '.join(str(x) for x in unknown_types[:5])}", unknown_types[0])

    action_hits = sum(1 for n in activities if is_action_label(n.get("name", "")))
    action_ratio = action_hits / len(activities) if activities else 0.0

    names = [norm_label(n.get("name", "")).lower() for n in activities if norm_label(n.get("name", ""))]
    duplicate_names = [name for name, count in Counter(names).items() if count > 1]

    # ---- lanes ----------------------------------------------------------
    missing_lane = [n.get("id") for n in activities
                    if n.get("laneId") not in lane_ids]
    lane_coverage = ((len(activities) - len(missing_lane)) / len(activities)) if activities else 0.0
    unknown_lane_refs = [n.get("id") for n in nodes
                         if n.get("laneId") and n.get("laneId") not in lane_ids]
    if unknown_lane_refs:
        rep.add("S05", f"{len(unknown_lane_refs)} node(s) reference a lane not in lanes[]",
                unknown_lane_refs[0])

    # ---- evidence -------------------------------------------------------
    evidenced, malformed = 0, 0
    weak_quotes = 0
    for node in activities:
        entries = [e for e in as_list(node.get("evidence")) if isinstance(e, dict)]
        good = False
        for ev in entries:
            quote = ev.get("quote")
            kind = ev.get("kind")
            if not isinstance(quote, str) or len(quote.strip()) < 8:
                malformed += 1
                continue
            if not locator_shape_ok(kind, ev.get("locator")):
                malformed += 1
                continue
            good = True
            if quote.strip().lower() == norm_label(node.get("name", "")).lower():
                weak_quotes += 1
        if good:
            evidenced += 1
    evidence_coverage = evidenced / len(activities) if activities else 0.0

    # ---- value ----------------------------------------------------------
    scope = as_dict(process.get("scope"))
    trigger = (scope.get("trigger") or "").strip() if isinstance(scope.get("trigger"), str) else ""
    outcome = (scope.get("outcome") or "").strip() if isinstance(scope.get("outcome"), str) else ""
    value = as_dict(process.get("value"))
    outcome_block = as_dict(value.get("outcome"))
    statement = outcome_block.get("statement")
    outcome_text = outcome or (statement.strip() if isinstance(statement, str) else "")
    no_outcome_marker = isinstance(value.get("noQuantifiedOutcome"), dict)

    # ---- names ----------------------------------------------------------
    name = norm_label(process.get("name", "")) if isinstance(process.get("name"), str) else ""
    name_is_file = bool(re.search(r"\.(pdf|png|jpe?g|mp4|mov|zip|ts|js|py|md)$", name, re.I))
    name_is_heading = is_heading(name) and len(words_of(name)) <= 3

    # ---- candidate leakage ----------------------------------------------
    node_ids = set(by_id)
    candidate_leak = [c.get("id") for c in as_list(process.get("candidates"))
                      if isinstance(c, dict) and c.get("id") in node_ids]

    # ------------------------------------------------------------------ #
    # Identity checks
    # ------------------------------------------------------------------ #
    if not name or name_is_file or name_is_heading or len(words_of(name)) < 1:
        rep.add("P01", f"Process name '{name or '(empty)'}' does not identify a process", None)

    if len(activities) < 2:
        rep.add("P02", f"{len(activities)} activity node(s); a process needs at least 2", None)

    transition_edges = sum(
        1 for edge in edges
        if (edge_ends(edge)[0] in activity_ids or edge_ends(edge)[1] in activity_ids)
        and edge_ends(edge)[0] in by_id and edge_ends(edge)[1] in by_id
    )
    if transition_edges == 0:
        rep.add("P03", "No sequence flow connects any activity; the payload is a list", None)

    if not starts or not ends:
        rep.add("P04", "Missing start or end event, so no process path exists", None)
    else:
        path_exists = any(end["id"] in reachable_from_start for end in ends)
        if not path_exists:
            rep.add("P04", "No directed path from a start event to an end event", None)

    if starts and ends:
        stranded = sorted(activity_ids - on_path)
        if stranded:
            rep.add("P05", f"{len(stranded)} activity node(s) not on a start-to-end path: "
                           f"{', '.join(str(x) for x in stranded[:5])}", stranded[0])

    if activities and action_ratio < 0.7:
        bad = [n.get("id") for n in activities if not is_action_label(n.get("name", ""))]
        rep.add("P07", f"Only {action_ratio:.0%} of activity names are verb-object; "
                       f"examples: {', '.join(str(x) for x in bad[:5])}", bad[0] if bad else None)

    entity_like = [n for n in nodes if n.get("type") in DATA_TYPES or looks_entity(n.get("name", ""))]
    entity_ratio = len(entity_like) / len(nodes) if nodes else 0.0
    if nodes and entity_ratio > 0.4:
        rep.add("P14", f"{entity_ratio:.0%} of nodes are data entities or field names", None)

    # ------------------------------------------------------------------ #
    # Compliance checks
    # ------------------------------------------------------------------ #
    if len(starts) != 1:
        rep.add("S09", f"{len(starts)} start event(s); exactly one is required", None)
    if len(ends) < 1:
        rep.add("S10", "No end event", None)

    if activities:
        if lane_coverage < 1.0:
            rep.add("P06", f"{len(missing_lane)} of {len(activities)} activities have no resolving lane "
                           f"({lane_coverage:.0%} coverage)", missing_lane[0] if missing_lane else None)
        elif not lanes:
            rep.add("P06", "No lanes declared, so actors are unbound", None)

    if not trigger or not outcome:
        missing = [k for k, v in (("trigger", trigger), ("outcome", outcome)) if not v]
        rep.add("P08", f"Missing scope field(s): {', '.join(missing)}", None)

    if outcome_text and looks_entity(outcome_text):
        rep.add("P09", f"Outcome '{outcome_text[:60]}' reads as a data field, not a result", None)

    if activities and evidence_coverage < 0.95:
        if not allow_unevidenced:
            rep.add("P10", f"Evidence coverage {evidence_coverage:.0%} of activities "
                           f"(threshold 95%)", None)
        elif evidence_coverage == 0:
            rep.add("P10", "No evidence at all (allowed by flag, still unverified)", None, weight=3)

    if malformed:
        rep.add("P11", f"{malformed} evidence entr(ies) with a malformed locator or short quote", None)

    if candidate_leak:
        rep.add("P12", f"{len(candidate_leak)} candidate id(s) also present in nodes[]",
                candidate_leak[0])

    if len(active_components) > 1:
        rep.add("P13", f"{len(active_components)} disconnected activity groups; "
                       f"split into processes[]", None)

    if duplicate_names or any(len(n) > 80 for n in names) or any(n.endswith(".") for n in names):
        rep.add("P15", "Activity labels contain duplicates, overlong text or trailing punctuation", None)

    # ---- advisory quality signals (never change the verdict) -------------
    if weak_quotes:
        rep.add("P16", f"{weak_quotes} quote(s) repeat the element label instead of showing behaviour",
                None, weight=min(4, weak_quotes * 2))

    if not value or not (value.get("lever") or outcome_text or no_outcome_marker):
        rep.add("P17", "Value block has no lever, outcome statement or noQuantifiedOutcome marker", None)

    low_confidence = [n.get("id") for n in nodes
                      if is_number(n.get("confidence")) and n["confidence"] < 0.7]
    if low_confidence:
        rep.add("P18", f"{len(low_confidence)} node(s) below 0.70 confidence are in nodes[]",
                low_confidence[0], weight=min(4, len(low_confidence) * 2))

    # ------------------------------------------------------------------ #
    # Pattern classification
    # ------------------------------------------------------------------ #
    node_names = [norm_label(n.get("name", "")) for n in nodes if norm_label(n.get("name", ""))]
    heading_ratio = (sum(1 for n in node_names if is_heading(n)) / len(node_names)) if node_names else 0.0
    org_ratio = (sum(1 for n in node_names if is_org(n)) / len(node_names)) if node_names else 0.0
    if not nodes:
        pattern = "unstructured"
    elif heading_ratio >= 0.5:
        pattern = "document_summary"
    elif org_ratio >= 0.5:
        pattern = "org_chart"
    elif len(activities) < 2:
        if entity_ratio >= 0.4:
            pattern = "entity_list"
        elif len(activities) == 1:
            pattern = "single_activity"
        else:
            pattern = "unstructured"
    elif entity_ratio > 0.4:
        pattern = "entity_list"
    elif transition_edges == 0:
        pattern = "unstructured"
    elif len(active_components) > 1:
        pattern = "multi_process"
    else:
        pattern = "process"

    score = max(0, 100 - sum(f["weight"] for f in rep.findings))

    identity_failed = bool(rep.gates["identity"])
    structure_failed = bool(rep.gates["structure"])
    compliance_failed = bool(rep.gates["compliance"])

    if structure_failed:
        verdict = "not_a_process"
    elif identity_failed:
        verdict = "not_a_process"
    elif compliance_failed:
        verdict = "partial_process"
    else:
        verdict = "business_process"

    # Keep the score band consistent with the verdict.
    if verdict == "not_a_process":
        score = min(score, 45)
    elif verdict == "partial_process":
        score = max(50, min(score, 74))

    metrics = {
        "nodes": len(nodes),
        "activities": len(activities),
        "gateways": len(gateways),
        "events": sum(1 for n in nodes if n.get("type") in EVENT_TYPES),
        "dataNodes": len(data_nodes),
        "edges": valid_edges,
        "lanes": len(lanes),
        "startEvents": len(starts),
        "endEvents": len(ends),
        "components": len(active_components),
        "activityOnPathRatio": round((len(activity_ids & on_path) / len(activity_ids)), 3) if activity_ids else 0.0,
        "laneCoverage": round(lane_coverage, 3),
        "evidenceCoverage": round(evidence_coverage, 3),
        "actionLabelRatio": round(action_ratio, 3),
        "entityNodeRatio": round(entity_ratio, 3),
        "weakQuotes": weak_quotes,
    }

    return {
        "verdict": verdict,
        "score": score,
        "pattern": pattern,
        "identityPass": not identity_failed and not structure_failed,
        "compliancePass": not compliance_failed,
        "failedIdentity": rep.gates["identity"],
        "failedCompliance": rep.gates["compliance"],
        "failedStructure": rep.gates["structure"],
        "metrics": metrics,
        "findings": rep.findings,
    }


# --------------------------------------------------------------------------- #
# Document handling
# --------------------------------------------------------------------------- #

def empty_metrics():
    return {
        "nodes": 0, "activities": 0, "gateways": 0, "events": 0, "dataNodes": 0,
        "edges": 0, "lanes": 0, "startEvents": 0, "endEvents": 0, "components": 0,
        "activityOnPathRatio": 0.0, "laneCoverage": 0.0, "evidenceCoverage": 0.0,
        "actionLabelRatio": 0.0, "entityNodeRatio": 0.0, "weakQuotes": 0,
    }


def declared_flag(doc):
    classification = as_dict(doc.get("classification"))
    if "isBusinessProcess" in classification:
        return classification.get("isBusinessProcess"), classification.get("pattern")
    if "isBusinessProcess" in doc:
        return doc.get("isBusinessProcess"), doc.get("pattern")
    return None, None


def validate_document(doc, source="<memory>", allow_unevidenced=False):
    if not isinstance(doc, dict):
        raise ValueError("top-level JSON value must be an object")

    declared, declared_pattern = declared_flag(doc)
    kind = doc.get("kind")
    processes = [p for p in as_list(doc.get("processes")) if isinstance(p, dict)]

    if isinstance(doc.get("process"), dict):
        targets, scope = [doc["process"]], "single"
    elif len(processes) >= 1:
        targets, scope = processes, "multiple"
    elif "nodes" in doc or "edges" in doc:
        targets, scope = [doc], "single"
    else:
        targets = []
        scope = "none"

    if not targets:
        abstained = (declared is False) or kind == "notBusinessProcess"
        if not abstained:
            raise ValueError("no process payload found (expected 'process', 'processes' or 'nodes')")
        pattern = declared_pattern if declared_pattern in PATTERNS else "unstructured"
        return {
            "validatorVersion": VALIDATOR_VERSION,
            "file": str(source),
            "verdict": "not_a_process",
            "score": 100,
            "pattern": pattern,
            "scope": "none",
            "processCount": 0,
            "declared": declared,
            "declaredPattern": declared_pattern,
            "agreement": True,
            "abstained": True,
            "summary": "Model abstained with no asserted process; abstention is the expected outcome here.",
            "gates": {"identity": {"pass": True, "failed": []},
                      "compliance": {"pass": True, "failed": []}},
            "metrics": empty_metrics(),
            "findings": [],
            "remediation": [],
            "verbatim": "not applicable",
            "processes": [],
        }

    per = [validate_process(p, allow_unevidenced) for p in targets]
    primary = per[0]

    # Aggregate: the weakest process decides the document verdict.
    rank = {"not_a_process": 0, "partial_process": 1, "business_process": 2}
    verdict = min((r["verdict"] for r in per), key=lambda v: rank[v])
    score = min(r["score"] for r in per)

    if scope == "multiple":
        # A clean explicit split is legitimate; pattern reflects the split, not a merge.
        if verdict == "business_process":
            pattern = "process"
        elif len(targets) > 1 and verdict != "not_a_process":
            pattern = "multi_process"
        else:
            pattern = primary["pattern"]
    else:
        pattern = primary["pattern"]

    if kind == "notBusinessProcess" and targets and primary["verdict"] != "not_a_process":
        verdict = "partial_process"

    if kind == "businessProcess" and scope == "multiple":
        verdict = min(verdict, "partial_process", key=lambda v: rank[v])

    agreement = None
    if declared is not None:
        agreement = (bool(declared) == (verdict != "not_a_process"))

    failed_identity = sorted({c for r in per for c in r["failedIdentity"]})
    failed_compliance = sorted({c for r in per for c in r["failedCompliance"]})
    failed_structure = sorted({c for r in per for c in r["failedStructure"]})

    findings = []
    seen_codes = set()
    for r in per:
        for f in r["findings"]:
            key = (f["code"], f["message"])
            if key in seen_codes:
                continue
            seen_codes.add(key)
            findings.append(f)

    remediation = []
    for f in findings:
        rule = RULES.get(f["code"])
        if rule and rule[3] and rule[3] not in remediation:
            remediation.append(rule[3])

    summary = build_summary(verdict, pattern, primary)

    report = {
        "validatorVersion": VALIDATOR_VERSION,
        "file": str(source),
        "verdict": verdict,
        "score": score,
        "pattern": pattern,
        "scope": scope,
        "processCount": len(targets),
        "declared": declared,
        "declaredPattern": declared_pattern,
        "agreement": agreement,
        "abstained": False,
        "summary": summary,
        "gates": {
            "identity": {"pass": not failed_identity and not failed_structure,
                         "failed": failed_identity + failed_structure},
            "compliance": {"pass": not failed_compliance, "failed": failed_compliance},
        },
        "metrics": primary["metrics"],
        "findings": findings,
        "remediation": remediation,
        "verbatim": "unverified offline",
        "processes": [
            {"index": i, "verdict": r["verdict"], "score": r["score"], "pattern": r["pattern"],
             "metrics": r["metrics"]}
            for i, r in enumerate(per)
        ] if scope == "multiple" else [],
    }
    return report


def count_noun(count, singular, plural=None):
    if count == 1:
        return f"{count} {singular}"
    return f"{count} {plural or singular + 's'}"


def build_summary(verdict, pattern, primary):
    m = primary["metrics"]
    base = (f"{count_noun(m['activities'], 'activity', 'activities')}, "
            f"{count_noun(m['lanes'], 'lane')}, {count_noun(m['edges'], 'edge')}, "
            f"{m['evidenceCoverage']:.0%} evidence coverage")
    if verdict == "business_process":
        return f"Ordered, actor-bound process. {base}."
    if verdict == "partial_process":
        return f"Process structure present but contract incomplete. {base}."
    reasons = {
        "entity_list": "Nodes are data entities or field names, not activities.",
        "document_summary": "Content is document structure, not process sequence.",
        "org_chart": "Content is a reporting hierarchy, not process flow.",
        "single_activity": "Only one activity exists; ordering and hand-off are absent.",
        "multi_process": "Several disconnected processes are merged into one graph.",
        "unstructured": "No ordered, actor-bound activities could be identified.",
    }
    return f"Not a business process. {reasons.get(pattern, '')} {base}.".strip()


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

BAND = {"business_process": "BUSINESS PROCESS",
        "partial_process": "PARTIAL PROCESS",
        "not_a_process": "NOT A PROCESS"}


def render_text(report, verbose=False):
    out = []
    line = "-" * 68
    out.append(f"EXTRACTION VALIDATION  {Path(report['file']).name}")
    out.append(line)
    out.append(f"Verdict    {BAND[report['verdict']]}")
    out.append(f"Score      {report['score']} / 100")
    out.append(f"Pattern    {report['pattern']}")
    out.append(f"Scope      {report['scope']}"
               + (f" ({report['processCount']} processes)" if report["scope"] == "multiple" else ""))
    if report.get("abstained"):
        out.append("Checks     not applicable (no payload asserted)")
    else:
        out.append(f"Identity   {'pass' if report['gates']['identity']['pass'] else 'FAIL'}"
                   f"   Compliance {'pass' if report['gates']['compliance']['pass'] else 'FAIL'}")
    if report["declared"] is not None:
        agree = "yes" if report["agreement"] else "NO"
        out.append(f"Declared   isBusinessProcess={str(report['declared']).lower()}   agreement {agree}")
    if report.get("abstained"):
        out.append("Abstained  yes, correctly")

    m = report["metrics"]
    if not report.get("abstained"):
        out.append("")
        out.append("Metrics")
        out.append(f"  activities {m['activities']}/{m['nodes']} nodes   lanes {m['lanes']}   "
                   f"edges {m['edges']}   gateways {m['gateways']}")
        out.append(f"  starts {m['startEvents']}   ends {m['endEvents']}   "
                   f"components {m['components']}")
        out.append(f"  on-path activities {m['activityOnPathRatio']:.0%}   "
                   f"lane coverage {m['laneCoverage']:.0%}")
        out.append(f"  evidence coverage {m['evidenceCoverage']:.0%}   "
                   f"action labels {m['actionLabelRatio']:.0%}   "
                   f"entity nodes {m['entityNodeRatio']:.0%}")

    out.append("")
    out.append(f"Findings ({len(report['findings'])})")
    if not report["findings"]:
        out.append("  none")
    for f in report["findings"]:
        where = f" [{f['elementId']}]" if f.get("elementId") else ""
        out.append(f"  {f['code']:<4} {f['message']}{where}")

    if report["remediation"]:
        out.append("")
        out.append("Remediation")
        for item in report["remediation"]:
            out.append(f"  - {item}")

    if verbose:
        out.append("")
        out.append("Process breakdown")
        for p in report["processes"]:
            out.append(f"  #{p['index']} {p['verdict']} score {p['score']} "
                       f"({p['metrics']['activities']} activities)")
        out.append("")
        out.append(f"Verbatim quotes: {report['verbatim']}")
        out.append(f"Validator: {report['validatorVersion']}")

    out.append(line)
    out.append(report["summary"])
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Self-test against bundled fixtures
# --------------------------------------------------------------------------- #

def run_self_test():
    here = Path(__file__).resolve().parent
    cases = [
        ("fixtures/valid-invoice-to-cash.json", "business_process", "process"),
        ("fixtures/entity-list.json", "not_a_process", "entity_list"),
        ("fixtures/doc-summary.json", "not_a_process", "document_summary"),
        ("fixtures/org-chart.json", "not_a_process", "org_chart"),
        ("fixtures/single-task.json", "not_a_process", "single_activity"),
        ("fixtures/multi-process.json", "partial_process", "multi_process"),
        ("fixtures/process-no-actors.json", "partial_process", "process"),
        ("fixtures/noun-labels.json", "partial_process", "process"),
        ("fixtures/abstain-entity-list.json", "not_a_process", "entity_list"),
    ]
    failures = 0
    for rel, want_verdict, want_pattern in cases:
        path = here / rel
        try:
            doc = json.loads(path.read_text())
            report = validate_document(doc, rel)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {rel}: {exc}")
            failures += 1
            continue
        ok = report["verdict"] == want_verdict and report["pattern"] == want_pattern
        status = "ok  " if ok else "FAIL"
        print(f"{status} {rel:<36} {report['verdict']:<16} {report['pattern']:<17} {report['score']:>3}")
        if not ok:
            print(f"     expected {want_verdict}/{want_pattern}")
            failures += 1
    print("-" * 68)
    print(f"{len(cases) - failures}/{len(cases)} fixtures matched")
    return 1 if failures else 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="validate_extraction.py",
        description="Validate that an extraction payload is a business process.",
    )
    parser.add_argument("file", nargs="?", help="JSON payload to validate")
    parser.add_argument("--json", action="store_true", help="emit machine-readable report")
    parser.add_argument("--verbose", action="store_true", help="include process breakdown")
    parser.add_argument("--allow-unevidenced", action="store_true",
                        help="downgrade the evidence gate for draft extractions")
    parser.add_argument("--self-test", action="store_true", help="run bundled fixtures")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()
    if not args.file:
        parser.print_help()
        return 3

    try:
        doc = json.loads(Path(args.file).read_text(encoding="utf-8"))
        report = validate_document(doc, args.file, args.allow_unevidenced)
    except FileNotFoundError:
        print(f"error: file not found: {args.file}", file=sys.stderr)
        return 3
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}",
              file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_text(report, args.verbose))

    return {"business_process": 0, "partial_process": 1, "not_a_process": 2}[report["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
