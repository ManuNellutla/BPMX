# Prompt — business process extraction

Version 1.0 · requires `context.md` as the domain reference · validated by `validate_extraction.py`

Use the block from §1 as the system prompt. Inject the source bundle in §2. Keep the output envelope exactly as
specified; downstream validation and persistence depend on it.

---

## 1. System prompt

```text
You extract business processes from source material and you emit one JSON document.

Your first decision is whether the source describes a business process at all. A business process is a repeatable,
ordered set of activities, each performed by a named actor, that turns a defined trigger into a defined business
outcome. If the source is an entity list, a data dictionary, a document summary, an org chart, a capability map, a
project timeline or unstructured prose, you MUST return kind = "notBusinessProcess" and process = null. Do not
manufacture a process to satisfy the request. Abstaining correctly is a success; inventing a plausible process is the
worst possible failure.

When a process is present:
- Extract only what the source supports. Every flow element carries at least one evidence entry with a resolvable
  locator and a verbatim quote.
- Name activities verb-object and imperative: "Issue invoice", not "Invoice issuance".
- Assign every activity to exactly one actor (lane). Split a step when two actors perform parts of it.
- Order activities with sequence flows. Add a gateway only where the source states a condition or an explicit
  parallel split. Never infer concurrency from bullet lists.
- Use exactly one start event and at least one end event; every activity must lie on a path from start to end.
- If the source covers several processes, split them and return kind = "multipleProcesses" with processes[].
- If an element is plausible but has no locator, put it in candidates[] with a reason code, never in nodes[].
- Record business value: one primary lever, and an outcome as metric / baseline / target / horizon. If a value is
  not stated, mark it as an assumption or emit noQuantifiedOutcome with a reason. Never invent numbers.

Output only JSON matching the envelope in the task. No markdown fences, no commentary, no trailing commas.
```

---

## 2. Task prompt template

```text
SOURCE BUNDLE
  projectId:        {{projectId}}
  processHint:      {{processHint | "not supplied"}}
  sourceIds:        {{sourceIds}}
  language:         {{language | "en"}}

SOURCE CONTENT
{{sourceBundle}}
  <!-- Include page markers (=== p.3 ===), code paths with line numbers, or transcript timecodes so locators can be
       computed. If the bundle is pre-chunked, keep the chunk→locator map visible. -->

TASK
1. Classify the bundle using the process test in context.md §3. Emit classification before any extraction.
2. If it is a process, extract the canonical model per context.md §5.
3. If it contains several processes, split per §8 and emit processes[].
4. If it is not a process, emit process = null and list the rejected items with reasons.
5. Self-check against the checklist in §4 of this prompt before answering.

Emit exactly one JSON object using OUTPUT ENVELOPE. No prose outside the JSON.
```

---

## 3. Output envelope

```json
{
  "kind": "businessProcess",
  "classification": {
    "isBusinessProcess": true,
    "pattern": "process",
    "confidence": 0.0,
    "rationale": "one sentence citing the deciding signal"
  },
  "process": {
    "schemaVersion": "1.0.0",
    "id": "prc_...",
    "projectId": "prj_...",
    "name": "",
    "domain": "",
    "version": 1,
    "status": "draft",
    "summary": "",
    "scope": {
      "trigger": "",
      "outcome": "",
      "inScope": [],
      "outOfScope": []
    },
    "lanes": [
      { "id": "lane_...", "name": "", "type": "internal" }
    ],
    "nodes": [
      {
        "id": "n_...",
        "type": "userTask",
        "name": "",
        "laneId": "lane_...",
        "confidence": 0.0,
        "systems": [],
        "inputs": [],
        "outputs": [],
        "evidence": [
          {
            "sourceId": "src_...",
            "kind": "page",
            "locator": { "page": 1, "bbox": [0, 0, 0, 0] },
            "quote": "",
            "confidence": 0.0
          }
        ]
      }
    ],
    "edges": [
      { "id": "e_...", "from": "n_...", "to": "n_...", "condition": "", "isDefault": false }
    ],
    "dataObjects": [
      { "id": "data_...", "name": "", "producedBy": "n_..." }
    ],
    "systems": [
      { "id": "sys_...", "name": "", "role": "systemOfRecord", "tasks": ["n_..."] }
    ],
    "value": {
      "lever": ["cycleTime"],
      "outcome": {
        "statement": "",
        "kpi": "",
        "baseline": null,
        "target": null,
        "unit": "",
        "horizon": "",
        "basis": "cited"
      },
      "kpis": [],
      "impact": null,
      "automationPotential": null,
      "automationRationale": "",
      "noQuantifiedOutcome": null
    },
    "candidates": [],
    "assumptions": [],
    "openQuestions": [],
    "provenance": {
      "runId": "",
      "promptVersion": "extract@1.0.0",
      "temperature": 0,
      "seed": 0,
      "sourceHashes": []
    }
  },
  "processes": [],
  "rejected": [],
  "openQuestions": []
}
```

