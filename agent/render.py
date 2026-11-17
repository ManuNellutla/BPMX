"""
Projections of the Canonical Process Model.

The CPM is the artefact; BPMN, Markdown and HTML are generated views of it.
Nothing here writes back into the model, so a re-render cannot change meaning.
"""

from __future__ import annotations

import html
import shutil
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from validation import PROMPTS_DIR

EVIDENCE_NS = "https://process-atlas.local/schema/1.0"

BPMN_TAGS = {
    "startEvent": "startEvent",
    "endEvent": "endEvent",
    "intermediateCatchEvent": "intermediateCatchEvent",
    "intermediateThrowEvent": "intermediateThrowEvent",
    "task": "task",
    "userTask": "userTask",
    "serviceTask": "serviceTask",
    "manualTask": "manualTask",
    "businessRuleTask": "businessRuleTask",
    "sendTask": "sendTask",
    "receiveTask": "receiveTask",
    "scriptTask": "scriptTask",
    "callActivity": "callActivity",
    "subProcess": "subProcess",
    "exclusiveGateway": "exclusiveGateway",
    "parallelGateway": "parallelGateway",
    "inclusiveGateway": "inclusiveGateway",
    "eventBasedGateway": "eventBasedGateway",
}

KIND_PILL = {
    "business_process": ("pill--ok", "business process"),
    "partial_process": ("pill--warn", "partial"),
    "not_a_process": ("pill--risk", "not a process"),
}


def _node_size(node: dict) -> tuple[int, int]:
    kind = node.get("type")
    if kind in ("startEvent", "endEvent") or (kind or "").endswith("Event"):
        return 36, 36
    if (kind or "").endswith("Gateway"):
        return 44, 44
    return 140, 74


def layout(process: dict) -> dict:
    """Deterministic left-to-right layout: lane bands, longest-path columns."""
    lanes = process.get("lanes") or [{"id": "lane_default", "name": "Default"}]
    nodes = [n for n in process.get("nodes", []) if isinstance(n, dict) and n.get("id")]
    edges = [e for e in process.get("edges", []) if isinstance(e, dict)]
    lane_index = {lane.get("id"): i for i, lane in enumerate(lanes)}
    by_id = {n["id"]: n for n in nodes}

    indegree = {n["id"]: 0 for n in nodes}
    adjacency: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for edge in edges:
        src, dst = edge.get("from"), edge.get("to")
        if src in by_id and dst in by_id:
            adjacency[src].append(dst)
            indegree[dst] += 1

    starts = [n["id"] for n in nodes if n.get("type") == "startEvent"]
    queue = [nid for nid in indegree if indegree[nid] == 0]
    depth = {nid: 0 for nid in by_id}
    order: list[str] = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        for nxt in adjacency[current]:
            depth[nxt] = max(depth[nxt], depth[current] + 1)
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if len(order) < len(nodes):  # cycle guard: keep declared order
        for i, node in enumerate(nodes):
            depth.setdefault(node["id"], i)

    placed = {}
    lane_height = 180
    for node in nodes:
        width, height = _node_size(node)
        lane = lane_index.get(node.get("laneId"), 0)
        column = depth.get(node["id"], 0)
        center_x = 200 + column * 220
        center_y = lane * lane_height + lane_height // 2
        placed[node["id"]] = {
            "x": center_x - width // 2,
            "y": center_y - height // 2,
            "w": width,
            "h": height,
            "cx": center_x,
            "cy": center_y,
        }
    width = max((p["x"] + p["w"] for p in placed.values()), default=800) + 160
    return {
        "nodes": placed,
        "lanes": {
            lane.get("id"): {
                "x": 40,
                "y": i * lane_height,
                "w": max(width, 900),
                "h": lane_height,
            }
            for i, lane in enumerate(lanes)
        },
        "width": max(width, 900),
        "height": lane_height * len(lanes),
        "starts": starts,
        "order": order,
    }


