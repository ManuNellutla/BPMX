"""
Configuration for the extraction agent.

A run is configured by a single JSON file, normally `process-atlas.json` at the
root of the repository being analysed. Everything has a default so that

    python3 -m agent run ./some-repo

does something useful with no configuration at all.

    {
      "projectId": "prj_orders",
      "projectName": "Orders Platform",
      "domain": "Sales",
      "include": ["src/**/*.ts", "app/**/*.py"],
      "exclude": ["**/*.test.ts"],
      "actors": [
        { "match": "src/billing/**", "lane": "Billing Operations", "type": "internal" }
      ],
      "processes": [
        {
          "id": "invoice_to_cash",
          "name": "Invoice to Cash",
          "domain": "Finance",
          "trigger": "Invoice becomes due",
          "outcome": "Cash collected and receivable closed",
          "include": ["src/billing/**", "src/collections/**"],
          "sequence": ["Issue invoice", "Apply payment", "Run dunning"],
          "ignore": ["Retrieve invoice"],
          "endLane": "Collections",
          "decisions": [
            { "after": "Apply payment", "name": "Remittance matched?",
              "branches": [
                { "condition": "remittance matched", "target": "Run dunning" },
                { "condition": "no remittance", "target": "$end" }
              ] }
          ],
          "value": {
            "lever": ["cycleTime"],
            "outcome": { "statement": "Reduce DSO from 48 to 38 days", "kpi": "DSO",
                         "baseline": 48, "target": 38, "unit": "days",
                         "horizon": "2 quarters", "basis": "assumption" }
          }
        }
      ]
    }

`processes` is optional. Without it the agent clusters discovered signals by
module directory and emits one process per cluster.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAME = "process-atlas.json"

GENERIC_DIRS = {
    "src", "app", "lib", "libs", "packages", "services", "server", "backend",
    "api", "apis", "core", "internal", "pkg", "source", "sources",
}
GENERIC_LEAF = {
    "routes", "route", "router", "routers", "handlers", "handler", "controllers",
    "controller", "services", "service", "jobs", "job", "tasks", "task", "workers",
    "worker", "http", "rest", "endpoints", "endpoint", "usecases", "use_cases",
}

DEFAULT_INCLUDE = ["**/*.py", "**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx",
                   "**/*.go", "**/*.java", "**/*.kt", "**/*.cs", "**/*.rb"]
DEFAULT_EXCLUDE = ["**/*.test.*", "**/*.spec.*", "**/__tests__/**", "**/test_*.py",
                   "**/*_test.py", "**/migrations/**", "**/generated/**"]


@dataclass
class ActorRule:
    match: str
    lane: str
    type: str = "internal"


@dataclass
class Target:
    """One process boundary that will be extracted."""
    id: str
    name: str
    domain: str
    trigger: str = ""
    outcome: str = ""
    summary: str = ""
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    sequence: list[str] = field(default_factory=list)
    ignore: list[str] = field(default_factory=list)
    end_lane: str = ""
    decisions: list[dict] = field(default_factory=list)
    value: dict | None = None
    declared: bool = False          # True when configured by hand
    cluster: str = ""
    hint: str = ""


@dataclass
class Settings:
    project_id: str
    project_name: str
    domain: str
    include: list[str]
    exclude: list[str]
    actors: list[ActorRule]
    targets: list[Target]
    provider: str = "auto"
    model: str = ""
    max_files: int = 400
    max_file_bytes: int = 200_000
    source: Path | None = None


def slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower())
    return re.sub(r"_+", "_", text).strip("_") or "process"


def title(text: str) -> str:
    text = slugify(text).replace("_", " ")
    return text.title()


def cluster_of(rel: str) -> str:
    """Derive a process-ish cluster key from a file path.

    src/billing/routes.ts        -> billing
    app/collections/jobs.py      -> collections
    packages/orders/http/api.ts  -> orders
    handlers/invoice.py          -> handlers  (nothing better available)
    """
    parts = [p for p in rel.split("/")[:-1] if p]
    parts = [p for p in parts if p not in GENERIC_DIRS]
    for candidate in reversed(parts):
        if candidate not in GENERIC_LEAF:
            return candidate
    return parts[-1] if parts else "general"


def _as_list(value, default=None):
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return list(default or [])


def _target(raw: dict, defaults: Settings | dict) -> Target:
    get = raw.get
    name = get("name") or title(get("id") or "process")
    return Target(
        id=get("id") or slugify(name),
        name=name,
        domain=get("domain") or (defaults.domain if isinstance(defaults, Settings) else defaults.get("domain", "Business")),
        trigger=get("trigger") or "",
        outcome=get("outcome") or "",
        summary=get("summary") or "",
        include=_as_list(get("include")),
        exclude=_as_list(get("exclude")),
        sequence=_as_list(get("sequence")),
        ignore=_as_list(get("ignore")),
        end_lane=get("endLane") or "",
        decisions=[d for d in get("decisions", []) if isinstance(d, dict)],
        value=get("value") if isinstance(get("value"), dict) else None,
        declared=True,
        hint=get("hint") or "",
    )


def load_config(repo: Path, config_path: Path | None = None) -> Settings:
    repo = repo.resolve()
    path = config_path
    if path is None:
        candidate = repo / CONFIG_NAME
        path = candidate if candidate.is_file() else None

    raw = {}
    if path is not None:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"config not found: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("config must be a JSON object")

    settings = Settings(
        project_id=raw.get("projectId") or f"prj_{slugify(repo.name)}",
        project_name=raw.get("projectName") or title(repo.name),
        domain=raw.get("domain") or "Business",
        include=_as_list(raw.get("include"), DEFAULT_INCLUDE),
        exclude=_as_list(raw.get("exclude"), DEFAULT_EXCLUDE),
        actors=[
            ActorRule(match=a.get("match", "**"), lane=a.get("lane") or title(a.get("match", "actor")),
                      type=a.get("type", "internal"))
            for a in raw.get("actors", []) if isinstance(a, dict)
        ],
        targets=[_target(t, raw) for t in raw.get("processes", []) if isinstance(t, dict)],
        provider=raw.get("provider") or "auto",
        model=raw.get("model") or "",
        max_files=int(raw.get("maxFiles") or 400),
        max_file_bytes=int(raw.get("maxFileBytes") or 200_000),
        source=path,
    )
    settings.include = [p for p in settings.include if p]
    settings.exclude = [p for p in settings.exclude if p]
    return settings


def discover_targets(settings: Settings, files, signals) -> list[Target]:
    """Return configured targets, or cluster signals into one target per module."""
    if settings.targets:
        return settings.targets

    by_cluster: dict[str, list] = {}
    for signal in signals:
        by_cluster.setdefault(cluster_of(signal.file), []).append(signal)

    targets: list[Target] = []
    for cluster in sorted(by_cluster):
        cluster_signals = by_cluster[cluster]
        labels = [s.label for s in cluster_signals]
        targets.append(Target(
            id=slugify(cluster),
            name=f"{title(cluster)} Operations",
            domain=settings.domain,
            trigger=f"{labels[0]} requested",
            outcome=f"{labels[-1]} completed",
            summary=f"Process discovered in the '{cluster}' module from {len(cluster_signals)} code signals.",
            sequence=labels,
            declared=False,
            cluster=cluster,
            hint=cluster,
        ))

    if not targets:
        # Nothing process-shaped was found. Still emit an explicit abstention so
        # the run answers the question instead of returning an empty report.
        targets.append(Target(
            id=slugify(settings.project_id),
            name=settings.project_name,
            domain=settings.domain,
            summary="No process-bearing code constructs were found in the selected files.",
            declared=False,
            cluster="",
            hint="whole repository",
        ))
    return targets
