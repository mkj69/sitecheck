"""Directory-based screenshot service for agents without browser or socket access."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import time
import traceback
from urllib.parse import urlsplit

from .browser import Chrome
from .discovery import serve


OVERFLOW_JS = r"""(() => {
  const viewport = document.documentElement.clientWidth;
  const overflowing = [];
  for (const element of document.querySelectorAll('body *')) {
    const bounds = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    if (!bounds.width || !bounds.height || bounds.right <= viewport + 1 ||
        bounds.left >= viewport || bounds.right <= 0 || style.display === 'none' ||
        style.visibility === 'hidden' || style.position === 'fixed') continue;
    let scrollBox = false;
    for (let parent = element.parentElement; parent; parent = parent.parentElement) {
      const parentStyle = getComputedStyle(parent);
      if (['auto', 'scroll'].includes(parentStyle.overflowX) && parent.scrollWidth > parent.clientWidth) {
        scrollBox = true;
        break;
      }
    }
    if (!scrollBox) overflowing.push({tag: element.tagName.toLowerCase(),
      cls: String(element.className || '').slice(0, 80), right: Math.round(bounds.right),
      text: (element.innerText || '').trim().slice(0, 60)});
  }
  return {scrollWidth: document.documentElement.scrollWidth, viewport,
    overflowing: overflowing.slice(0, 25), count: overflowing.length};
})()"""

THEME_JS = r"""(() => {
  const name = ATTRIBUTE;
  return document.documentElement.getAttribute(name) || document.body.getAttribute(name);
})()"""


def parse_request(request_file: Path) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", request_file.stem):
        raise ValueError("Request filename must be a safe, unique id")
    spec = json.loads(request_file.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or set(spec) - {"worktree", "build", "shots"}:
        raise ValueError("Request must contain only worktree, build, and shots")
    worktree = spec.get("worktree")
    if not isinstance(worktree, str) or not Path(worktree).is_absolute() or not Path(worktree).is_dir():
        raise ValueError("worktree must be an existing absolute directory")
    if type(spec.get("build", True)) is not bool:
        raise ValueError("build must be a boolean")
    shots = spec.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ValueError("shots must be a nonempty array")
    for shot in shots:
        if not isinstance(shot, dict) or set(shot) - {"path", "width", "theme", "click", "max_height"}:
            raise ValueError("Each shot must contain only path, width, theme, click, and max_height")
        path = shot.get("path", "/")
        if (not isinstance(path, str) or not path.startswith("/") or path.startswith("//")
                or urlsplit(path).scheme or urlsplit(path).netloc or urlsplit(path).fragment):
            raise ValueError("shot path must be a local absolute URL path without a fragment")
        for field, default in (("width", 1440), ("max_height", 6000)):
            number = shot.get(field, default)
            if type(number) is not int or number < 1:
                raise ValueError(f"shot {field} must be a positive integer")
        if shot.get("theme", "light") not in ("light", "dark"):
            raise ValueError("shot theme must be light or dark")
        if "click" in shot and (not isinstance(shot["click"], list) or
                                any(not isinstance(label, str) or not label for label in shot["click"])):
            raise ValueError("shot click must be an array of nonempty button labels")
    return spec


def switch_theme(browser, theme: str, selector: str, attribute: str, values: dict[str, str]):
    expression = THEME_JS.replace("ATTRIBUTE", json.dumps(attribute))
    for _ in range(3):
        if browser.evaluate(expression) == values[theme]:
            return
        if not browser.evaluate(r"""(() => {
          const element = document.querySelector(SELECTOR);
          if (!element) return false;
          element.click();
          return true;
        })()""".replace("SELECTOR", json.dumps(selector))):
            raise ValueError(f"Theme toggle not found: {selector}")
        browser.pump(0.5)
    if browser.evaluate(expression) != values[theme]:
        raise ValueError(f"Theme toggle did not select {theme}")


def handle(request_file: Path, output_dir: Path, *, build_command: str | None, site_dir: str,
           build_timeout: float, chrome: str | None, timeout: float, theme_mode: str,
           theme_attribute: str, theme_selector: str, theme_values: dict[str, str], settle: float,
           browser_factory=Chrome, server_factory=serve) -> None:
    output = output_dir / request_file.stem
    output.mkdir(parents=True, exist_ok=True)
    spec = parse_request(request_file)
    worktree = Path(spec["worktree"])
    if spec.get("build", True):
        if not build_command:
            raise ValueError("Set --build-command or use build: false for a prebuilt site")
        try:
            result = subprocess.run(build_command, shell=True, cwd=worktree, capture_output=True,
                                    text=True, timeout=build_timeout)
        except subprocess.TimeoutExpired as exc:
            (output / "build.log").write_text(str(exc), encoding="utf-8")
            raise RuntimeError("Build timed out; see build.log") from exc
        (output / "build.log").write_text(result.stdout[-4000:] + result.stderr[-8000:], encoding="utf-8")
        if result.returncode:
            raise RuntimeError("Build failed; see build.log")
    directory = (worktree / site_dir).resolve()
    if not directory.is_relative_to(worktree.resolve()) or not directory.is_dir():
        raise ValueError(f"Built site directory is missing or outside the worktree: {directory}")
    report = []
    with server_factory(directory) as origin:
        with browser_factory(chrome, timeout=timeout) as browser:
            for index, shot in enumerate(spec["shots"]):
                width = shot.get("width", 1440)
                theme = shot.get("theme", "light")
                browser.open(origin.rstrip("/") + shot.get("path", "/"), width,
                             "light" if theme_mode == "click" else theme,
                             "attribute" if theme_mode == "attribute" else "media", theme_attribute)
                if theme_mode == "click":
                    switch_theme(browser, theme, theme_selector, theme_attribute, theme_values)
                browser.pump(settle)
                for label in shot.get("click", []):
                    if not browser.click_text(label, "button, [role=button], [role=tab], [role=radio]"):
                        raise ValueError(f"Button not found: {label}")
                    browser.pump(settle)
                info = browser.evaluate(OVERFLOW_JS)
                if not isinstance(info, dict) or not {"scrollWidth", "viewport", "overflowing", "count"} <= info.keys():
                    raise ValueError("Overflow evaluation returned an invalid result")
                browser.evaluate("scrollTo(0, 0)")
                png = f"{index}.png"
                capture = browser.screenshot(output / png, width, max_height=shot.get("max_height", 6000))
                exceptions = [event.get("params", {}).get("exceptionDetails", {}).get("exception", {}).get(
                    "description", event.get("params", {}).get("exceptionDetails", {}).get("text", ""))[:200]
                    for event in browser.events if event.get("method") == "Runtime.exceptionThrown"]
                report.append({"shot": shot, "png": png, "exceptions": exceptions, **info, "capture": capture})
    temporary = output / "report.json.tmp"
    temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temporary.replace(output / "report.json")
    (output / "DONE").write_text("ok\n", encoding="utf-8")


def process_requests(request_dir: Path, output_dir: Path, **options) -> int:
    processed = 0
    for request in sorted(request_dir.glob("*.json")):
        output = output_dir / request.stem
        if (output / "DONE").exists() or (output / "ERROR").exists():
            continue
        try:
            handle(request, output_dir, **options)
        except Exception:
            output.mkdir(parents=True, exist_ok=True)
            (output / "ERROR").write_text(traceback.format_exc(), encoding="utf-8")
        processed += 1
    return processed


def serve_shots(request_dir: Path, output_dir: Path, *, poll: float = 2, **options) -> None:
    if poll <= 0:
        raise ValueError("Poll interval must be positive")
    if options["timeout"] <= 0 or options["build_timeout"] <= 0 or options["settle"] < 0:
        raise ValueError("Timeouts must be positive and settle must be nonnegative")
    if options["theme_mode"] == "click" and not options["theme_selector"]:
        raise ValueError("--theme-selector is required for click mode")
    if not options["theme_attribute"] or any(not value for value in options["theme_values"].values()):
        raise ValueError("Theme attribute and values must not be empty")
    if not options["site_dir"] or Path(options["site_dir"]).is_absolute():
        raise ValueError("--site-dir must be relative to the worktree")
    request_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Watching {request_dir} -> {output_dir} (Ctrl-C to stop)", flush=True)
    while True:
        process_requests(request_dir, output_dir, **options)
        time.sleep(poll)
