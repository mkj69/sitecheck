"""Command line interface for sitecheck."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import re
import sys
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
from urllib.parse import urlparse

from .browser import BrowserError, Chrome, DEFAULT_BROWSER_TIMEOUT
from .checks import overflow_findings, static_findings
from .discovery import discover, fetch, parse_page, serve
from .docs import collect, run
from .reports import contact_sheet, write_reports


DEFAULT_CONFIG = '''# Sitecheck configuration
source = "examples/demo-site"
output = "sitecheck-out"
viewports = [1440, 390]
themes = ["light", "dark"]
limit = 100
include = []
exclude = []
sitemap = true
chrome = ""
browser_timeout = 40
max_height = 40000
# Choose media, attribute, or query.
theme_mode = "media"
theme_attribute = "data-theme"
theme_query = "theme"
docs = ["examples/demo-site/docs"]
doc_languages = ["bash", "sh", "shell"]
doc_skip_marker = "sitecheck: skip"
doc_cwd = "."
doc_timeout = 30
# doc_env = { SITE_MODE = "test" }

# Add entries such as { kind = "broken_link", page = "*/draft.html" }.
allow = []
'''


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="sitecheck", description="Check static sites and documentation")
    root.add_argument("--config", type=Path, default=Path("sitecheck.toml"))
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="write a starter sitecheck.toml")
    for name in ("pages", "shots", "smoke", "all"):
        part = sub.add_parser(name)
        part.add_argument("source", nargs="?", help="URL or directory")
        part.add_argument("--output", type=Path)
        part.add_argument("--include", action="append")
        part.add_argument("--exclude", action="append")
        part.add_argument("--limit", type=int)
        part.add_argument("--no-sitemap", action="store_true")
        part.add_argument("--chrome")
        part.add_argument("--timeout", type=float, help="browser command timeout in seconds")
        part.add_argument("--max-height", type=int, help="maximum screenshot height in pixels")
        part.add_argument("--viewports", help="comma separated widths")
        part.add_argument("--themes", help="comma separated themes")
        part.add_argument("--theme-mode", choices=("media", "attribute", "query"))
        part.add_argument("--theme-attribute")
        part.add_argument("--theme-query")
    docs = sub.add_parser("doc-commands", help="run fenced shell examples")
    docs.add_argument("paths", nargs="*", type=Path)
    docs.add_argument("--output", type=Path)
    docs.add_argument("--cwd", type=Path)
    docs.add_argument("--timeout", type=float)
    docs.add_argument("--language", action="append")
    docs.add_argument("--skip-marker")
    docs.add_argument("--env", action="append", default=[], metavar="NAME=VALUE")
    return root


def read_config(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as stream:
        return tomllib.load(stream)


def value(args, config: dict, name: str, default):
    item = getattr(args, name, None)
    return item if item is not None else config.get(name, default)


def command_findings(commands: list[dict]) -> list[dict]:
    return [{"kind": "doc_command", "page": f"{item['file']}:{item['line']}",
             "message": item["output_tail"] or ("timed out" if item.get("timeout") else f"exit {item['returncode']}")}
            for item in commands if item["returncode"] != 0]


def run_docs(args, config: dict, output: Path) -> tuple[list[dict], list[dict]]:
    paths = getattr(args, "paths", None) or [Path(path) for path in config.get("docs", ["docs"])]
    languages = getattr(args, "language", None) or config.get("doc_languages", ["bash", "sh", "shell"])
    marker = value(args, config, "skip_marker", config.get("doc_skip_marker", "sitecheck: skip"))
    cwd = value(args, config, "cwd", Path(config.get("doc_cwd", ".")))
    timeout = value(args, config, "timeout", config.get("doc_timeout", 30))
    environment = dict(config.get("doc_env", {}))
    for assignment in getattr(args, "env", []):
        if "=" not in assignment or not assignment.split("=", 1)[0]:
            raise ValueError(f"Invalid environment assignment: {assignment}")
        key, val = assignment.split("=", 1)
        environment[key] = val
    blocks = collect(paths, languages, marker)
    results = run(blocks, Path(cwd), timeout, environment)
    return results, command_findings(results)


def screenshot_name(url: str, theme: str, width: int) -> str:
    path = urlparse(url).path.strip("/") or "index"
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", path).strip("_")[:50] or "index"
    digest = hashlib.sha1(url.encode()).hexdigest()[:8]
    return f"{slug}_{digest}_{theme}_{width}.png"


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            if args.config.exists():
                raise ValueError(f"Configuration already exists: {args.config}")
            args.config.write_text(DEFAULT_CONFIG, encoding="utf-8")
            print(args.config)
            return 0
        config = read_config(args.config)
        output = Path(value(args, config, "output", "sitecheck-out"))
        if args.command == "doc-commands":
            commands, findings = run_docs(args, config, output)
            errors = write_reports(output, findings, commands=commands)
            print(f"{len(commands)} commands, {errors} errors: {output / 'report.html'}")
            return int(errors > 0)
        source = args.source or config.get("source")
        if not source:
            raise ValueError("Provide a URL or directory, or set source in sitecheck.toml")
        widths = value(args, config, "viewports", [1440, 390])
        widths = [int(part) for part in widths.split(",")] if isinstance(widths, str) else widths
        if not widths or any(int(width) < 1 for width in widths):
            raise ValueError("Viewports must be positive widths")
        themes = value(args, config, "themes", ["light", "dark"])
        themes = themes.split(",") if isinstance(themes, str) else themes
        if not themes or any(theme not in ("light", "dark") for theme in themes):
            raise ValueError("Themes must be light or dark")
        theme_mode = value(args, config, "theme_mode", "media")
        browser_timeout = args.timeout if args.timeout is not None else config.get("browser_timeout", DEFAULT_BROWSER_TIMEOUT)
        max_height = value(args, config, "max_height", 40000)
        if max_height < 1:
            raise ValueError("Maximum screenshot height must be positive")
        include = value(args, config, "include", [])
        exclude = value(args, config, "exclude", [])
        limit = value(args, config, "limit", 100)
        sitemap = not args.no_sitemap and config.get("sitemap", True)
        with ExitStack() as stack:
            if urlparse(source).scheme in ("http", "https"):
                start = source
            else:
                directory = Path(source)
                if not directory.is_dir():
                    raise ValueError(f"Site directory does not exist: {source}")
                start = stack.enter_context(serve(directory))
            pages = discover(start, include=include, exclude=exclude, limit=limit, sitemap=sitemap)
            if args.command == "pages":
                for page in pages:
                    print(page)
                return 0 if pages else 1
            findings: list[dict] = []
            shots: list[dict] = []
            cache = {}
            if args.command in ("smoke", "all"):
                for page in pages:
                    status, body = fetch(page)
                    if status >= 400:
                        findings.append({"kind": "page_error", "page": page, "message": f"HTTP {status}"})
                        continue
                    for finding in static_findings(page, parse_page(body), cache):
                        findings.append({"page": page, **finding})
            if not pages:
                findings.append({"kind": "no_pages", "page": start, "message": "No pages discovered"})
            if pages:
                try:
                    with Chrome(value(args, config, "chrome", None) or None, timeout=browser_timeout) as browser:
                        for page in pages:
                            for theme in (themes if args.command in ("shots", "all") else ["light"]):
                                for width in widths:
                                    try:
                                        browser.open(page, int(width), theme, theme_mode,
                                                     value(args, config, "theme_attribute", "data-theme"),
                                                     value(args, config, "theme_query", "theme"))
                                        if args.command in ("smoke", "all") and theme == "light":
                                            findings += [{"page": page, "viewport": width, **item}
                                                         for item in overflow_findings(browser.layout_boxes(), int(width))]
                                            findings += [{"page": page, "viewport": width, **item}
                                                         for item in browser.event_findings()]
                                        if args.command in ("shots", "all"):
                                            path = output / "shots" / screenshot_name(page, theme, int(width))
                                            capture = browser.screenshot(path, int(width), max_height=max_height)
                                            shot = {"page": page, "theme": theme, "width": width,
                                                    "path": path.relative_to(output).as_posix()}
                                            if capture["truncated"]:
                                                shot["note"] = (f"Screenshot truncated at {capture['height']}px; "
                                                                f"full page height is {capture['full_height']}px")
                                            shots.append(shot)
                                    except BrowserError as exc:
                                        findings.append({"kind": "browser_error", "page": page,
                                                         "viewport": width, "message": str(exc)})
                except BrowserError as exc:
                    findings.append({"kind": "browser_error", "page": start, "message": str(exc)})
            if shots:
                for theme in themes:
                    paths = [output / shot["path"] for shot in shots if shot["theme"] == theme]
                    if paths:
                        contact_sheet(paths, output / f"contact_{theme}.png")
            commands = []
            if args.command == "all":
                commands, doc_findings = run_docs(args, config, output)
                findings += doc_findings
            errors = write_reports(output, findings, shots, config.get("allow", []), commands)
            print(f"{len(pages)} pages, {len(shots)} screenshots, {errors} errors: {output / 'report.html'}")
            return int(errors > 0)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"sitecheck: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
