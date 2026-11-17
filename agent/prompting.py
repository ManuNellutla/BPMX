"""
Prompt assembly.

The specification set already contains the extraction contract. Rather than
copying it, the agent reads `designs/prompts/context.md` and the system prompt
block from `designs/prompts/prompt-extract-process.md`, so prompt and validator
stay versioned together.
"""

from __future__ import annotations

import re
from pathlib import Path

import sources
from config import Target
from validation import PROMPTS_DIR

MAX_BUNDLE_CHARS = 90_000
WINDOW_PAD = 30


def _first_fence(markdown: str, language: str = "text") -> str:
    match = re.search(r"```" + language + r"\n(.*?)```", markdown, re.S)
    return match.group(1).strip() if match else ""


def system_prompt() -> str:
    context = PROMPTS_DIR / "context.md"
    prompt = PROMPTS_DIR / "prompt-extract-process.md"
    parts = []
    if context.is_file():
        parts.append(context.read_text(encoding="utf-8"))
    if prompt.is_file():
        block = _first_fence(prompt.read_text(encoding="utf-8"))
        if block:
            parts.append("EXTRACTION INSTRUCTION\n\n" + block)
    if not parts:
        parts.append(
            "Extract business processes from source code. Return one JSON envelope. "
            "A process needs at least two activities, one lane per actor, sequence flows "
            "from one start event to at least one end event, a trigger, an outcome, and a "
            "locator plus verbatim quote behind every activity."
        )
    return "\n\n---\n\n".join(parts)


def file_windows(lines: list[str], signal_lines: list[int], pad: int = WINDOW_PAD) -> list[tuple[int, int]]:
    windows = []
    for line in sorted(set(signal_lines)):
        start = max(1, line - pad)
        end = min(len(lines), line + pad)
        if windows and start <= windows[-1][1] + 1:
            windows[-1] = (windows[-1][0], max(windows[-1][1], end))
        else:
            windows.append((start, end))
    return windows


def render_file(rel: str, text: str, signal_lines: list[int]) -> str:
    lines = text.splitlines()
    windows = file_windows(lines, signal_lines) or [(1, min(len(lines), 80))]
    out = [f"=== {rel} (sourceId: {source_id(rel)}) ==="]
    for start, end in windows:
        out.append(f"--- {rel} lines {start}-{end} ---")
        for number in range(start, end + 1):
            out.append(f"{number:>5} | {lines[number - 1]}")
    return "\n".join(out)


def source_id(rel: str) -> str:
    import hashlib
    return "src_" + hashlib.sha1(rel.encode()).hexdigest()[:8]


def build_bundle(target: Target, files: list[sources.SourceFile],
                 signals: list[sources.Signal]) -> str:
    """Render the task prompt and a focused source bundle.

    Files with signals are always included, ordered by signal count. Other
    selected files are included while the character budget allows, so the model
    can see context (types, constants) without receiving the repository.
    """
    by_file: dict[str, list[int]] = {}
    for signal in signals:
        by_file.setdefault(signal.file, []).append(signal.line)
    ordered = sorted(files, key=lambda f: (-len(by_file.get(f.rel, [])), f.rel))

    header = [
        "SOURCE BUNDLE",
        f"  projectId:        {target.id}",
        f"  processHint:      {target.name} — {target.hint or target.summary or 'not supplied'}",
        f"  triggerHint:      {target.trigger or 'not supplied'}",
        f"  outcomeHint:      {target.outcome or 'not supplied'}",
        f"  sourceIds:        {', '.join(source_id(f.rel) for f in ordered[:12])}",
        "  language:         en",
        "",
        "SOURCE CONTENT",
        "  Line numbers are authoritative. Emit code locators as "
        "{ \"path\": \"<path>\", \"startLine\": n, \"endLine\": n } and quote the line verbatim.",
        "",
    ]

    body, used = [], 0
    for source in ordered:
        rendered = render_file(source.rel, source.text, by_file.get(source.rel, []))
        if body and used + len(rendered) > MAX_BUNDLE_CHARS:
            continue
        body.append(rendered)
        used += len(rendered)

    task = [
        "",
        "TASK",
        f"1. Decide whether the selected sources contain the business process '{target.name}'.",
        "2. If yes, extract it as one canonical process using the OUTPUT ENVELOPE.",
        "3. Use kind = \"businessProcess\" with exactly one process object. Do not return multipleProcesses.",
        "4. If the sources do not support a process, return kind = \"notBusinessProcess\" and why.",
        "5. Every activity needs a code locator and a verbatim quote from the lines above.",
        "6. Emit JSON only. No markdown fences, no commentary.",
    ]
    return "\n".join(header + body + task)


def user_message(target: Target, files, signals) -> str:
    return ("Extract the business process described by this source bundle.\n\n"
            + build_bundle(target, files, signals))


def load_prompt_version() -> str:
    prompt = PROMPTS_DIR / "prompt-extract-process.md"
    if not prompt.is_file():
        return "extract@unknown"
    match = re.search(r"Version\s+([0-9][^\s·]*)", prompt.read_text(encoding="utf-8"))
    return f"extract@{match.group(1) if match else 'unknown'}"