def _extension(node: dict) -> str:
    entries = []
    for ev in node.get("evidence", []) or []:
        if not isinstance(ev, dict):
            continue
        locator = ev.get("locator") or {}
        attrs = {
            "sourceId": ev.get("sourceId", ""),
            "kind": ev.get("kind", ""),
            "quote": ev.get("quote", ""),
            "confidence": ev.get("confidence", ""),
        }
        for key in ("page", "path", "file", "startLine", "endLine", "start", "end"):
            if key in locator:
                attrs[key] = locator[key]
        if "bbox" in locator:
            attrs["bbox"] = ",".join(str(v) for v in locator["bbox"])
        rendered = " ".join(f"{k}={quoteattr(str(v))}" for k, v in attrs.items() if v != "")
        entries.append(f"        <atlas:evidence {rendered}/>")
    confidence = node.get("confidence")
    if confidence is not None:
        entries.append(f"        <atlas:confidence value={quoteattr(str(confidence))}/>")
    lane = node.get("laneId")
    if lane:
        entries.append(f"        <atlas:laneRef>{escape(str(lane))}</atlas:laneRef>")
    if not entries:
        return ""
    return "      <bpmn:extensionElements>\n" + "\n".join(entries) + "\n      </bpmn:extensionElements>\n"


def to_bpmn(process: dict) -> str:
    lanes = process.get("lanes") or [{"id": "lane_default", "name": "Default"}]
    nodes = [n for n in process.get("nodes", []) if isinstance(n, dict) and n.get("id")]
    edges = [e for e in process.get("edges", []) if isinstance(e, dict)]
    geo = layout(process)
    process_id = process.get("id") or "prc_generated"

    incoming: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    outgoing: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for edge in edges:
        src, dst = edge.get("from"), edge.get("to")
        if src in outgoing and dst in incoming:
            outgoing[src].append(edge.get("id", ""))
            incoming[dst].append(edge.get("id", ""))

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"',
        '    xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"',
        '    xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"',
        '    xmlns:di="http://www.omg.org/spec/DD/20100524/DI"',
        f'    xmlns:atlas="{EVIDENCE_NS}"',
        f'    id="Definitions_{escape(process_id)}"',
        '    targetNamespace="https://process-atlas.local/bpmn">',
        f'  <bpmn:process id={quoteattr(process_id)} name={quoteattr(process.get("name", ""))} isExecutable="false">',
    ]

    parts.append('    <bpmn:laneSet id="LaneSet_1">')
    for lane in lanes:
        lane_nodes = [n["id"] for n in nodes if n.get("laneId") == lane.get("id")]
        parts.append(f'      <bpmn:lane id={quoteattr(str(lane.get("id")))} name={quoteattr(str(lane.get("name", "")))}>')
        for nid in lane_nodes:
            parts.append(f'        <bpmn:flowNodeRef>{escape(nid)}</bpmn:flowNodeRef>')
        parts.append('      </bpmn:lane>')
    parts.append('    </bpmn:laneSet>')

    for node in nodes:
        tag = BPMN_TAGS.get(node.get("type", "task"), "task")
        attrs = f'id={quoteattr(str(node["id"]))} name={quoteattr(str(node.get("name", "")))}'
        if tag.endswith("Gateway"):
            direction = "Diverging" if len(outgoing[node["id"]]) > 1 else "Converging"
            attrs += f' gatewayDirection="{direction}"'
        if tag == "serviceTask":
            attrs += ' implementation="##unspecified"'
        parts.append(f'    <bpmn:{tag} {attrs}>')
        ext = _extension(node)
        if ext:
            parts.append(ext.rstrip("\n"))
        for eid in incoming[node["id"]]:
            parts.append(f'      <bpmn:incoming>{escape(eid)}</bpmn:incoming>')
        for eid in outgoing[node["id"]]:
            parts.append(f'      <bpmn:outgoing>{escape(eid)}</bpmn:outgoing>')
        parts.append(f'    </bpmn:{tag}>')

    for edge in edges:
        attrs = (f'id={quoteattr(str(edge.get("id")))} '
                 f'sourceRef={quoteattr(str(edge.get("from")))} '
                 f'targetRef={quoteattr(str(edge.get("to")))}')
        if edge.get("condition"):
            attrs += f' name={quoteattr(str(edge["condition"]))}'
        if edge.get("isDefault"):
            attrs += ' isDefault="true"'
        parts.append(f'    <bpmn:sequenceFlow {attrs}/>')

    parts.append('  </bpmn:process>')

    # ---- diagram interchange ------------------------------------------- #
    parts += [
        f'  <bpmndi:BPMNDiagram id="Diagram_{escape(process_id)}">',
        f'    <bpmndi:BPMNPlane id="Plane_{escape(process_id)}" bpmnElement={quoteattr(process_id)}>',
    ]
    for lane in lanes:
        box = geo["lanes"][lane.get("id")]
        parts += [
            f'      <bpmndi:BPMNShape id="Shape_{escape(str(lane.get("id")))}" bpmnElement={quoteattr(str(lane.get("id")))} isHorizontal="true">',
            f'        <dc:Bounds x="{box["x"]}" y="{box["y"]}" width="{box["w"]}" height="{box["h"]}"/>',
            '      </bpmndi:BPMNShape>',
        ]
    for node in nodes:
        box = geo["nodes"][node["id"]]
        parts += [
            f'      <bpmndi:BPMNShape id="Shape_{escape(str(node["id"]))}" bpmnElement={quoteattr(str(node["id"]))}>',
            f'        <dc:Bounds x="{box["x"]}" y="{box["y"]}" width="{box["w"]}" height="{box["h"]}"/>',
            '      </bpmndi:BPMNShape>',
        ]
    for i, edge in enumerate(edges):
        src = geo["nodes"].get(edge.get("from"))
        dst = geo["nodes"].get(edge.get("to"))
        if not src or not dst:
            continue
        sx, sy = src["x"] + src["w"], src["cy"]
        tx, ty = dst["x"], dst["cy"]
        if abs(sy - ty) < 1:
            points = [(sx, sy), (tx, ty)]
        else:
            mid = (sx + tx) // 2 if tx > sx else sx + 60
            points = [(sx, sy), (mid, sy), (mid, ty), (tx, ty)]
        parts.append(f'      <bpmndi:BPMNEdge id="Edge_{escape(str(edge.get("id", i)))}" bpmnElement={quoteattr(str(edge.get("id", "")))}>')
        for x, y in points:
            parts.append(f'        <di:waypoint x="{x}" y="{y}"/>')
        parts.append('      </bpmndi:BPMNEdge>')
    parts += [
        '    </bpmndi:BPMNPlane>',
        '  </bpmndi:BPMNDiagram>',
        '</bpmn:definitions>',
        '',
    ]
    return "\n".join(parts)


