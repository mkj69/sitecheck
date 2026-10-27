"""Browser journeys and rendered text checks."""

from __future__ import annotations

from fnmatch import fnmatch
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

from .browser import BrowserError
from .discovery import crawl_key, page_url


SCRIPTS = {
    "cjk": r"[\u3400-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]",
    "han": r"[\u3400-\u9fff\uf900-\ufaff]",
    "kana": r"[\u3040-\u30ff]",
    "hangul": r"[\uac00-\ud7af]",
    "cyrillic": r"[\u0400-\u052f]",
    "arabic": r"[\u0600-\u06ff]",
    "greek": r"[\u0370-\u03ff]",
}


def language_findings(text: str, page: str, rules: list[dict]) -> list[dict]:
    findings = []
    for rule in rules:
        if not fnmatch(page, rule["page"]):
            continue
        for script in rule["scripts"]:
            pattern = re.compile(SCRIPTS[script])
            matches = []
            for line in text.splitlines():
                clean = line.strip()
                for allowed in rule["allow"]:
                    clean = clean.replace(allowed, "")
                if pattern.search(clean):
                    matches.append(clean[:160])
            if matches:
                findings.append({"kind": "wrong_script", "page": page,
                                 "message": f"{script} in rendered text ({len(matches)} lines): " + "; ".join(matches[:3])})
    return findings


def parse_rules(rules: list[dict]) -> list[dict]:
    if not isinstance(rules, list):
        raise ValueError("lang_rules must be a list")
    result = []
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("page", "*"), str):
            raise ValueError("Each language rule needs a page glob")
        scripts = rule.get("scripts")
        allow = rule.get("allow", [])
        if not isinstance(scripts, list) or not scripts or any(not isinstance(script, str) or script not in SCRIPTS for script in scripts):
            raise ValueError(f"Language scripts must be chosen from: {', '.join(SCRIPTS)}")
        if not isinstance(allow, list) or any(not isinstance(item, str) or not item for item in allow):
            raise ValueError("Language allow entries must be nonempty strings")
        result.append({"page": rule.get("page", "*"), "scripts": scripts, "allow": allow})
    return result


def inspect_widget(browser, root: str, fallback: str) -> list[dict]:
    result = browser.evaluate(f"""(() => {{
        const roots = {json.dumps(root)} ? [...document.querySelectorAll({json.dumps(root)})] : [];
        const visible = element => element.getClientRects().length && getComputedStyle(element).visibility !== 'hidden';
        const fallback = {json.dumps(fallback)} ? [...document.querySelectorAll({json.dumps(fallback)})].some(visible) : false;
        return {{missing: Boolean({json.dumps(root)}) && !roots.length, fallback}};
    }})()""")
    findings = []
    if result["missing"]:
        findings.append({"kind": "widget_missing", "message": f"Widget root not found: {root}"})
    if result["fallback"]:
        findings.append({"kind": "static_fallback", "message": f"Static fallback visible: {fallback}"})
    return findings


def exceptions(browser, page: str, route: str) -> list[dict]:
    return [{"page": page, "route": route, **item} for item in browser.event_findings()
            if item["kind"] in ("uncaught_exception", "console_error")]


def route_key(url: str) -> str:
    parts = urlsplit(crawl_key(page_url(url)))
    path = parts.path or "/"
    if not path.endswith("/") and "." not in path.rsplit("/", 1)[-1]:
        path += "/"
    return urlunsplit(parts._replace(path=path))


def navwalk(browser, start: str, pages: list[str], width: int, nav_selector: str,
            root: str, fallback: str, settle: float) -> list[dict]:
    findings = []

    def check(page: str, route: str):
        browser.pump(settle)
        findings.extend({"page": page, "route": route, **item} for item in inspect_widget(browser, root, fallback))
        findings.extend(exceptions(browser, page, route))

    for page in pages:
        try:
            browser.open(page, width)
            check(page, "direct")
        except BrowserError as exc:
            findings.append({"kind": "browser_error", "page": page, "route": "direct", "message": str(exc)})
        if route_key(page) == route_key(start):
            continue
        try:
            browser.open(start, width)
            browser.pump(settle)
            browser.events.clear()
            target = route_key(page)
            clicked = browser.evaluate(f"""(() => {{
                const target = {json.dumps(target)};
                const link = [...document.querySelectorAll({json.dumps(nav_selector)})].find(element => {{
                    const url = new URL(element.href, location.href);
                    if (url.pathname.endsWith('/index.html')) url.pathname = url.pathname.slice(0, -10);
                    else if (!url.pathname.endsWith('/') && !url.pathname.split('/').pop().includes('.')) url.pathname += '/';
                    url.hash = '';
                    return url.href === target;
                }});
                if (!link) return false;
                link.click();
                return true;
            }})()""")
            if not clicked:
                findings.append({"kind": "nav_link_missing", "page": page, "route": "nav",
                                 "message": f"No link to page matches {nav_selector} on home page"})
                continue
            check(page, "nav")
            actual = route_key(browser.evaluate("location.href"))
            if actual != target:
                findings.append({"kind": "nav_destination", "page": page, "route": "nav",
                                 "message": f"Navigation reached {actual} instead of {target}"})
        except BrowserError as exc:
            findings.append({"kind": "browser_error", "page": page, "route": "nav", "message": str(exc)})
    return findings


