# Validator — process identity and contract compliance

Version 1.0.0 · `validate_extraction.py` · fixtures in `fixtures/`

The validator answers two different questions and never conflates them:

| Question | Gates | Failure means |
| --- | --- | --- |
| **Is this a business process?** | identity | The payload is an arbitrary extraction: fields, headings, roles, a single task |
| **Is the model acceptable?** | compliance | It is a process, but lanes, terminals, evidence or scope are incomplete |

A field list with perfect JSON is still `not_a_process`. A genuine process with no actor is `partial_process`, not a
rejection.

---

## 1. Verdicts and exit codes

| Verdict | Score band | Meaning | Exit |
| --- | --- | --- | --- |
| `business_process` | 76–100 | Identity and compliance pass | 0 |
| `partial_process` | 50–74 | A process, contract incomplete | 1 |
| `not_a_process` | 0–45 | Identity failed; not a process | 2 |
| — | — | Unreadable input | 3 |

Score is `100 - Σ(rule weights)`, then clamped to the verdict band so the number cannot contradict the verdict.
Advisory findings (P16–P18) lower the score without changing the verdict.

A correct abstention — `isBusinessProcess: false` with `process: null` — is reported as `not_a_process` with score
`100`, `abstained: true` and `agreement: true`. Abstaining is a pass for the model even though the document contains
no process.

---

## 2. Identity gates

Any failure here forces `not_a_process`, regardless of compliance.

| Code | Test | Detection |
| --- | --- | --- |
| P01 | Named process | `name` non-empty, not a file name, not a heading word (Introduction, Appendix, …) |
| P02 | ≥ 2 activities | Count of BPMN task types |
| P03 | Ordering exists | At least one sequence flow touches an activity |
| P04 | Path exists | A start event can reach an end event |
| P05 | No stranded work | Every activity is reachable from a start and can reach an end |
| P14 | Nodes are not fields | ≤ 40% of nodes are data types or field-like names |

**P14 detection.** A node counts as an entity when its type is a data type, its name is `snake_case`/`CONSTANT_CASE`,
or its last token is a field suffix (`id`, `amount`, `status`, `date`, …).

---

## 3. Compliance gates

| Code | Test | Weight | Detection |
| --- | --- | --- | --- |
| S03 | Unique node IDs | 20 (structure) | Duplicate or missing `id` |
| S04 | Edges resolve | 20 (structure) | Endpoint missing, or self-loop without a rework condition |
| S05 | Lanes resolve | 10 | `laneId` not present in `lanes[]` |
| S06 | No duplicate edges | 3 | Repeated `from`/`to` pair |
| S07 | Known node types | 3 | Type outside the BPMN vocabulary |
| S09 | Exactly one start | 12 | `startEvent` count ≠ 1 |
| S10 | At least one end | 12 | No `endEvent` |
| P06 | Actor coverage | 15 | < 100% of activities have a resolving lane |
| P07 | Activities are actions | 15 | < 70% of activity labels start with a recognised verb |
| P08 | Trigger and outcome | 12 | `scope.trigger` or `scope.outcome` empty |
| P09 | Outcome is a result | 5 | Outcome matches field-name heuristics |
| P10 | Evidence coverage | 12 | < 95% of activities have a valid locator + quote |
| P11 | Locators well formed | 6 | Bad page/bbox, code line range, timecode or image region |
| P12 | No candidate leakage | 2 | Candidate ID also appears in `nodes[]` |
| P13 | One process per graph | 15 | More than one disconnected activity group |
| P15 | Label hygiene | 3 | Duplicate names, > 80 chars, trailing punctuation |
| P16 | Quote quality (advisory) | 2 per finding (max 4) | Quote repeats the element label instead of showing behaviour |
| P17 | Value block (advisory) | 3 | No lever, outcome statement or `noQuantifiedOutcome` marker |
| P18 | Confidence routing (advisory) | 2 per finding (max 4) | Elements below 0.70 confidence left in `nodes[]` |

**P07 detection.** First token is checked against a verb lexicon (`approve`, `issue`, `validate`, `match`, …), with
`-ing`/`-ed`/`-s` stemming and `re-` handling. Names such as *Invoice Number*, *Background*, *CFO* and *Dunning* fail. Naming is
a compliance concern, not an identity one: a graph with noun-labelled activities and real control flow is still a
process, so it scores as `partial_process` rather than being rejected. The lexicon is deliberately conservative; a
novel verb may need adding to `VERBS`.

Advisory findings deduct from the score but never change the verdict and never enter a gate list. They are the
difference between a passing model that is merely valid and one that is well-evidenced.

`S03` and `S04` are **structural**: a graph with duplicate IDs or dangling edges is unreadable, so it is rejected as
`not_a_process` rather than scored as a compliant model.

`--allow-unevidenced` downgrades a zero-evidence P10 failure to a 3-point warning for draft extraction. Quotes are
never verified against the source by this tool; the report states `verbatim: unverified offline`.

---

## 4. Pattern classifier

The pattern explains *what the payload actually is*. It is diagnostic, not the verdict.

