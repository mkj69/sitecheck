import base64
from contextlib import contextmanager
from io import BytesIO

from PIL import Image
import pytest

from sitecheck import cli
from sitecheck.browser import BrowserError
from sitecheck.strip import capture_strip


class FakeBrowser:
    def __init__(self):
        self.calls = []
        self.clicks = 0
        self.theme = "light"
        self.captures = []
        self.missing = False
        self.region_height = 3

    def open(self, *args):
        self.calls.append(("open", args))

    def pump(self, seconds):
        self.calls.append(("pump", seconds))

    def evaluate(self, expression):
        self.calls.append(("evaluate", expression))
        if "getAttribute(name)" in expression:
            return self.theme
        if "getBoundingClientRect" in expression:
            if self.missing:
                return None
            if "scrollIntoView" in expression:
                return {"x": 8, "y": 77, "width": 2, "height": self.region_height,
                        "top": 200, "bottom": 200 + self.region_height, "left": 8, "right": 10}
            return {"width": 2, "height": self.region_height}
        if "element.click()" in expression:
            if "palette-toggle" in expression:
                self.theme = "slate"
            else:
                self.clicks += 1
            return True
        return None

    def click_text(self, text, selector):
        self.calls.append(("click_text", text, selector))
        self.clicks += 1
        return True

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "Page.captureScreenshot":
            self.captures.append(params)
            image = Image.new("RGB", (2, 3), (self.clicks * 50, len(self.captures) * 20, 0))
            stream = BytesIO()
            image.save(stream, "PNG")
            return {"data": base64.b64encode(stream.getvalue()).decode()}
        return {}


@pytest.mark.parametrize("action,marker", [
    ({"click_selector": "#next"}, "#next"),
    ({"aria_label": "Next step"}, "Next step"),
    ({"button_text": "Next step"}, "click_text"),
])
def test_grid_and_actions(tmp_path, action, marker):
    browser = FakeBrowser()
    output = tmp_path / "nested" / "strip.png"
    size = capture_strip(browser, "https://example.org/", output, region=".pane",
                         delays=[0, 0.001], repeat=2, settle=0, **action)
    assert size == (4, 6)
    assert browser.clicks == 2
    assert len(browser.captures) == 4
    assert all(capture["clip"] == {"x": 8, "y": 77, "width": 2, "height": 3, "scale": 1}
               for capture in browser.captures)
    assert any(item[0] == "Emulation.setDeviceMetricsOverride" and item[1]["height"] == 900
               for item in browser.calls)
    assert any(marker in str(item) for item in browser.calls)
    with Image.open(output) as image:
        assert image.getpixel((0, 0)) == (50, 20, 0)
        assert image.getpixel((2, 0)) == (50, 40, 0)
        assert image.getpixel((0, 3)) == (100, 60, 0)


def test_click_theme_and_missing_region(tmp_path):
    browser = FakeBrowser()
    capture_strip(browser, "https://example.org/", tmp_path / "strip.png", region=".pane",
                  click_selector="#next", delays=[0], theme="dark", theme_mode="click",
                  theme_selector=".palette-toggle", theme_value="slate", settle=0)
    assert browser.theme == "slate"
    assert browser.calls[0] == ("open", ("https://example.org/", 1440, "light"))
    assert browser.clicks == 1
    browser.missing = True
    with pytest.raises(BrowserError, match="Region not found"):
        capture_strip(browser, "https://example.org/", tmp_path / "missing.png", region=".missing",
                      button_text="Next step", delays=[0], settle=0)


def test_missing_control_does_not_write_png(tmp_path):
    browser = FakeBrowser()
    browser.click_text = lambda *_args: False
    output = tmp_path / "missing.png"
    with pytest.raises(BrowserError, match="Click control not found"):
        capture_strip(browser, "https://example.org/", output, region=".pane",
                      button_text="Absent", delays=[0], settle=0)
    assert not output.exists()


def test_tall_region_enlarges_viewport(tmp_path):
    browser = FakeBrowser()
    browser.region_height = 700
    capture_strip(browser, "https://example.org/", tmp_path / "tall.png", region=".pane",
                  click_selector="#next", delays=[0], settle=0)
    assert any(item[0] == "Emulation.setDeviceMetricsOverride" and item[1]["height"] == 1100
               for item in browser.calls)
    assert browser.captures[0]["clip"]["height"] == 700


@pytest.mark.parametrize("options", [
    {"delays": []}, {"delays": [0.2, 0.1]}, {"delays": [float("nan")]},
    {"repeat": 0}, {"width": 0}, {"click_selector": "#x"},
    {"theme_mode": "click"}, {"settle": -1},
])
def test_invalid_options_fail_before_open(tmp_path, options):
    browser = FakeBrowser()
    kwargs = {"region": ".pane", "button_text": "Next", "delays": [0]}
    kwargs.update(options)
    with pytest.raises(ValueError):
        capture_strip(browser, "https://example.org/", tmp_path / "bad.png", **kwargs)
    assert not browser.calls


def test_cli_local_page_and_url(tmp_path, monkeypatch):
    browser = FakeBrowser()
    created = []

    @contextmanager
    def serve(_directory):
        yield "http://127.0.0.1:1234/"

    @contextmanager
    def chrome(executable, timeout):
        created.append((executable, timeout))
        yield browser

    monkeypatch.setattr(cli, "serve", serve)
    monkeypatch.setattr(cli, "Chrome", chrome)
    site = tmp_path / "site"
    site.mkdir()
    for source, extra, expected in [(str(site), ["--page", "/viewer/"], "http://127.0.0.1:1234/viewer/"),
                                    ("https://example.org/viewer", [], "https://example.org/viewer")]:
        output = tmp_path / "motion.png"
        assert cli.main(["strip", source, "--region", ".pane", "--button-text", "Next step",
                         "--delays", "0", "--output", str(output), *extra]) == 0
        assert any(item == ("open", (expected, 1440, "light")) for item in browser.calls)
        assert output.is_file()
    assert created == [(None, 150), (None, 150)]
    assert cli.main(["strip", str(site), "--region", ".pane", "--button-text", "Next step",
                     "--delays", "0.3,0.1", "--output", str(tmp_path / "bad.png")]) == 2
