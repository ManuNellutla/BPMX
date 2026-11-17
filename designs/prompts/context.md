# Business process extraction — context

Version 1.0 · pairs with `prompt-extract-process.md` and `validate_extraction.py`

---

## 1. Purpose

This document supplies the domain context an extraction model needs in order to decide **whether a source contains a
business process at all**, and if so, what to emit. It is the reference for the prompt and the rule baseline for the
validator.

Three artefacts, one contract:

| Artefact | Role |
| --- | --- |
| `context.md` | Definitions, decision tests, archetypes, vocabulary |
| `prompt-extract-process.md` | Instruction and output envelope given to the model |
| `validate_extraction.py` | Deterministic check that the output is a process, not an arbitrary extraction |

The validator does not judge writing quality. It judges **process identity** (is this an ordered, actor-bound,
outcome-producing set of activities?) and **contract compliance** (evidence, lanes, terminals, value).

---

## 2. Definitions

These definitions are operational: each one is testable against a JSON payload.

**Business process** — a repeatable, ordered set of activities, performed by one or more actors, that transforms a
defined trigger into a defined business outcome. Repeatable means the sequence can be instantiated more than once
with different inputs; it is not a one-off project schedule.

**Activity** — one verb–object unit of work with a single accountable actor: *Issue invoice*, *Validate credit
limit*, *Match remittance*. An activity is not a document, a field, a role, a system, a section heading or a stage.

**Actor** — the role, department, team or external party that performs an activity. Actors become lanes. A node has
exactly one lane.

**Trigger** — the event or state that starts an instance: *purchase order received*, *employee submits claim*,
*scheduled run at 02:00*.

**Outcome** — the business result the process exists to produce, stated so it can be observed: *cash collected*,
*invoice paid within terms*, *claim reimbursed*. An outcome is not a data field and not a deliverable name.

**Control flow** — the ordering of activities plus the conditions under which the path branches, waits or ends. A set
of activities without control flow is a list, not a process.

**Evidence** — a locator into the source plus a verbatim quote. Locator kinds: PDF page + bounding box, image region,
code `file:line` range, video timecode range. Confidence is a number in `[0,1]`.

**Business value** — the lever (cost, revenue, risk, compliance, customer experience, cycle time) plus a quantified
outcome when the source supports one, or an explicit marker when it does not.

**Canonical Process Model (CPM)** — the persisted JSON document. BPMN, briefs, tables and canvases are projections
of it; the model is never reconstructed from them.

---

## 3. The process test

A candidate is a **business process** only if checks 1–3 hold. Checks 4 and 6–8 decide whether the extracted model is
complete enough to accept; their failure yields a partial model, not a rejection. Check 5 is a modelling rule
enforced by the prompt, and check 9 separates a recurring process from a one-off plan.

| # | Check | Pass criterion | Validator rule |
| --- | --- | --- | --- |
| 1 | Identity | A named process, not a document or section title | P01 |
| 2 | Plurality | ≥ 2 activities and ≥ 1 named actor | P02, P06 |
| 3 | Ordering | Every activity lies on a directed path from a start to an end | P03, P04, P05 |
| 4 | Actor binding | Every activity has exactly one lane; lanes resolve | P06, S05 |
| 5 | Decisions | Branching only where the source states a condition; no invented concurrency | (prompt rule) |
| 6 | Termination | ≥ 1 start event and ≥ 1 end event, both reachable | S09, S10 |
| 7 | Outcome | A stated business result that is not a field or artefact name | P08, P09 |
| 8 | Evidence | Every activity carries a locator and a verbatim quote | P10, P11 |
| 9 | Repeatability | Described as recurring operation, not a one-time schedule | soft |

Failure of check 1, 2 or 3 is an **identity failure**: the payload is not a process. Entity-node drift (P14) is
also identity. Failure of checks 4, 6, 7 or 8 is a **compliance failure**: the payload may be a process but is not
acceptable as a model. Check 5 is enforced by prompt rule and has no gate.

---

## 4. What is *not* a business process

The most common false positives. Each has a validator pattern label.

### 4.1 Entity or field inventory → `entity_list`

Content: names of documents, fields, columns or records; no ordering; no actor.

```
Invoice Number, Customer Name, Amount, Due Date, Status
```

This is a data dictionary. It describes *what is stored*, not *what is done*. Extraction should return
`isBusinessProcess: false` with these items in `rejected[]`.

### 4.2 Document summary → `document_summary`

Content: section headings or topics.

