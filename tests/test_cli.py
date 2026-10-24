from contextlib import contextmanager
import json
from pathlib import Path

from PIL import Image

from sitecheck import cli, discovery
from test_discovery import ORIGIN, fixture_fetch


@contextmanager
def fake_serve(_directory):
    yield ORIGIN


def test_pages_and_doc_commands(tmp_path, capsys, monkeypatch):
    site = Path(__file__).parents[1] / "examples/demo-site"
    monkeypatch.setattr(cli, "serve", fake_serve)
    monkeypatch.setattr(discovery, "fetch", fixture_fetch(site))
    assert cli.main(["pages", str(site), "--no-sitemap"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 3
    output = tmp_path / "out"
    assert cli.main(["doc-commands", str(site / "docs"), "--output", str(output)]) == 0
    assert (output / "report.json").is_file()


def test_smoke_writes_report_when_browser_unavailable(tmp_path, monkeypatch):
    site = Path(__file__).parents[1] / "examples/demo-site"
    fake_fetch = fixture_fetch(site)
    monkeypatch.setattr(cli, "serve", fake_serve)
    monkeypatch.setattr(discovery, "fetch", fake_fetch)
    monkeypatch.setattr(cli, "fetch", fake_fetch)

    def unavailable(*_args, **_kwargs):
        raise cli.BrowserError("Browser unavailable")

    monkeypatch.setattr(cli, "Chrome", unavailable)
    output = tmp_path / "out"
    assert cli.main(["smoke", str(site), "--output", str(output)]) == 1
    import json
    report = json.loads((output / "report.json").read_text())
    kinds = {item["kind"] for item in report["findings"]}
    assert "broken_link" in kinds
    assert "browser_error" in kinds


def test_browser_timeout_config_and_cli_override(tmp_path, monkeypatch):
    site = Path(__file__).parents[1] / "examples/demo-site"
    fake_fetch = fixture_fetch(site)
    monkeypatch.setattr(cli, "serve", fake_serve)
    monkeypatch.setattr(discovery, "fetch", fake_fetch)
    monkeypatch.setattr(cli, "fetch", fake_fetch)
    observed = []

    def unavailable(*_args, timeout):
        observed.append(timeout)
        raise cli.BrowserError("Browser unavailable")

    monkeypatch.setattr(cli, "Chrome", unavailable)
    config = tmp_path / "sitecheck.toml"
    config.write_text("browser_timeout = 55\n")
    for extra in ([], ["--timeout", "60"]):
        assert cli.main(["--config", str(config), "smoke", str(site),
                         "--limit", "1", "--output", str(tmp_path / "out"), *extra]) == 1
    assert observed == [55, 60]


def test_all_reports_overflow_and_captures_every_viewport(tmp_path, monkeypatch):
    site = Path(__file__).parents[1] / "examples/demo-site"
    fake_fetch = fixture_fetch(site)
    monkeypatch.setattr(cli, "serve", fake_serve)
    monkeypatch.setattr(discovery, "fetch", fake_fetch)
    monkeypatch.setattr(cli, "fetch", fake_fetch)

    class FakeChrome:
        def __init__(self, _executable, timeout):
            assert timeout == 40

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def open(self, page, width, *_args):
            self.page = page

        def layout_boxes(self):
            if self.page.endswith("/"):
                return [{"selector": "#wide-panel", "left": 0, "right": 1200, "visible": True}]
            return []

        def event_findings(self):
            return []

        def screenshot(self, output, _width):
            output.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (1, 1)).save(output)
            return 1

    monkeypatch.setattr(cli, "Chrome", FakeChrome)
    output = tmp_path / "out"
    assert cli.main(["all", str(site), "--output", str(output)]) == 1
    report = json.loads((output / "report.json").read_text())
    assert any(item["kind"] == "overflow" and "#wide-panel" in item["message"]
               and item["viewport"] == 390 for item in report["findings"])
    assert any(item["kind"] == "broken_link" and "missing.html" in item["message"]
               for item in report["findings"])
    assert not any(item["kind"] == "browser_error" for item in report["findings"])
    assert len(report["screenshots"]) == len(list((output / "shots").glob("*.png"))) == 12