def _md(text) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def to_markdown(process: dict, report: dict, audit: dict) -> str:
    verdict = report.get("verdict", "unknown")
    lanes = {lane.get("id"): lane.get("name") for lane in process.get("lanes", [])}
    nodes = process.get("nodes", [])
    activities = [n for n in nodes if (n.get("type") or "").endswith("Task")]
    gateways = [n for n in nodes if (n.get("type") or "").endswith("Gateway")]
    events = [n for n in nodes if (n.get("type") or "").endswith("Event")]
    value = process.get("value") or {}
    outcome = value.get("outcome") or {}
    scope = process.get("scope") or {}

    out = [
        f"# {process.get('name', 'Process')}",
        "",
        f"> Process Atlas extraction · **{verdict.replace('_', ' ')}** · score {report.get('score', 0)}/100 "
        f"· pattern `{report.get('pattern', '')}` · {len(activities)} activities",
        "",
        "## Scope",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Domain | {_md(process.get('domain', ''))} |",
        f"| Trigger | {_md(scope.get('trigger', ''))} |",
        f"| Outcome | {_md(scope.get('outcome', ''))} |",
        f"| Status | {_md(process.get('status', ''))} |",
        f"| Version | {process.get('version', 1)} |",
        "",
        _md(process.get("summary", "")) or "No summary.",
        "",
        "## Actors",
        "",
        "| Lane | Type | Activities |",
        "| --- | --- | --- |",
    ]
    for lane_id, lane_name in lanes.items():
        count = sum(1 for n in activities if n.get("laneId") == lane_id)
        lane_type = next((l.get("type") for l in process.get("lanes", []) if l.get("id") == lane_id), "")
        out.append(f"| {_md(lane_name)} | {_md(lane_type)} | {count} |")

    out += ["", "## Steps", "", "| # | Step | Actor | Type | Confidence | Evidence |",
            "| --- | --- | --- | --- | --- | --- |"]
    for i, node in enumerate(activities, start=1):
        evidence = (node.get("evidence") or [{}])[0]
        locator = evidence.get("locator") or {}
        where = f"`{locator.get('path', '?')}:{locator.get('startLine', '?')}`"
        out.append(f"| {i} | {_md(node.get('name'))} | {_md(lanes.get(node.get('laneId'), '—'))} | "
                   f"{_md(node.get('type'))} | {node.get('confidence', '')} | {where} |")

    if gateways:
        out += ["", "## Decisions", "", "| Gateway | Actor | Outgoing conditions |",
                "| --- | --- | --- |"]
        for gateway in gateways:
            branches = [e for e in process.get("edges", []) if e.get("from") == gateway.get("id")]
            labels = ", ".join(str(e.get("condition") or "default") for e in branches)
            out.append(f"| {_md(gateway.get('name'))} | {_md(lanes.get(gateway.get('laneId'), '—'))} "
                       f"| {_md(labels)} |")

    out += ["", "## Business value", ""]
    if outcome:
        out += [
            f"**Lever:** {', '.join(value.get('lever') or []) or '—'}",
            "",
            "| Metric | Baseline | Target | Unit | Horizon | Basis |",
            "| --- | --- | --- | --- | --- | --- |",
            f"| {_md(outcome.get('kpi') or outcome.get('statement'))} | {outcome.get('baseline', '—') or '—'} "
            f"| {outcome.get('target', '—') or '—'} | {_md(outcome.get('unit') or '—')} "
            f"| {_md(outcome.get('horizon') or '—')} | {_md(outcome.get('basis') or '—')} |",
        ]
        if outcome.get("statement"):
            out += ["", f"> {outcome['statement']}"]
    else:
        reason = (value.get("noQuantifiedOutcome") or {}).get("reason") or "No quantified outcome stated."
        out += [f"No quantified outcome. {_md(reason)}", f"", f"**Lever:** {', '.join(value.get('lever') or []) or '—'}"]

    out += ["", "## Evidence", "",
            f"Quotes verified against the repository: **{audit.get('matched', 0)}/{audit.get('checked', 0)}** "
            f"({audit.get('coverage', 1.0):.0%}).", ""]
    for i, node in enumerate(activities, start=1):
        for ev in node.get("evidence", [])[:1]:
            locator = ev.get("locator") or {}
            out += [
                f"**{i}. {_md(node.get('name'))}** — `{locator.get('path', '?')}:{locator.get('startLine', '?')}`",
                "",
                f"    {_md(ev.get('quote', ''))}",
                "",
            ]

    if process.get("assumptions"):
        out += ["## Assumptions", ""] + [f"- {_md(a)}" for a in process["assumptions"]] + [""]
    if process.get("openQuestions"):
        out += ["## Open questions", ""] + [f"- {_md(q)}" for q in process["openQuestions"]] + [""]

    out += [
        "## Validation",
        "",
        f"- Verdict: `{verdict}`",
        f"- Score: {report.get('score', 0)} / 100",
        f"- Identity gate: {'pass' if report.get('gates', {}).get('identity', {}).get('pass') else 'fail'}",
        f"- Compliance gate: {'pass' if report.get('gates', {}).get('compliance', {}).get('pass') else 'fail'}",
    ]
    for finding in report.get("findings", []):
        out.append(f"- `{finding.get('code')}` {finding.get('message')}")
    if not report.get("findings"):
        out.append("- No findings.")
    out += ["", f"Validator `{report.get('validatorVersion', '')}` · prompt `{process.get('provenance', {}).get('promptVersion', '')}`.", ""]
    return "\n".join(out)