```
Introduction · Background · Method · Results · Conclusion
```

This is the structure of a document. Headings are not activities; reading order is not control flow.

### 4.3 Table or spreadsheet dump → `entity_list` (tabular subtype)

Content: row-per-record data with column headers. Signals: uniform node types, labels equal to headers, keys such as
`fields`, `columns`, `rows`, `dtype`.

### 4.4 Organisation chart → `org_chart`

Content: roles and reporting lines.

```
CFO → Controller → Accounts Payable Team
```

Reporting relationships are not process sequence. An org chart may *supply* actors for a process; it is not one.

### 4.5 Capability map or value stream → `unstructured` (too coarse)

Content: 5–12 high-level stages (*Plan, Source, Make, Deliver*). Stages are not activities: no single accountable
actor, no terminal state, no evidence per step. Treat as context for scoping, not as an extracted process.

### 4.6 Single activity → `single_activity`

Content: one task with a start and an end. Not a process: nothing is ordered, no hand-off exists. Validator requires
≥ 2 activities.

### 4.7 Project plan or timeline → `unstructured` (schedule subtype)

Content: milestones with dates. A plan is instantiated once and its ordering is calendar-driven, not
condition-driven. Signal: dates as node names, `milestone` types, no repeatable trigger.

### 4.8 System architecture → `unstructured` (topology subtype)

Content: services, queues, databases and their connections. Call graphs are topology, not business sequence. Code
extraction must map handlers to *business* activities with a business actor, not mirror the module tree.

### 4.9 Prose narrative → `unstructured`

Content: a story with no separable steps. If activities cannot be isolated with evidence, return no process and list
the reason.

---

## 5. What to extract

### 5.1 Process header

| Field | Required | Rule |
| --- | --- | --- |
| `name` | yes | Verb–object or noun-phrase naming the process domain, not a file name |
| `domain` | yes | Business domain (Finance, Procurement, HR, …) |
| `scope.trigger` | yes | Event or state that starts an instance |
| `scope.outcome` | yes | Observable business result |
| `scope.inScope` / `outOfScope` | recommended | Boundary terms as extracted, not invented |
| `summary` | optional | ≤ 2 sentences, no new facts |

### 5.2 Lanes

One per actor. `type` is `internal` or `external`. Lane names come from the source; do not normalise a department
into a system name.

### 5.3 Nodes

Allowed BPMN types:

| Type | Use when |
| --- | --- |
| `startEvent`, `endEvent` | Trigger and terminal states, typed only when evidenced |
| `userTask` | A person performs the step |
| `serviceTask` | A system performs the step; cite the code construct |
| `task` | Actor known, human/system unclear |
| `manualTask` | Performed without system support |
| `businessRuleTask` | Rule engine or decision table |
| `sendTask`, `receiveTask` | Explicit message exchange |
| `subProcess` | Named sub-flow with its own boundary |
| `exclusiveGateway` | One path chosen by a stated condition |
| `parallelGateway` | Concurrency stated explicitly |
| `inclusiveGateway` | One or more paths, stated explicitly |

Every node: `id`, `type`, `name`, `laneId`, `confidence`, `evidence[]`. Activities additionally carry `systems[]`,
`inputs[]`, `outputs[]` when the source states them.

**Naming rule.** Verb–object, imperative, sentence case, ≤ 6 words: *Issue invoice*, not *Invoice issuance*,
*Invoicing*, or *INVOICE_CREATE*. Keep the source term in the quote; the normalised label is the model field.

**One activity, one actor.** If two actors perform parts of a step, split it into two nodes with a hand-off edge.

### 5.4 Edges

`{ id, from, to, condition? }`. Conditions are verbatim from the source. A default flow is marked
`isDefault: true`. Do not infer a parallel branch from bullet-list formatting; use it only when the source says
*simultaneously*, *in parallel* or *at the same time*.

### 5.5 Data and systems

`dataObjects[]` links named documents/records to a producer or consumer; `systems[]` lists named systems with the
tasks they support. These are supporting entities — they never become flow nodes.

---

## 6. Evidence rules

1. Quote is verbatim, ≤ 240 characters, and contains the words that justify the element's name or type.
2. A quote equal to the node label is weak: it shows the name but not the behaviour. Prefer a sentence with a verb.
3. Locator must resolve: page + bbox in PDF points; `path` (or `file`) + `startLine`/`endLine` for code; `start`/`end` seconds
   for video; `region` bbox for images.
