# Process Atlas extraction agent

Point it at a code repository. It finds process-shaped constructs, builds a Canonical Process Model per process,
runs the specification validator, verifies every quote against the source file, and writes CPM JSON, BPMN 2.0,
Markdown and an HTML report.

```
repository → file selection → code signals → process boundaries → extraction
           → validation gate → evidence audit → CPM JSON → BPMN · Markdown · dashboard
```

The agent is the runtime counterpart to the specification set in `../designs/`. It does not duplicate the rules:
`designs/prompts/validate_extraction.py` is imported as the acceptance gate, and `designs/prompts/context.md` plus
`prompt-extract-process.md` are the system prompt for model-backed runs.

---

## 1. What is needed

| Requirement | Detail |
| --- | --- |
| Python | 3.10 or newer. Stdlib only, no `pip install`. |
| Source repository | Any repo containing `.ts`, `.js`, `.py`, `.go`, `.java`, `.kt`, `.cs`, `.rb` files. |
| Configuration | Optional. Without it the agent auto-discovers process boundaries by module. |
| Model access | Optional. Without an API key the offline heuristic provider runs. Set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` for LLM extraction. |
| Specification set | Keep `BPM/designs/prompts/` in place; the agent reads the validator and prompt from there. |

Use the LLM provider when the source is prose, PDFs, diagrams or when you want actor/business-value inference. Use
the heuristic provider for a deterministic baseline, CI, and offline demos.

---

## 2. Quickstart

```bash
cd BPM/agent

# scans the bundled example, writes to atlas-out/
python3 atlas.py run examples/orders-service

# open the report
xdg-open atlas-out/prj_orders_platform/index.html
```

Expected result: two processes, both `business_process`, 5 and 3 activities, every quote verified.

```bash
# inspect boundaries without extracting
python3 atlas.py discover examples/orders-service

# prove discovery, extraction, evidence, BPMN and determinism
python3 atlas.py selftest