| Pattern | Detected when |
| --- | --- |
| `document_summary` | ≥ 50% of node names are section headings |
| `org_chart` | ≥ 50% of node names contain role/department words |
| `entity_list` | < 2 activities with ≥ 40% entity-like nodes, or > 40% entity nodes overall |
| `single_activity` | Exactly one activity |
| `multi_process` | More than one disconnected activity group |
| `unstructured` | No nodes, or activity labels that are neither actions nor fields |
| `process` | None of the above |

Order matters: heading and role signals are checked before activity count, so a section outline mislabelled as
`task` still reports `document_summary`.

---

## 5. Report shape

```json
{
  "validatorVersion": "1.0.0",
  "file": "fixtures/entity-list.json",
  "verdict": "not_a_process",
  "score": 0,
  "pattern": "entity_list",
  "scope": "single",
  "processCount": 1,
  "declared": true,
  "declaredPattern": "process",
  "agreement": false,
  "abstained": false,
  "summary": "Not a business process. Nodes are data entities or field names...",
  "gates": {
    "identity": { "pass": false, "failed": ["P02", "P03", "P04", "P14"] },
    "compliance": { "pass": false, "failed": ["S09", "S10", "P08"] }
  },
  "metrics": {
    "nodes": 5, "activities": 0, "gateways": 0, "events": 0, "dataNodes": 5,
    "edges": 0, "lanes": 0, "startEvents": 0, "endEvents": 0, "components": 0,
    "activityOnPathRatio": 0.0, "laneCoverage": 0.0, "evidenceCoverage": 0.0,
    "actionLabelRatio": 0.0, "entityNodeRatio": 1.0, "weakQuotes": 0
  },
  "findings": [
    { "code": "P02", "category": "identity", "severity": "error",
      "message": "0 activity node(s); a process needs at least 2",
      "elementId": null, "weight": 30 }
  ],
  "remediation": ["Extract at least two activities; if none exist, return notBusinessProcess."],
  "verbatim": "unverified offline",
  "processes": []
}
```

The `findings` array above is abridged. `agreement` compares the payload's own
`classification.isBusinessProcess` with the computed verdict. A model that
correctly abstains scores `agreement: true`; a model that claims a process for a field list scores `false`.

---

## 6. Usage

```bash
# human report
python3 validate_extraction.py extraction.json

# machine report
python3 validate_extraction.py extraction.json --json > report.json

# draft mode: evidence gate relaxed
python3 validate_extraction.py extraction.json --allow-unevidenced

# batch gate in CI
find out -name '*.json' -print0 | xargs -0 -n1 python3 validate_extraction.py || exit 1

# rule regression
python3 validate_extraction.py --self-test
```

Accepts three payload shapes:

1. envelope with `process` — the prompt's normal output;
2. envelope with `processes[]` — every process is validated, the weakest verdict wins;
3. a bare CPM document with `nodes`/`edges` — the persisted model format.

---

## 7. Integration

| Point | Action |
| --- | --- |
| After extraction, before persistence | `abstained` → store as a negative label; other `not_a_process` → discard and log; `partial_process` → review queue; `business_process` → draft model |
| Before BPMN export | Any compliance failure blocks export; identity failure is impossible at this stage |
| CI on the golden corpus | A regression in verdict for a known-process fixture fails the build |
| Review UI | Show pattern and failed gate codes next to the candidate; remediation strings are the reviewer's checklist |

This is layer 2 of three. Layer 1 is JSON Schema (shape). Layer 3 is BPMN semantic validation before export
(gateway arity, dangling flow, lane assignment). The validator deliberately overlaps layer 3 only where a broken
graph makes process identity unreadable.

---

## 8. Fixtures

`--self-test` asserts these outcomes.

| Fixture | Expected verdict | Pattern | Proves |
| --- | --- | --- | --- |
| `valid-invoice-to-cash.json` | `business_process` | `process` | A complete two-actor process passes every gate |
| `entity-list.json` | `not_a_process` | `entity_list` | Fields are rejected even when the model claims a process |
| `doc-summary.json` | `not_a_process` | `document_summary` | Section headings are not activities |
| `org-chart.json` | `not_a_process` | `org_chart` | Reporting lines are not control flow |
| `single-task.json` | `not_a_process` | `single_activity` | One task is not a process |
| `multi-process.json` | `partial_process` | `multi_process` | Two triggers in one graph require a split |
| `process-no-actors.json` | `partial_process` | `process` | A real sequence without lanes is incomplete, not fake |
| `noun-labels.json` | `partial_process` | `process` | Noun-labelled activities are a naming defect, not a fake process |
| `abstain-entity-list.json` | `not_a_process` | `entity_list` | Correct abstention: score 100, agreement true, no fabricated model |

---

## 9. Limitations

- Verb detection is English-only and lexicon-based. Add domain verbs to `VERBS` rather than weakening the 70% rule.
- The validator cannot confirm a quote exists in the source; pair it with a locator-resolver step that opens the page,
  line range or timecode.
- Gateways are not required. A linear process is valid; branching is evidenced, not expected.
- Parallel versus exclusive semantics are not distinguished here; that is BPMN semantic validation.
- A process split across several `processes[]` entries is validated element-wise; the weakest entry sets the document
  verdict. Cross-process hand-offs are out of scope for v1.