4. Confidence bands: `≥ 0.85` explicit statement; `0.70–0.85` implied by adjacent text or code; `< 0.70` ambiguous —
   put the element in `candidates[]`, not `nodes[]`.
5. Do not synthesise a quote. If no sentence supports the step, the step is a candidate.

---

## 7. Business value rules

Levers (exactly one primary): `cost`, `revenue`, `risk`, `compliance`, `customerExperience`, `cycleTime`.

An outcome statement has four parts: metric, baseline, target, horizon. If baseline is not stated, set
`basis: "assumption"` and do not invent a number. If the source states no outcome at all, emit
`noQuantifiedOutcome: { reason }` — never leave the value block empty silently.

Impact estimates require a method and named assumptions; they are recomputable, not asserted.

---

## 8. Multi-process sources

A single PDF or recording often documents several processes. Split when **any** of these holds:

- Two disjoint start→end flows exist with different triggers.
- The named scopes differ by object or domain (*invoice to cash* vs *vendor onboarding*).
- Hand-offs cross an organisational boundary that has its own trigger and terminal state.

Do not split a single process merely because it has branches, loops or multiple end states.

Return `kind: "multipleProcesses"` with a `processes[]` array. Merging two processes into one graph is a scope
error, not a simplification.

---

## 9. Abstention

Returning no process is a valid, expected result. Emit:

```json
{
  "kind": "notBusinessProcess",
  "classification": { "isBusinessProcess": false, "pattern": "entity_list", "confidence": 0.93,
    "rationale": "Field inventory with no activities or control flow." },
  "process": null,
  "rejected": [ { "label": "Invoice Number", "why": "field, not an activity" } ]
}
```

Abstaining correctly is scored as success; inventing a plausible process from a field list is the worst failure mode.

---

## 10. BPMN projection constraints

Extraction must stay exportable to BPMN 2.0 without repair:

- Exactly one start event per process; ≥ 1 end event.
- Every activity lies on a start→end path.
- A gateway has ≥ 2 outgoing flows or a default.
- Every node has a lane; every lane has ≥ 1 node.
- No dangling edges, no duplicate edges, no self-loops without an explicit rework condition.
- Element IDs are stable and unique; they survive export and re-import.

These constraints are checked before export and are mirrored in the validator.

---

## 11. Vocabulary

```text
node types      startEvent endEvent intermediateCatchEvent intermediateThrowEvent
                task userTask serviceTask manualTask businessRuleTask sendTask
                receiveTask scriptTask callActivity subProcess
                exclusiveGateway parallelGateway inclusiveGateway eventBasedGateway

lane types      internal external

evidence kinds  page image code timecode text

levers          cost revenue risk compliance customerExperience cycleTime

patterns        process entity_list document_summary org_chart single_activity
                multi_process unstructured
```

---

## 12. Failure modes

| Failure | Symptom | Consequence |
| --- | --- | --- |
| False process | Fields or headings rendered as tasks | Model looks complete but is fiction; validator pattern `entity_list` / `document_summary` |
| Flattened process | Ordered steps with no actors | No lane assignment; hand-offs invisible; `partial_process` |
| Invented concurrency | Parallel gateway from bullet lists | Wrong branch semantics; export is valid but wrong |
| Merged processes | Two triggers in one graph | Scope ambiguity; `multi_process` |
| Orphan steps | Nodes not on any path | Unreachable model fragments; identity failure |
| Uncited model | Nodes with names only | Not auditable; compliance failure |
| Single-step process | One task between events | `single_activity`; not a process |
| Narrative summary | Prose with no separable steps | `unstructured`; abstain |

---

## 13. Worked boundaries

**Process** (accept): *"Sales Ops validates the order, runs a credit check, and if credit fails places the order on
hold; Finance issues the invoice and applies payment."* — two actors, ordered activities, one condition, one outcome.

**Not a process** (reject): *"The invoice contains customer name, amount, due date and status."* — entity inventory.

**Not a process** (reject): *"Section 4.2 covers invoice issuance."* — document structure.

**Process, incomplete** (partial): the same sales paragraph with no actor named for any step. Ordered activities
exist, lanes do not.

**Two processes** (split): *"Vendor onboarding starts with a registration form; separately, invoice processing starts
when a PO is received."* — different triggers, different outcomes.

---

## 14. Determinism

Same source, same prompt version, same seed → same model. Extraction records `promptVersion`, `seed`, `temperature`
and source hashes. The validator is deterministic given a payload; it performs no network calls and reads no source
files, so `verbatim` is reported as *unverified offline* unless the source bundle is supplied.