# validate any CPM or envelope
python3 atlas.py validate atlas-out/prj_orders_platform/processes/invoice_to_cash/cpm.json
```

---

## 3. Running against your own repository

```bash
python3 atlas.py run /path/to/repo --out ./atlas-out
```

With no configuration the agent:

1. walks the repository, skipping `node_modules`, `dist`, `.venv`, tests and generated code;
2. scans each file for route handlers, Python decorators, queue consumers, cron jobs and exported functions;
3. clusters signals by module directory (`src/billing/**` → `Billing Operations`);
4. emits one process per cluster, ordered by discovery, with a generated trigger and outcome;
5. validates, audits quotes, and writes the artefacts.

Auto-discovery is a starting point, not a scope decision. Add a config to name the processes, state the trigger and
outcome, order the steps and declare decisions.

### 3.1 Configuration

Place `process-atlas.json` at the repository root, or pass `--config`.

```json
{
  "projectId": "prj_orders_platform",
  "projectName": "Orders Platform",
  "domain": "Sales",
  "include": ["src/**/*.ts"],
  "exclude": ["**/*.test.ts"],
  "actors": [
    { "match": "src/billing/**", "lane": "Billing Operations", "type": "internal" },
    { "match": "src/collections/**", "lane": "Collections", "type": "internal" }
  ],
  "processes": [
    {
      "id": "invoice_to_cash",
      "name": "Invoice to Cash",
      "domain": "Finance",
      "trigger": "Invoice issued and payment due",
      "outcome": "Cash collected and receivable closed",
      "include": ["src/billing/**/*.ts", "src/collections/**/*.ts"],
      "sequence": ["Issue invoice", "Apply payment", "Run dunning"],
      "ignore": ["Retrieve invoice"],
      "endLane": "Collections",
      "decisions": [
        {
          "after": "Run dunning",
          "name": "Payment recovered?",
          "branches": [
            { "condition": "payment recovered", "target": "$end" },
            { "condition": "payment not recovered", "target": "Place credit hold" }
          ]
        }
      ],
      "value": {
        "lever": ["cycleTime"],
        "outcome": {
          "statement": "Reduce DSO from 48 to 38 days",
          "kpi": "DSO", "baseline": 48, "target": 38,
          "unit": "days", "horizon": "2 quarters", "basis": "assumption"
        }
      }
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `projectId`, `projectName`, `domain` | Identity of the run and default domain for targets |
| `include`, `exclude` | Glob patterns; `**` matches across directories |
| `actors[]` | `match` (glob) → `lane` name and `type` (`internal` or `external`) |
| `processes[]` | Explicit process boundaries. Omit for auto-discovery |
| `processes[].include` | Files belonging to that process; defaults to the whole repo |
| `processes[].sequence` | Activity labels in business order. Unlisted activities are appended |
| `processes[].ignore` | Activity labels to drop (query endpoints, health checks, technical helpers) |
| `processes[].endLane` | Lane for the end event when the closing outcome belongs to another actor |
| `processes[].decisions[]` | `after` activity, gateway `name`, `branches[]` with `condition` and `target`; `$end` targets the end event |
| `processes[].value` | Lever plus metric, baseline, target, unit, horizon and basis |
| `provider`, `model` | Defaults for this repository; overridden by the CLI |
| `maxFiles`, `maxFileBytes` | Scan budget (default 400 files, 200 KB per file) |

Labels in `sequence`, `ignore` and decision targets are matched case-insensitively against the labels the scanner
derives from code (`issueInvoice` → `Issue invoice`).

---

## 4. Commands

```bash
python3 atlas.py run SOURCE [options]
python3 atlas.py discover SOURCE
python3 atlas.py validate FILE [--json] [--verbose]
python3 atlas.py selftest
```

| `run` option | Effect |
| --- | --- |
| `--config PATH` | Use a specific config file |
| `--out DIR` | Output directory (default `./atlas-out`) |
| `--provider auto\|heuristic\|anthropic\|openai` | `auto` uses a key if present, else heuristic |
| `--model NAME` | Override the provider default |
| `--allow-unevidenced` | Downgrade the evidence gate for draft runs |
| `--dry-run` | List files, signals and boundaries; no extraction |
| `--quiet` | Only the final summary |

Exit codes: `0` every process accepted, `1` partial or mixed, `2` nothing accepted, `3` bad input or provider error.

### 4.1 Model-backed extraction

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 atlas.py run /path/to/repo --provider anthropic --out ./atlas-out
```

The model receives the extraction context, the system prompt, and a focused bundle: files that contain signals,
with ±30-line windows around each signal, line numbers, and a process hint. It must return the JSON envelope from
`prompt-extract-process.md`. The response is parsed, validated and audited exactly like heuristic output. A model
failure never produces a model file: the target is reported as an error and the run continues.

`auto` prints which provider it selected. `heuristic` never makes a network call.

---

## 5. Outputs

```
atlas-out/
  <projectId>/
    index.html                  dashboard: verdicts, scores, quote verification
    run.json                    manifest: files, signals, providers, findings, errors
    portfolio.json              value and scope per process
    assets/styles.css
    processes/
      invoice_to_cash/
        cpm.json                canonical model (the artefact)
        process.bpmn            BPMN 2.0 projection with DI layout and atlas: evidence
        process.md              scope, actors, steps, decisions, value, evidence, validation
        extraction.json         the envelope returned by the provider
        validation.json         gate report, metrics, findings and the evidence audit
```

`cpm.json` is written before any projection. A process that fails the identity gate is never exported to BPMN;
it still gets `extraction.json`, `validation.json` and a dashboard row explaining why.

BPMN is deterministic: lanes are horizontal bands, columns are longest-path depth, IDs are preserved, and evidence
travels in `<atlas:evidence>` extension elements. Re-running on unchanged sources produces byte-identical CPM,
BPMN and Markdown (only `generatedAt` timestamps differ).

---

## 6. How acceptance works

Three gates run in order:

| Layer | Check | Failure |
| --- | --- | --- |
| Shape | JSON parses, envelope has `process`, `processes` or a bare CPM | target error, run continues |
| Identity + compliance | `designs/prompts/validate_extraction.py` | `partial_process` or `not_a_process` |
| Evidence | Each code locator is opened and the quote compared to the line | recorded in `validation.json`; quote counts on the dashboard |

Identity asks whether the payload is a process at all: ≥ 2 activities, ordering, a start-to-end path, an actor per
activity, a process name. Compliance asks whether the process is complete: exactly one start, an end, lanes, trigger,
outcome, evidence, one scope. A real sequence with a naming or lane defect is partial, not rejected.

The evidence audit is the one check the standalone validator cannot do. It resolves `path`, `startLine` and
`endLine` inside the repository, normalises whitespace, and reports `matched/checked`. A quote that is not present
at the stated location appears in the dashboard and in `validation.json` → `evidenceAudit.unresolved`.

---

## 7. Source support

| Language | Route/endpoint | Decorator | Queue | Cron | Exported function |
| --- | --- | --- | --- | --- | --- |
| TypeScript / JavaScript | `router.post`, `app.get`, … | — | `queue.process("x", fn)` | `cron.schedule("x", fn)` | `export function`, `const fn = () =>` |
| Python | `@router.post("/x")` | yes | `.consume("x", fn)` | `.schedule("x", fn)` | `def` |
| Go, Java, Kotlin, C#, Ruby, PHP, Rust | generic function declarations only | — | — | — | limited |

The scanner is heuristic: it recognises common construct shapes, not frameworks. Add a regex to
`sources.py` and a label rule to `camel_to_label`/`route_label` to support another convention. Both the signal
label and the verb vocabulary come from `designs/prompts/validate_extraction.py` (`is_action_label`), so a new label
must start with a known verb or be added to `VERBS` there.

---

## 8. Limitations

- **Code only.** PDFs, images, video and text are specified in the design set but not implemented by this agent.
  The LLM providers accept any bundle; the file walker currently selects source files.
- **Heuristic ordering is configured, not inferred.** Without `sequence`, activities follow declaration order. The
  heuristic does not read call graphs or handler bodies for control flow.
- **Decisions come from config.** The gateway in a heuristic run exists because a human declared it, not because the
  scanner inferred it. LLM runs may infer further decisions, which the validator then checks.
- **Actors are path rules.** `actors[]` maps directories to business roles. Without a rule, a lane is named after the
  module. True role inference is a model task.
- **No BPMN import.** The agent writes BPMN; importing an existing BPMN file into the CPM is specified but not built.
- **Quotes are line-level.** A locator is one line for code. Multi-line constructs are represented by their first
  line, which keeps the audit exact.
- **English only.** Verb detection and label generation assume English identifiers.

---

## 9. Specification traceability

| Implemented behaviour | Requirement | Note |
| --- | --- | --- |
| Repository intake and file walker | REQ-EXT-01 | Repositories only; PDF, image and video intake are not built |
| Per-file SHA-256 in provenance | REQ-EXT-02 | `provenance.sourceHashes` |
| Verb–object activity extraction | REQ-EXT-03 | Route, job, consumer and function labels |
| Actor lanes | REQ-EXT-04 | Path rules in `actors[]`, one lane per activity |
| Decisions and conditions | REQ-EXT-05 | Declared in `decisions[]`; heuristic does not infer them |
| Start and end events | REQ-EXT-06 | One start, evidenced outcome end |
| Code construct detection | REQ-EXT-10 | Handlers, decorators, consumers, schedulers, exported functions |
| Evidence binding | REQ-EXT-08 | `path` + `startLine`/`endLine` + verbatim quote |
| Abstention instead of invention | REQ-EXT-14 | `notBusinessProcess` when no ordered activities exist |
| Reproducible model | REQ-EXT-15 | Stable IDs, `promptVersion`, seed, source hashes |
| Identity and compliance gate | REQ-VAL-01…06 | Delegated to `validate_extraction.py` |
| BPMN 2.0 projection | REQ-VIZ-01…04 | Deterministic DI, IDs preserved, evidence in extension elements |

Not implemented from the specification set: PDF, image and video interpretation (REQ-EXT-09, REQ-EXT-11), cross-source
fusion (REQ-EXT-12), incremental extraction (REQ-EXT-13), BPMN import, and the interactive review surfaces described by
the wireframes.

---

## 10. Layout

```
BPM/agent/
  atlas.py            CLI entry point
  cli.py              argument parsing and commands
  pipeline.py         orchestration and output writing
  config.py           process-atlas.json, targets, auto-discovery
  sources.py          file walker and code-signal scanner
  build.py            offline heuristic CPM builder
  prompting.py        system prompt and focused source bundle
  providers.py        heuristic, Anthropic, OpenAI
  validation.py       validator bridge and evidence audit
  render.py           BPMN, Markdown, dashboard
  examples/
    orders-service/   runnable demo repository and config
```