OPERATIONS = {"open", "click_text", "fill", "wait", "assert_text", "screenshot"}


def parse_walk(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("pages", {}), dict) or not isinstance(data.get("urls"), list) or not data["urls"]:
        raise ValueError("Walk script needs a pages map and a nonempty urls list")
    pages = data.get("pages", {})
    if any(not isinstance(key, str) or not isinstance(url, str) or not url for key, url in pages.items()):
        raise ValueError("Walk page ids and URLs must be strings")
    if any(not isinstance(target, str) or not target or (target in pages and not pages[target]) for target in data["urls"]):
        raise ValueError("Walk URLs or page ids must be nonempty strings")
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Walk steps must be a nonempty list")
    for step in steps:
        if not isinstance(step, dict) or len(step) != 1 or next(iter(step)) not in OPERATIONS:
            raise ValueError("Each walk step must contain exactly one supported operation")
        operation, argument = next(iter(step.items()))
        if operation in ("open", "click_text", "assert_text", "screenshot") and (not isinstance(argument, str) or not argument):
            raise ValueError(f"Walk {operation} needs a nonempty string")
        if operation == "screenshot" and (Path(argument).name != argument or argument in (".", "..")):
            raise ValueError("Screenshot names must be filenames, not paths")
        if operation == "fill" and (not isinstance(argument, dict) or not isinstance(argument.get("selector"), str)
                                    or not argument["selector"] or not isinstance(argument.get("value"), str)):
            raise ValueError("Walk fill needs a selector and string value")
        if operation == "wait" and (isinstance(argument, bool) or not (
                isinstance(argument, (int, float)) and argument >= 0 or
                isinstance(argument, dict) and isinstance(argument.get("text"), str) and argument["text"]
                and isinstance(argument.get("timeout", 10), (int, float)) and not isinstance(argument.get("timeout", 10), bool)
                and argument.get("timeout", 10) > 0)):
            raise ValueError("Walk wait needs seconds or a text and positive timeout")
    return data


def resolve(target: str, pages: dict, base: str | None) -> str:
    url = pages.get(target, target)
    if url == "$target":
        raise ValueError("$target can only appear in an open step")
    if urlparse(url).scheme not in ("http", "https") and not base:
        raise ValueError(f"Relative walk URL needs a site source: {url}")
    return urljoin(base or url, url)


def run_walk(browser, data: dict, base: str | None, output: Path, width: int,
             max_height: int) -> tuple[list[dict], list[dict]]:
    findings, shots = [], []
    pages = data.get("pages", {})
    for target in data["urls"]:
        page = resolve(target, pages, base)
        try:
            browser.open(page, width)
            findings.extend(exceptions(browser, page, "open"))
        except BrowserError as exc:
            findings.append({"kind": "browser_error", "page": page, "message": str(exc)})
            continue
        for index, step in enumerate(data["steps"], 1):
            operation, argument = next(iter(step.items()))
            browser.events.clear()
            try:
                if operation == "open":
                    browser.open(page if argument == "$target" else resolve(argument, pages, base or page), width)
                elif operation == "click_text":
                    if not browser.click_text(argument):
                        raise BrowserError(f"Text control not found: {argument}")
                elif operation == "fill":
                    if not browser.fill(argument["selector"], argument["value"]):
                        raise BrowserError(f"Input not found: {argument['selector']}")
                elif operation == "wait":
                    if isinstance(argument, dict):
                        deadline = time.monotonic() + argument.get("timeout", 10)
                        while argument["text"] not in browser.evaluate("document.body.innerText") and time.monotonic() < deadline:
                            browser.pump(min(0.2, max(0, deadline - time.monotonic())))
                        if argument["text"] not in browser.evaluate("document.body.innerText"):
                            raise BrowserError(f"Timed out waiting for text: {argument['text']}")
                    else:
                        browser.pump(argument)
                elif operation == "assert_text":
                    if argument not in browser.evaluate("document.body.innerText"):
                        raise BrowserError(f"Text not found: {argument}")
                elif operation == "screenshot":
                    digest = hashlib.sha1(page.encode()).hexdigest()[:8]
                    filename = f"{digest}_step{index}_{width}_{argument}"
                    path = output / "shots" / filename
                    browser.screenshot(path, width, max_height=max_height)
                    shots.append({"page": page, "theme": "light", "width": width,
                                  "path": path.relative_to(output).as_posix()})
                browser.pump(0.1)
                findings.extend(exceptions(browser, page, f"step {index}"))
            except BrowserError as exc:
                findings.append({"kind": "walk_step", "page": page, "step": index,
                                 "message": f"{operation}: {exc}"})
                findings.extend(exceptions(browser, page, f"step {index}"))
                break
    return findings, shots
