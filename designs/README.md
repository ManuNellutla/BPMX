# Process Atlas — design set

Static HTML specification set for process extraction, documentation and BPMN visualization.
Open `index.html` in a browser; no build step, no JavaScript.

## Documents

| File | Contents |
| --- | --- |
| `index.html` | Traceability hub: chain diagram, document index, coverage summary, artefact contract |
| `features.html` | 12 features across extraction, documentation and visualization; contracts, pipeline, value model, notation policy |
| `requirements.html` | 49 requirements (`REQ-EXT` 15, `REQ-VAL` 6, `REQ-DOC` 10, `REQ-VIZ` 12, `REQ-MOD` 6), 16 use cases, 10 quality gates |
| `test-cases.html` | 60 test cases in suites A–J (48 P0 / 12 P1), traceability matrix |
| `wireframes/index.html` | Gallery and rendering rules for the four UI samples |
| `samples/cpm-invoice-to-cash.json` | Canonical Process Model example — lanes, nodes, edges, evidence, value, findings, provenance |
| `prompts/context.md` | Extraction context: definitions, process test, negative archetypes, evidence and value rules |
| `prompts/prompt-extract-process.md` | Extraction prompt, output envelope, self-check and calibration examples |
| `prompts/validator.md` | Process-identity and contract rules, weights, patterns, report shape |
| `prompts/validate_extraction.py` | Deterministic validator for business process vs arbitrary extraction |
| `../agent/README.md` | Runnable extraction agent: source repository → CPM JSON → BPMN, Markdown, HTML report |
| `assets/styles.css` | Shared theme |
| `wireframes/wf.css` | App-shell styles for the wireframes |

## Wireframes

1. `wireframes/01-bpmn-canvas.html` — three-lane BPMN pool, evidence badges, confidence bars, finding outlines, inspector.
2. `wireframes/02-evidence-provenance.html` — provenance chain, captured fields, citation list, PDF / video / code locators.
3. `wireframes/03-portfolio-value.html` — KPI strip, value-vs-effort matrix, priority formula, assumption flags.
4. `wireframes/04-review-compare.html` — review queue, version diff overlay, per-change decision panel.

## Conventions

- Model authority: the CPM JSON is the single source; BPMN, brief, step table and canvas are projections.
- Evidence before assertion: every flow element carries a locator (`page+bbox`, `image region`, `file:line`, `timecode range`) and a verbatim quote.
- IDs are stable across documents (`REQ-*`, `UC-01`…`UC-16`, `TC-001`…`TC-060`) and used as anchor targets.
- Wireframes are static HTML/CSS/SVG; controls are non-interactive by design.
