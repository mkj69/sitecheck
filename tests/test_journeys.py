from contextlib import contextmanager
import json

import pytest

from sitecheck import cli, journeys
from sitecheck.reports import write_reports


def test_language_rules_and_report(tmp_path):
    rules = journeys.parse_rules([{"page": "*/en/*", "scripts": ["cjk", "cyrillic"],
                                  "allow": ["示例"]}])
    findings = journeys.language_findings("Hello\n示例\n中文 text\nПривет", "https://example.org/en/", rules)
    assert [finding["kind"] for finding in findings] == ["wrong_script", "wrong_script"]
    assert "中文" in findings[0]["message"]
    assert journeys.language_findings("中文", "https://example.org/zh/", rules) == []
    assert write_reports(tmp_path, findings, rules=[{"kind": "wrong_script", "message": "cjk*"}]) == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["error_counts_by_kind"] == {"wrong_script": 1}
    assert [item["allowed"] for item in report["findings"]] == [True, False]


def test_route_key_and_widget_reporting():
    assert journeys.route_key("https://example.org/guide/index.html#intro") == "https://example.org/guide/"
    assert journeys.route_key("https://example.org/guide") == "https://example.org/guide/"

    class Browser:
        def evaluate(self, script):
            assert ".widget" in script and ".fallback" in script
            return {"missing": True, "fallback": True}

    assert [item["kind"] for item in journeys.inspect_widget(Browser(), ".widget", ".fallback")] == [
        "widget_missing", "static_fallback"]


@pytest.mark.parametrize("bad", [
    {"urls": [], "steps": []},
    {"urls": ["home"], "steps": [{"click_text": ""}]},
    {"urls": ["home"], "steps": [{"fill": {"selector": "#x"}}]},
    {"urls": ["home"], "steps": [{"wait": {"text": "ok", "timeout": -1}}]},
    {"urls": ["home"], "steps": [{"screenshot": "../secret.png"}]},
    {"urls": ["home"], "steps": [{"open": "/"}, {"assert_text": "yes", "unknown": 3}]},
])
def test_invalid_walk(tmp_path, bad):
    script = tmp_path / "walk.json"
    script.write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        journeys.parse_walk(script)


def test_walk_steps_and_failures(tmp_path):
    script = tmp_path / "walk.json"
    script.write_text(json.dumps({"pages": {"home": "/", "guide": "/guide/"},
                                  "urls": ["home", "guide"],
                                  "steps": [{"click_text": "Play"}, {"fill": {"selector": "#name", "value": "Ada"}},
                                            {"wait": {"text": "Ready", "timeout": 1}},
                                            {"assert_text": "Ready"}, {"screenshot": "result.png"}]}))
    data = journeys.parse_walk(script)

    class Browser:
        def __init__(self):
            self.events = []
            self.opened = []

        def open(self, url, width):
            self.opened.append(url)

        def click_text(self, text):
            return self.opened[-1].endswith("/") and "guide" not in self.opened[-1]

        def fill(self, selector, value):
            return selector == "#name" and value == "Ada"

        def evaluate(self, expression):
            return "Ready"

        def pump(self, seconds):
            pass

        def screenshot(self, path, width, max_height):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")

        def event_findings(self):
            return []

    browser = Browser()
    findings, shots = journeys.run_walk(browser, data, "https://example.org/", tmp_path, 390, 1000)
    assert browser.opened == ["https://example.org/", "https://example.org/guide/"]
    assert len(shots) == 1 and (tmp_path / shots[0]["path"]).exists()
    assert findings[0]["step"] == 1 and findings[0]["page"].endswith("/guide/")
    assert write_reports(tmp_path, findings, shots) == 1
    assert "(step 1)" in (tmp_path / "report.html").read_text()


def test_navwalk_reports_direct_and_clicked_routes(tmp_path, monkeypatch):
    start = "https://example.org/"
    page = start + "guide/"

    @contextmanager
    def browser_context(*args, **kwargs):
        class Browser:
            events = []

            def open(self, url, width):
                self.url = url

            def pump(self, seconds):
                pass

            def evaluate(self, script):
                if "const link" in script:
                    self.url = page
                    return True
                if script == "location.href":
                    return self.url
                return {"missing": False, "fallback": self.url == page}

            def event_findings(self):
                return [{"kind": "uncaught_exception", "message": "broken"}] if self.url == page else []

        yield Browser()

    monkeypatch.setattr(cli, "Chrome", browser_context)
    monkeypatch.setattr(cli, "discover", lambda *args, **kwargs: [page])
    output = tmp_path / "report"
    assert cli.main(["navwalk", start, "--widget-root", ".widget", "--static-fallback", ".static",
                     "--output", str(output)]) == 1
    report = json.loads((output / "report.json").read_text())
    assert report["error_counts_by_kind"] == {"static_fallback": 2, "uncaught_exception": 2}
    assert {finding["route"] for finding in report["findings"]} == {"direct", "nav"}


def test_lang_cli_uses_rendered_text(tmp_path, monkeypatch):
    @contextmanager
    def browser_context(*args, **kwargs):
        class Browser:
            def open(self, url, width):
                pass

            def pump(self, seconds):
                pass

            def evaluate(self, script):
                assert script == "document.body.innerText"
                return "Hello 中文"

            def event_findings(self):
                return []

        yield Browser()

    monkeypatch.setattr(cli, "Chrome", browser_context)
    monkeypatch.setattr(cli, "discover", lambda *args, **kwargs: ["https://example.org/en/"])
    config = tmp_path / "config.toml"
    config.write_text('lang_rules = [{ page = "*/en/*", scripts = ["cjk"] }]\n')
    output = tmp_path / "report"
    assert cli.main(["--config", str(config), "lang", "https://example.org/", "--output", str(output)]) == 1
    assert json.loads((output / "report.json").read_text())["error_counts_by_kind"] == {"wrong_script": 1}
