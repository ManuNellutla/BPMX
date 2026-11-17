"""
Source discovery and code-signal scanning.

The agent never sends a whole repository to a model. It selects files per process
boundary (from process-atlas.json), then scans them for constructs that usually
carry business behaviour:

    route handlers        router.post("/orders", submitOrder)
    python decorators     @router.post("/orders")
    exported functions    export async function issueInvoice(...)
    queue consumers       queue.process("invoice.issue", handler)
    scheduled jobs        cron.schedule("0 2 * * *", runDunning)

Each signal carries a file path, a line number and the verbatim line, which is
exactly the locator shape the validator expects.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

CODE_EXTENSIONS = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".py", ".java", ".kt", ".kts", ".go", ".cs", ".rb", ".php", ".rs", ".scala",
}

SKIP_DIRS = {
    "node_modules", ".git", ".hg", ".svn", "dist", "build", "out", "coverage",
    ".venv", "venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".next", ".nuxt", ".cache", "target", "vendor", "bin", "obj", ".idea",
    ".vscode", ".terraform", "site-packages",
}

# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #


@dataclass
class SourceFile:
    rel: str
    path: Path
    text: str

    @property
    def lines(self):
        return self.text.splitlines()


def glob_match(path: str, pattern: str) -> bool:
    """Minimal ** aware glob, independent of Python version quirks."""
    p = pattern.replace("\\", "/").strip()
    if not p:
        return False
    out, i = [], 0
    while i < len(p):
        if p.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif p.startswith("**", i):
            out.append(".*")
            i += 2
        elif p[i] == "*":
            out.append("[^/]*")
            i += 1
        elif p[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(p[i]))
            i += 1
    return re.fullmatch("".join(out), path) is not None


def walk(root: Path, include=None, exclude=None, max_file_bytes=200_000, max_files=400):
    """Yield SourceFile objects under root, filtered by include/exclude globs."""
    include = include or []
    exclude = exclude or []
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".git"))
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix.lower() not in CODE_EXTENSIONS:
                continue
            rel = path.relative_to(root).as_posix()
            if include and not any(glob_match(rel, p) for p in include):
                continue
            if exclude and any(glob_match(rel, p) for p in exclude):
                continue
            try:
                if path.stat().st_size > max_file_bytes:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            yield SourceFile(rel=rel, path=path, text=text)
            count += 1
            if count >= max_files:
                return


# --------------------------------------------------------------------------- #
# Signal patterns
# --------------------------------------------------------------------------- #

ROUTE_RE = re.compile(
    r"""\b(?:router|app|server|api|bp|blueprint)\s*\.\s*(get|post|put|patch|delete)\s*"""
    r"""\(\s*['"`]([^'"`]+)['"`]\s*,\s*([A-Za-z_$][\w$]*)?""",
    re.I,
)
DECORATOR_RE = re.compile(
    r"""^\s*@(?:router|app|bp|blueprint)\.(get|post|put|patch|delete)\(\s*['"]([^'"]+)['"]""",
    re.I,
)
DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(")
FUNC_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\("
)
CONST_FN_RE = re.compile(
    r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?"
    r"(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
)
QUEUE_RE = re.compile(
    r"""\.(?:process|consume|subscribe|consumeFrom)\s*\(\s*['"]([^'"]+)['"]\s*,\s*([A-Za-z_$][\w$]*)""",
    re.I,
)
CRON_RE = re.compile(
    r"""\.(?:schedule|addJob)\s*\(\s*['"]([^'"]+)['"]\s*,\s*([A-Za-z_$][\w$]*)""",
    re.I,
)

PRIORITY = {"cron": 4, "queue": 4, "route": 3, "decorator": 3, "function": 1}

VERB_MAP = {
    "post": "Submit", "put": "Update", "patch": "Update",
    "get": "Retrieve", "delete": "Cancel",
}


@dataclass
class Signal:
    label: str
    kind: str
    file: str
    line: int
    quote: str
    handler: str = ""

    @property
    def priority(self):
        return PRIORITY.get(self.kind, 0)


def camel_to_label(name: str) -> str:
    name = name.strip("_$")
    parts = [p for p in re.split(r"[_\-\s]+|(?<=[a-z0-9])(?=[A-Z])", name) if p]
    if parts and parts[0].lower() in {"handle", "on"} and len(parts) > 1:
        parts = parts[1:]
    if not parts:
        return ""
    label = " ".join(parts).lower()
    return label[0].upper() + label[1:]


def route_label(method: str, route: str) -> str:
    segments = [s for s in route.split("/") if s and not s.startswith(":") and not s.startswith("{")]
    resource = segments[-1] if segments else "request"
    action = method.lower()
    if resource in {"approve", "reject", "cancel", "close", "submit"} and len(segments) > 1:
        obj = segments[-2].rstrip("s")
        return f"{resource.capitalize()} {obj}"
    verb = VERB_MAP.get(action, "Handle")
    return f"{verb} {resource.rstrip('s')}"


def _quote(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip())[:240]


def scan_file(source: SourceFile, is_action) -> list[Signal]:
    """Return activity signals from one file. `is_action` filters verb labels."""
    lines = source.lines
    found: list[Signal] = []
    has_routes = False

    for idx, line in enumerate(lines, start=1):
        deco = DECORATOR_RE.search(line)
        if deco:
            method, route = deco.group(1), deco.group(2)
            handler = ""
            for probe in range(idx, min(idx + 6, len(lines))):
                match = DEF_RE.match(lines[probe])
                if match:
                    handler = match.group(1)
                    break
            label = camel_to_label(handler) if handler else route_label(method, route)
            if label and is_action(label) and len(label.split()) >= 2:
                found.append(Signal(label, "decorator", source.rel, idx, _quote(line), handler))
                has_routes = True
            continue

        route = ROUTE_RE.search(line)
        if route:
            method, route_path, handler = route.group(1), route.group(2), route.group(3) or ""
            label = camel_to_label(handler) if handler else route_label(method, route_path)
            if label and is_action(label) and len(label.split()) >= 2:
                found.append(Signal(label, "route", source.rel, idx, _quote(line), handler))
                has_routes = True
            continue

        cron = CRON_RE.search(line)
        if cron and ("cron" in source.text.lower() or "schedule" in line.lower()):
            handler = cron.group(2)
            label = camel_to_label(handler)
            if label and is_action(label) and len(label.split()) >= 2:
                found.append(Signal(label, "cron", source.rel, idx, _quote(line), handler))
            continue

        queue = QUEUE_RE.search(line)
        if queue:
            handler = queue.group(2)
            label = camel_to_label(handler)
            if label and is_action(label) and len(label.split()) >= 2:
                found.append(Signal(label, "queue", source.rel, idx, _quote(line), handler))
            continue

    if not has_routes:
        for idx, line in enumerate(lines, start=1):
            match = FUNC_RE.match(line) or CONST_FN_RE.match(line)
            if not match:
                continue
            label = camel_to_label(match.group(1))
            if label and is_action(label) and len(label.split()) >= 2:
                found.append(Signal(label, "function", source.rel, idx, _quote(line), match.group(1)))

    # De-duplicate by label, keeping the strongest construct (cron > route > function).
    best: dict[str, Signal] = {}
    for signal in found:
        key = signal.label.lower()
        if key not in best or signal.priority > best[key].priority:
            best[key] = signal
    return list(best.values())


def scan(files, is_action) -> list[Signal]:
    signals: list[Signal] = []
    for source in files:
        signals.extend(scan_file(source, is_action))
    return signals