DASHBOARD_CSS = """
  .atlas-head { padding:28px 0 8px; border-bottom:1px solid var(--line); margin-bottom:24px; }
  .atlas-head h1 { margin:0 0 6px; font-size:26px; color:var(--blue-900); letter-spacing:-0.02em; }
  .atlas-head p { margin:0; color:var(--muted); font-size:14px; }
  .atlas-meta { display:flex; flex-wrap:wrap; gap:8px; margin:14px 0 0; }
  .kpis { display:grid; grid-template-columns:repeat(4, 1fr); gap:14px; margin:24px 0 30px; }
  .kpi { background:#fff; border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
  .kpi .v { font-size:24px; font-weight:700; color:var(--blue-900); letter-spacing:-0.02em; }
  .kpi .k { font-size:11px; text-transform:uppercase; letter-spacing:.09em; color:var(--muted-2); margin-top:2px; }
  .score { font-variant-numeric:tabular-nums; font-weight:700; }
  .proc-name { font-weight:650; color:var(--blue-900); text-decoration:none; }
  .proc-name:hover { text-decoration:underline; }
  .links a { font-size:12px; color:var(--blue-700); text-decoration:none; margin-right:10px; }
  .links a:hover { text-decoration:underline; }
  .note { background:var(--blue-50); border:1px solid var(--blue-100); border-radius:10px; padding:14px 18px; margin:24px 0; font-size:13px; color:var(--blue-800); }
  .foot { color:var(--muted-2); font-size:12px; margin:36px 0 40px; padding-top:16px; border-top:1px solid var(--line); }
  @media (max-width:800px){ .kpis{grid-template-columns:repeat(2,1fr);} }
"""


