"""Extract and run fenced shell examples from Markdown."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess


@dataclass(frozen=True)
class CommandBlock:
    file: Path
    line: int
    script: str


FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})([^\n]*)\n(.*?)^[ \t]*\1[ \t]*$", re.MULTILINE | re.DOTALL)


def extract(text: str, file: Path, languages: list[str] | None = None, skip_marker: str = "sitecheck: skip") -> list[CommandBlock]:
    accepted = set(languages or ["bash", "sh", "shell"])
    blocks = []
    for match in FENCE.finditer(text):
        language = match.group(2).strip().split(maxsplit=1)[0].lower() if match.group(2).strip() else ""
        body = match.group(3)
        if language in accepted and not any(line.lstrip().startswith("#") and skip_marker in line
                                            for line in body.splitlines()):
            blocks.append(CommandBlock(file, text.count("\n", 0, match.start()) + 1, body))
    return blocks


def collect(paths: list[Path], languages: list[str] | None = None, skip_marker: str = "sitecheck: skip") -> list[CommandBlock]:
    files = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.rglob("*.md")))
        elif path.is_file():
            files.append(path)
    return [block for file in dict.fromkeys(files)
            for block in extract(file.read_text(encoding="utf-8"), file, languages, skip_marker)]


def run(blocks: list[CommandBlock], cwd: Path, timeout: float = 30, env: dict[str, str] | None = None,
        tail_lines: int = 12) -> list[dict]:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    result = []
    environment = {**os.environ, **(env or {})}
    for block in blocks:
        try:
            completed = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", block.script],
                                       cwd=cwd, env=environment, text=True, capture_output=True, timeout=timeout)
            output = (completed.stdout + completed.stderr).splitlines()
            result.append({"file": str(block.file), "line": block.line, "returncode": completed.returncode,
                           "output_tail": "\n".join(output[-tail_lines:])})
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or b"") + (exc.stderr or b"")
            if isinstance(output, bytes):
                output = output.decode(errors="replace")
            result.append({"file": str(block.file), "line": block.line, "returncode": None,
                           "output_tail": "\n".join(output.splitlines()[-tail_lines:]), "timeout": True})
    return result
