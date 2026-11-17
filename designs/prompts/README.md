# Extraction prompts and process validator

Instruction and verification layer for turning source material into a Canonical Process Model. This folder is the
runtime counterpart to the HTML specification set in `../`.

| File | Purpose |
| --- | --- |
| `context.md` | Domain definitions, the process test, negative archetypes, evidence and value rules |
| `prompt-extract-process.md` | System prompt, task template, output envelope, self-check, calibration examples |
| `validator.md` | Rule reference: gates, weights, patterns, report shape, integration points |
| `validate_extraction.py` | Deterministic validator; stdlib only, no network |
| `fixtures/` | Nine labelled payloads used by `--self-test` |

## Quickstart

```bash
python3 validate_extraction.py --self-test
python3 validate_extraction.py fixtures/entity-list.json
python3 validate_extraction.py ../samples/cpm-invoice-to-cash.json --json
```

Exit codes: `0` business process, `1` partial, `2` not a process, `3` unreadable input.

## The contract in one paragraph

A payload is a business process only when it contains at least two activities, each assigned to a named actor, joined
by sequence flows on a path from one start event to at least one end event, with a stated trigger and outcome and a
locator plus verbatim quote behind every activity. Anything else is an arbitrary extraction: a field inventory, a
document outline, an org chart, a single task or unstructured prose. The validator encodes that sentence as gates;
`context.md` explains why each gate exists.

## Fixtures

| Fixture | Verdict | Pattern |
| --- | --- | --- |
| `valid-invoice-to-cash.json` | business_process | process |
| `entity-list.json` | not_a_process | entity_list |
| `doc-summary.json` | not_a_process | document_summary |
| `org-chart.json` | not_a_process | org_chart |
| `single-task.json` | not_a_process | single_activity |
| `multi-process.json` | partial_process | multi_process |
| `process-no-actors.json` | partial_process | process |
| `noun-labels.json` | partial_process | process |
| `abstain-entity-list.json` | not_a_process | entity_list |

Run `python3 validate_extraction.py --self-test` to assert all nine.

## Versioning

`context.md` and `prompt-extract-process.md` are versioned together (`1.0`). The validator has its own semantic
version (`1.0.0`) recorded on every report. A prompt change that alters element naming or gating increments the prompt
version; a rule or weight change increments the validator version.