def dashboard(run: dict) -> str:
    project = run.get("project", {})
    processes = run.get("processes", [])
    total = len(processes)
    passed = sum(1 for p in processes if p.get("verdict") == "business_process")
    partial = sum(1 for p in processes if p.get("verdict") == "partial_process")
    failed = total - passed - partial
    acts = sum(p.get("activities", 0) for p in processes)
    checked = sum(p.get("audit", {}).get("checked", 0) for p in processes)
    matched = sum(p.get("audit", {}).get("matched", 0) for p in processes)

    rows = []
    for proc in processes:
        pill, label = KIND_PILL.get(proc.get("verdict"), ("pill--later", proc.get("verdict", "")))
        folder = proc.get("folder", "")
        title_href = proc.get("md") or proc.get("extraction") or proc.get("report") or folder
        links = []
        if proc.get("bpmn"):
            links.append(f'<a href="{html.escape(proc["bpmn"])}">BPMN</a>')
        if proc.get("cpm"):
            links.append(f'<a href="{html.escape(proc["cpm"])}">CPM</a>')
        links.append(f'<a href="{html.escape(proc.get("report") or folder)}">Report</a>')
        rows.append(
            "<tr>"
            f'<td><a class="proc-name" href="{html.escape(title_href)}">{html.escape(proc.get("name", ""))}</a>'
            f'<div style="font-size:12px;color:var(--muted)">{html.escape(proc.get("domain", ""))}</div></td>'
            f'<td><span class="pill {pill}">{html.escape(label)}</span></td>'
            f'<td class="score">{proc.get("score", 0)}</td>'
            f'<td>{proc.get("activities", 0)}</td>'
            f'<td>{proc.get("lanes", 0)}</td>'
            f'<td>{proc.get("audit", {}).get("matched", 0)}/{proc.get("audit", {}).get("checked", 0)}</td>'
            f'<td class="links">{"".join(links)}</td>'
            "</tr>"
        )

    note = (
        "Generated from source code. Every activity carries a code locator and a verbatim quote; "
        "the evidence column counts quotes that were found at the stated file and line. "
        "A <em>partial</em> verdict means the model is a real sequence but the contract is incomplete."
    )

    value_rows = []
    for proc in processes:
        value = proc.get("value") or {}
        outcome = value.get("outcome") or {}
        if outcome:
            metric = outcome.get("kpi") or outcome.get("statement") or "—"
            baseline = outcome.get("baseline")
            target = outcome.get("target")
            movement = (f"{baseline} → {target} {outcome.get('unit', '')}".strip()
                        if baseline is not None or target is not None else "not quantified")
            value_rows.append(
                "<tr>"
                f'<td>{html.escape(proc.get("name", ""))}</td>'
                f'<td>{html.escape(", ".join(value.get("lever") or []))}</td>'
                f'<td>{html.escape(str(metric))}</td>'
                f'<td>{html.escape(movement)}</td>'
                f'<td>{html.escape(str(outcome.get("horizon") or "—"))}</td>'
                f'<td><span class="pill pill--later">{html.escape(str(outcome.get("basis") or "—"))}</span></td>'
                "</tr>"
            )
        else:
            reason = (value.get("noQuantifiedOutcome") or {}).get("reason") or "No quantified outcome."
            value_rows.append(
                "<tr>"
                f'<td>{html.escape(proc.get("name", ""))}</td>'
                f'<td>{html.escape(", ".join(value.get("lever") or ["—"]))}</td>'
                f'<td colspan="3" style="color:var(--muted)">{html.escape(str(reason))}</td>'
                '<td><span class="pill pill--warn">unquantified</span></td>'
                "</tr>"
            )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(project.get("name", "Process Atlas"))} — extraction report</title>