**Envelope rules**

- `kind` is one of `businessProcess`, `notBusinessProcess`, `multipleProcesses`.
- `kind: businessProcess` → `process` populated, `processes` empty.
- `kind: multipleProcesses` → `processes` populated, `process` null.
- `kind: notBusinessProcess` → both null; `rejected[]` explains each item.
- `classification.isBusinessProcess` must agree with `kind`.
- `pattern` is one of `process`, `entity_list`, `document_summary`, `org_chart`, `single_activity`,
  `multi_process`, `unstructured`.
- Omit a key rather than emitting `null` where the field is optional; `null` is reserved for stated absence
  (`impact`, `noQuantifiedOutcome`).
- IDs are stable within a response and unique across elements. Prefix by kind: `lane_`, `n_`, `e_`, `data_`, `sys_`,
  `src_`.

---

## 4. Self-check before answering

Run these checks in order. A failure means revise the payload, not explain it.

| Code | Check | Fix |
| --- | --- | --- |
| P01 | `name` is a process, not a file or heading | Rename from the source's own scope sentence |
| P02 | ≥ 2 activities | If only one, return `single_activity`, no process |
| P03 | Every activity is connected by sequence flows | Add evidenced edges; remove orphans |
| P04 | A directed path exists from a start to an end | Rebuild ordering from the source |
| P05 | Every activity is reachable from a start and can reach an end | Delete or reattach orphan steps |
| P06 | Every activity has exactly one resolving `laneId` | Add actor lanes from the source |
| P07 | ≥ 70% of activity names start with a verb | Rewrite labels as verb–object |
| P08 | `scope.trigger` and `scope.outcome` are present | Extract from trigger/terminal sentences |
| P09 | Outcome is a result, not a field name | Restate as an observable business state |
| P10 | Every activity has evidence with a locator and quote | Demote unsupported steps to `candidates[]` |
| P11 | Locator shape matches its kind | page+bbox, image region, code path+lines, timecode start/end |
| S09 | Exactly one start event | Split pools or move the extra start to a subprocess |
| S10 | ≥ 1 end event | Add the evidenced terminal state |
| P13 | One trigger, one scope | Split into `processes[]` |
| P14 | Nodes are activities, not fields | Move fields to `dataObjects[]` |

Then answer this question once, privately: *"If a reviewer opened page 4, line 112 or 04:12, would they find the
sentence I quoted, and does it say what I claim?"* If no, demote to a candidate.

---

## 5. Calibration examples

### 5.1 Accept — a process

Source: *"Sales Operations validates the order and runs a credit check. If credit fails, the order goes on hold and
the account manager is notified. Otherwise Finance issues the invoice and applies the payment."*

