"""Minimal Chrome DevTools pipe client and page capture."""

from __future__ import annotations

import base64
from io import BytesIO
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from PIL import Image

from .checks import LAYOUT_JS


class BrowserError(RuntimeError):
    pass


DEFAULT_BROWSER_TIMEOUT = 40


class Chrome:
    def __init__(self, executable: str | None = None, timeout: float = DEFAULT_BROWSER_TIMEOUT):
        self.executable = executable or os.environ.get("SITECHECK_CHROME") or shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
        if not self.executable:
            raise BrowserError("Chrome was not found. Set --chrome or SITECHECK_CHROME.")
        if timeout <= 0:
            raise ValueError("Browser timeout must be positive")
        self.timeout = timeout
        self.process = None
        self.events: list[dict] = []
        self._buffer = b""
        self._id = 0
        self.session = None
        self._profile = None

    def __enter__(self):
        self._profile = tempfile.TemporaryDirectory(prefix="sitecheck-chrome-")
        read_in, write_in = os.pipe()
        read_out, write_out = os.pipe()

        def setup_pipe():
            os.dup2(read_in, 3)
            os.dup2(write_out, 4)
            os.set_inheritable(3, True)
            os.set_inheritable(4, True)

        try:
            self.process = subprocess.Popen(
                [self.executable, "--headless=new", "--no-sandbox", "--disable-gpu",
                 "--hide-scrollbars", "--remote-debugging-pipe",
                 f"--user-data-dir={self._profile.name}", "about:blank"],
                preexec_fn=setup_pipe, close_fds=False,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, ValueError) as exc:
            self._profile.cleanup()
            raise BrowserError(f"Could not start Chrome: {exc}") from exc
        finally:
            os.close(read_in)
            os.close(write_out)
        self._input = write_in
        self._output = read_out
        try:
            targets = self.call("Target.getTargets")["targetInfos"]
            page = next(item for item in targets if item["type"] == "page")
            self.session = self.call("Target.attachToTarget", {"targetId": page["targetId"], "flatten": True})["sessionId"]
            for method in ("Page.enable", "Runtime.enable", "Log.enable", "Network.enable"):
                self.call(method)
            return self
        except Exception as exc:
            self.__exit__(None, None, None)
            raise BrowserError(f"Chrome pipe did not initialize: {exc}") from exc

    def __exit__(self, *_):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        for descriptor in (getattr(self, "_input", None), getattr(self, "_output", None)):
            if descriptor is not None:
                os.close(descriptor)
        if self._profile:
            self._profile.cleanup()

    def _receive(self, timeout: float) -> dict | None:
        end = time.monotonic() + timeout
        while b"\0" not in self._buffer:
            remaining = end - time.monotonic()
            if remaining <= 0:
                return None
            readable, _, _ = select.select([self._output], [], [], remaining)
            if readable:
                chunk = os.read(self._output, 1 << 20)
                if not chunk:
                    return None
                self._buffer += chunk
        data, self._buffer = self._buffer.split(b"\0", 1)
        return json.loads(data)

    def call(self, method: str, params: dict | None = None, timeout: float | None = None) -> dict:
        self._id += 1
        message = {"id": self._id, "method": method, "params": params or {}}
        if self.session:
            message["sessionId"] = self.session
        os.write(self._input, json.dumps(message).encode() + b"\0")
        end = time.monotonic() + (timeout if timeout is not None else self.timeout)
        while time.monotonic() < end:
            received = self._receive(end - time.monotonic())
            if received is None:
                break
            if received.get("id") == self._id:
                if "error" in received:
                    raise BrowserError(f"{method}: {received['error']}")
                return received.get("result", {})
            self.events.append(received)
        raise BrowserError(f"Chrome timed out during {method}")

    def pump(self, seconds: float):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            message = self._receive(end - time.monotonic())
            if message is None:
                break
            self.events.append(message)

    def evaluate(self, expression: str):
        result = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        if "exceptionDetails" in result:
            raise BrowserError(f"JavaScript evaluation failed: {result['exceptionDetails'].get('text', '')}")
        return result.get("result", {}).get("value")

    def click_text(self, text: str, selector: str = "button, a, [role=button], [role=tab], [role=radio]") -> bool:
        return bool(self.evaluate(f"""(() => {{
            const visible = element => element.getClientRects().length && getComputedStyle(element).visibility !== 'hidden';
            const element = [...document.querySelectorAll({json.dumps(selector)})]
                .find(item => visible(item) && item.innerText.trim() === {json.dumps(text)});
            if (!element) return false;
            element.click();
            return true;
        }})()"""))

    def fill(self, selector: str, value: str) -> bool:
        return bool(self.evaluate(f"""(() => {{
            const element = document.querySelector({json.dumps(selector)});
            if (!element) return false;
            element.value = {json.dumps(value)};
            element.dispatchEvent(new Event('input', {{bubbles: true}}));
            element.dispatchEvent(new Event('change', {{bubbles: true}}));
            return true;
        }})()"""))

    def open(self, url: str, width: int, theme: str = "light", theme_mode: str = "media", theme_attribute: str = "data-theme", theme_query: str = "theme"):
        self.events.clear()
        self.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900,
                  "deviceScaleFactor": 1, "mobile": width < 600})
        self.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": theme}]})
        if theme_mode == "query":
            parts = urlsplit(url)
            query = dict(parse_qsl(parts.query, keep_blank_values=True))
            query[theme_query] = theme
            url = urlunsplit(parts._replace(query=urlencode(query)))
        self.events.clear()
        navigation = self.call("Page.navigate", {"url": url})
        if navigation.get("errorText"):
            raise BrowserError(f"Page navigation failed: {navigation['errorText']}")
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if any(event.get("method") == "Page.loadEventFired" for event in self.events):
                break
            self.pump(0.2)
        else:
            raise BrowserError(f"Page did not finish loading: {url}")
        if theme_mode == "attribute":
            self.evaluate(f"document.documentElement.setAttribute({json.dumps(theme_attribute)}, {json.dumps(theme)})")
        self.pump(0.3)

    def layout_boxes(self) -> dict:
        return self.evaluate(LAYOUT_JS)

    def screenshot(self, output: Path, width: int, max_height: int = 40000) -> dict:
        if max_height < 1:
            raise ValueError("Maximum screenshot height must be positive")
        height = int(self.evaluate("Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)"))
        if height < 1:
            raise BrowserError(f"Page height {height}px is below 1px")
        self.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": min(height, 8000),
                  "deviceScaleFactor": 1, "mobile": width < 600})
        self.pump(0.2)
        height = int(self.evaluate("Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)"))
        if height < 1:
            raise BrowserError(f"Page height {height}px is below 1px")
        captured_height = min(height, max_height)
        image = Image.new("RGB", (width, captured_height))
        for y in range(0, captured_height, 8000):
            tile_height = min(8000, captured_height - y)
            result = self.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True,
                               "clip": {"x": 0, "y": y, "width": width, "height": tile_height, "scale": 1}})
            with Image.open(BytesIO(base64.b64decode(result["data"]))) as tile:
                if tile.size != (width, tile_height):
                    raise BrowserError(f"Screenshot tile at {y}px has size {tile.size}, expected {(width, tile_height)}")
                image.paste(tile.convert("RGB"), (0, y))
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output, format="PNG")
        return {"height": captured_height, "full_height": height, "truncated": height > max_height}

    def event_findings(self) -> list[dict]:
        findings = []
        for event in self.events:
            method, data = event.get("method"), event.get("params", {})
            if method == "Runtime.consoleAPICalled" and data.get("type") in ("error", "assert"):
                message = " ".join(str(arg.get("value", arg.get("description", ""))) for arg in data.get("args", []))
                findings.append({"kind": "console_error", "message": message})
            elif method == "Runtime.exceptionThrown":
                details = data.get("exceptionDetails", {})
                findings.append({"kind": "uncaught_exception", "message": details.get("text", "JavaScript exception")})
            elif method == "Network.responseReceived":
                response = data.get("response", {})
                if response.get("status", 0) >= 400:
                    findings.append({"kind": "failed_request", "message": f"{response.get('status')} {response.get('url', '')}"})
            elif method == "Network.loadingFailed" and not data.get("canceled"):
                findings.append({"kind": "failed_request", "message": data.get("errorText", "Request failed")})
        return findings