<link rel="stylesheet" href="assets/styles.css">
<style>{DASHBOARD_CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="atlas-head">
    <h1>{html.escape(project.get("name", "Process Atlas"))}</h1>
    <p>Process Atlas extraction report · project <code>{html.escape(project.get("id", ""))}</code></p>
    <div class="atlas-meta">
      <span class="pill pill--core">source code</span>
      <span class="pill pill--unit">{html.escape(run.get("provider", ""))}</span>
      <span class="pill pill--later">{html.escape(run.get("model", ""))}</span>
      <span class="pill pill--e2e">validator {html.escape(str(run.get("validatorVersion", "")))}</span>
    </div>
  </header>

  <section class="kpis">
    <div class="kpi"><div class="v">{total}</div><div class="k">processes</div></div>
    <div class="kpi"><div class="v">{passed}</div><div class="k">accepted</div></div>
    <div class="kpi"><div class="v">{partial + failed}</div><div class="k">need review</div></div>
    <div class="kpi"><div class="v">{matched}/{checked}</div><div class="k">quotes verified</div></div>
  </section>

  <div class="note">{note}</div>

  <section class="block">
    <h2 class="sec" style="margin-top:0">Extracted processes</h2>
    <div class="tablewrap">
      <table class="tbl">
        <thead><tr><th>Process</th><th>Verdict</th><th>Score</th><th>Activities</th><th>Lanes</th><th>Evidence</th><th>Artefacts</th></tr></thead>
        <tbody>
          {''.join(rows) if rows else '<tr><td colspan="7">No processes extracted.</td></tr>'}
        </tbody>
      </table>
    </div>
  </section>

  <section class="block">
    <h2 class="sec">Business outcomes</h2>
    <div class="tablewrap">
      <table class="tbl">
        <thead><tr><th>Process</th><th>Lever</th><th>Metric</th><th>Baseline → target</th><th>Horizon</th><th>Basis</th></tr></thead>
        <tbody>
          {''.join(value_rows) if value_rows else '<tr><td colspan="6">No value captured.</td></tr>'}
        </tbody>
      </table>
    </div>
  </section>

  <section class="block">
    <h2 class="sec">Run manifest</h2>
    <div class="tablewrap">
      <table class="tbl compact">
        <tbody>
          <tr><td style="width:26%"><b>Repository</b></td><td><code>{html.escape(run.get("repo", ""))}</code></td></tr>
          <tr><td><b>Configuration</b></td><td><code>{html.escape(str(run.get("config") or "defaults, auto-discovery"))}</code></td></tr>
          <tr><td><b>Provider</b></td><td>{html.escape(run.get("provider", ""))} · {html.escape(run.get("model", ""))}</td></tr>
          <tr><td><b>Files scanned</b></td><td>{run.get("filesScanned", 0)}</td></tr>
          <tr><td><b>Signals found</b></td><td>{run.get("signalsFound", 0)}</td></tr>
          <tr><td><b>Activities extracted</b></td><td>{acts}</td></tr>
          <tr><td><b>Generated</b></td><td>{html.escape(run.get("generatedAt", ""))}</td></tr>
        </tbody>
      </table>
    </div>
  </section>

  <div class="foot">
    Generated by the Process Atlas extraction agent. CPM JSON is the canonical artefact;
    the BPMN files and this page are projections of it. No JavaScript, no network calls at read time.
  </div>
</div>
</body>
</html>
"""


def copy_theme(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    source = PROMPTS_DIR.parent / "assets" / "styles.css"
    if source.is_file():
        shutil.copyfile(source, destination / "styles.css")
    else:  # pragma: no cover - spec set always ships the theme
        (destination / "styles.css").write_text(
            ":root{--blue-900:#0b2545;--blue-800:#14335c;--blue-700:#1d4e89;"
            "--blue-100:#dbe7f5;--blue-50:#f2f7fc;--line:#dde5ee;--muted:#5b6b80;"
            "--muted-2:#8794a5;--teal-50:#eaf7f4;--teal-700:#0f766e;"
            "--amber-50:#fdf6e7;--amber-700:#92620a;--rose-50:#fdeef0;--rose-700:#a12c3a;}"
            "body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;color:#1f2a37;"
            "background:#f7f9fc;margin:0}.wrap{max-width:1140px;margin:0 auto;padding:0 40px}"
            ".tbl{width:100%;border-collapse:collapse;font-size:13px}.tbl td,.tbl th{"
            "padding:9px 12px;border-bottom:1px solid var(--line);text-align:left}"
            ".pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11px;"
            "border:1px solid var(--line);background:#fff}"
            ".pill--ok{background:var(--teal-50);color:var(--teal-700)}"
            ".pill--warn{background:var(--amber-50);color:var(--amber-700)}"
            ".pill--risk{background:var(--rose-50);color:var(--rose-700)}"
            ".pill--core{background:var(--blue-800);color:#fff}"
            ".pill--unit{background:var(--blue-50);color:var(--blue-700)}"
            ".pill--later,.pill--e2e{background:#eef2f6;color:var(--muted)}"
        )


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