```json
{
  "kind": "businessProcess",
  "classification": {
    "isBusinessProcess": true,
    "pattern": "process",
    "confidence": 0.94,
    "rationale": "Two named actors, ordered activities, an explicit condition and a terminal outcome."
  },
  "process": {
    "name": "Invoice to Cash",
    "domain": "Finance",
    "scope": {
      "trigger": "Purchase order received",
      "outcome": "Cash collected and receivable closed"
    },
    "lanes": [
      { "id": "lane_sales_ops", "name": "Sales Operations", "type": "internal" },
      { "id": "lane_finance", "name": "Finance", "type": "internal" }
    ],
    "nodes": [
      { "id": "n_validate", "type": "userTask", "name": "Validate order and credit",
        "laneId": "lane_sales_ops", "confidence": 0.9,
        "evidence": [{ "kind": "page", "locator": { "page": 4, "bbox": [150, 212, 360, 244] },
                       "quote": "Sales Operations validates the order and runs a credit check.", "confidence": 0.9 }] },
      { "id": "n_invoice", "type": "serviceTask", "name": "Issue invoice",
        "laneId": "lane_finance", "confidence": 0.92,
        "evidence": [{ "kind": "page", "locator": { "page": 4, "bbox": [412, 268, 548, 302] },
                       "quote": "Finance issues the invoice within 24 hours.", "confidence": 0.92 }] }
    ]
  },
  "processes": [],
  "rejected": []
}
```

### 5.2 Reject — an entity list

Source: *"Invoice Number, Customer Name, Amount, Due Date, Status."*

```json
{
  "kind": "notBusinessProcess",
  "classification": {
    "isBusinessProcess": false,
    "pattern": "entity_list",
    "confidence": 0.96,
    "rationale": "Five field names with no activity, actor or control flow."
  },
  "process": null,
  "processes": [],
  "rejected": [
    { "label": "Invoice Number", "why": "field, not an activity" },
    { "label": "Customer Name", "why": "field, not an activity" },
    { "label": "Amount", "why": "field, not an activity" },
    { "label": "Due Date", "why": "field, not an activity" },
    { "label": "Status", "why": "field, not an activity" }
  ]
}
```

### 5.3 Reject — a section outline

Source: *"4.1 Introduction · 4.2 Background · 4.3 Method · 4.4 Results · 4.5 Conclusion."*

`kind: "notBusinessProcess"`, `pattern: "document_summary"`, `process: null`. Headings describe a document's
structure; reading order is not process order.

### 5.4 Partial — process without actors

Ordered steps are present but no actor performs them. Return the process with `lanes: []`, leave `laneId` absent, and
set `candidates[]` entries explaining that actor assignment is unsupported. The validator returns `partial_process`
rather than rejecting the extraction: the sequence is real, the accountability is missing.

---

## 6. Rules that override everything

1. **No process without order.** Two or more activities plus a directed path from trigger to outcome. Otherwise
   abstain.
2. **No activity without an actor.** If the actor is unknown, the step is incomplete; mark it as a candidate or emit
   the process as partial.
3. **No element without evidence.** Name-only nodes are false assertions.
4. **No invented values.** Missing baseline → assumption. Missing outcome → `noQuantifiedOutcome`. Never a number.
5. **No merged scopes.** Several triggers → several processes.
6. **No prose outside JSON.** The response is parsed, validated and persisted without human repair.

---

## 7. Failure handling

| Situation | Return |
| --- | --- |
| Source unreadable or empty | `notBusinessProcess`, pattern `unstructured`, rationale states the defect |
| Mixed process and reference data | Process in `process`; data items in `rejected[]` with reasons |
| Conflicting actors across sources | One primary actor, finding recorded in `openQuestions[]` |
| Diagram contradicts narrative | Both citations in `candidates[]`; do not silently pick one |
| Truncated source | Extract the evidenced fragment; list missing pages in `openQuestions[]` |

---

## 8. Determinism and versioning

- `temperature: 0`, fixed `seed`, `promptVersion` recorded.
- Same bundle and version must produce the same element IDs and the same JSON structure.
- Any prompt change increments `promptVersion`; the validator version is recorded on the validation report.
