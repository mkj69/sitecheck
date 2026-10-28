from contextlib import contextmanager
import json
from pathlib import Path

import pytest

from sitecheck import cli, shot_service


def request(tmp_path, spec, name="capture"):
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def options():
    return {"build_command": None, "site_dir": "site", "build_timeout": 30,
            "chrome": None, "timeout": 150, "theme_mode": "media",
            "theme_attribute": "data-theme", "theme_selector": "", "settle": 0,
            "theme_values": {"light": "light", "dark": "dark"}}


def test_request_defaults_and_schema(tmp_path):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    spec = {"worktree": str(worktree), "shots": [{"path": "/guide/?x=1", "click": ["Next"]}]}
    assert shot_service.parse_request(request(tmp_path, spec)) == spec
    invalid = [
        {**spec, "extra": True}, {**spec, "worktree": "relative"},
        {**spec, "shots": []}, {**spec, "build": "false"},
        {**spec, "shots": [{"path": "https://example.com/"}]},
        {**spec, "shots": [{"path": "//example.com/"}]},
        {**spec, "shots": [{"width": True}]},
        {**spec, "shots": [{"max_height": 0}]},
        {**spec, "shots": [{"theme": "blue"}]},
        {**spec, "shots": [{"click": "Next"}]},
        {**spec, "shots": [{"unexpected": 1}]},
    ]
    for index, entry in enumerate(invalid):
        with pytest.raises(ValueError):
            shot_service.parse_request(request(tmp_path, entry, f"bad{index}"))
    with pytest.raises(ValueError, match="filename"):
        shot_service.parse_request(request(tmp_path, spec, "..bad"))


@contextmanager
def fake_server(directory):
    assert directory.is_dir()
    yield "http://127.0.0.1:41414/"


class FakeBrowser:
    instances = []

    def __init__(self, executable, timeout):
        assert executable is None and timeout == 150
        self.opens = []
        self.clicks = []
        self.events = []
        self.theme = "light"
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def open(self, url, width, theme, mode, attribute):
        self.opens.append((url, width, theme, mode, attribute))
        self.theme = theme
        self.events = [{"method": "Runtime.exceptionThrown", "params": {
            "exceptionDetails": {"exception": {"description": "Test error"}}}}]

    def pump(self, seconds):
        assert seconds >= 0

    def click_text(self, label, selector):
        self.clicks.append(label)
        return label != "Missing"

    def evaluate(self, expression):
        if "return document.documentElement.getAttribute" in expression:
            return self.theme
        if "element.click()" in expression:
            self.theme = "dark" if self.theme == "light" else "light"
            return True
        if "scrollWidth:" in expression:
            assert "const viewport" in expression
            return {"scrollWidth": 425, "viewport": 390, "overflowing": [{"tag": "div"}], "count": 1}
        return None

    def screenshot(self, path, width, max_height):
        path.write_bytes(b"PNG")
        return {"height": 100, "full_height": 100, "truncated": False}


def test_report_and_markers_with_fake_browser(tmp_path):
    worktree = tmp_path / "worktree"
    (worktree / "site").mkdir(parents=True)
    requests = tmp_path / "requests"
    requests.mkdir()
    output = tmp_path / "output"
    request(requests, {"worktree": str(worktree), "build": False, "shots": [
        {"path": "/guide/", "width": 390, "theme": "dark", "click": ["Next"]},
        {"path": "/", "click": ["Missing"]}]}, "first")
    config = {**options(), "theme_mode": "click", "theme_selector": "#toggle"}
    assert shot_service.process_requests(requests, output, **config, browser_factory=FakeBrowser,
                                          server_factory=fake_server) == 1
    assert (output / "first" / "ERROR").exists()
    assert "Button not found: Missing" in (output / "first" / "ERROR").read_text()
    assert shot_service.process_requests(requests, output, **config, browser_factory=FakeBrowser,
                                          server_factory=fake_server) == 0
    request(requests, {"worktree": str(worktree), "build": False, "shots": [
        {"path": "/guide/?x=1", "width": 390, "theme": "dark", "click": ["Next"]},
        {"path": "/"}]}, "second")
    assert shot_service.process_requests(requests, output, **config, browser_factory=FakeBrowser,
                                          server_factory=fake_server) == 1
    result = json.loads((output / "second" / "report.json").read_text())
    assert (output / "second" / "DONE").exists()
    assert not (output / "second" / "ERROR").exists()
    assert [item["png"] for item in result] == ["0.png", "1.png"]
    assert result[0]["scrollWidth"] == 425 and result[0]["viewport"] == 390
    assert result[0]["count"] == 1 and result[0]["exceptions"] == ["Test error"]
    assert (output / "second" / "0.png").read_bytes() == b"PNG"
    assert FakeBrowser.instances[-1].opens[0][:3] == ("http://127.0.0.1:41414/guide/?x=1", 390, "light")
    assert FakeBrowser.instances[-1].clicks == ["Next"]


def test_build_failure_and_cli_defaults(tmp_path, monkeypatch):
    worktree = tmp_path / "worktree"
    (worktree / "site").mkdir(parents=True)
    requests = tmp_path / "requests"
    requests.mkdir()
    output = tmp_path / "output"
    request(requests, {"worktree": str(worktree), "shots": [{}]})
    assert shot_service.process_requests(requests, output, **{**options(), "build_command": "exit 7"},
                                          browser_factory=FakeBrowser, server_factory=fake_server) == 1
    assert "Build failed" in (output / "capture" / "ERROR").read_text()
    assert (output / "capture" / "build.log").exists()

    def stop(request_dir, output_dir, **kwargs):
        assert request_dir == Path("shot-requests")
        assert output_dir == Path("shot-output")
        assert kwargs["timeout"] == 150
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "serve_shots", stop)
    assert cli.main(["serve-shots"]) == 0


def test_build_runs_in_worktree_and_invalid_json_gets_error(tmp_path, monkeypatch):
    worktree = tmp_path / "worktree"
    (worktree / "site").mkdir(parents=True)
    requests = tmp_path / "requests"
    requests.mkdir()
    output = tmp_path / "output"
    request(requests, {"worktree": str(worktree), "shots": [{}]}, "valid")
    (requests / "invalid.json").write_text("{", encoding="utf-8")
    seen = []

    def build(command, **kwargs):
        seen.append((command, kwargs))
        return type("Result", (), {"returncode": 0, "stdout": "built", "stderr": ""})()

    monkeypatch.setattr(shot_service.subprocess, "run", build)
    assert shot_service.process_requests(requests, output, **{**options(), "build_command": "make site"},
                                          browser_factory=FakeBrowser, server_factory=fake_server) == 2
    assert seen[0][0] == "make site"
    assert seen[0][1]["cwd"] == worktree
    assert seen[0][1]["timeout"] == 30
    assert (output / "valid" / "build.log").read_text() == "built"
    assert (output / "valid" / "DONE").exists()
    assert "JSONDecodeError" in (output / "invalid" / "ERROR").read_text()
    assert not (output / "invalid" / "DONE").exists()


def test_service_option_validation(tmp_path):
    for change in ({"timeout": 0}, {"build_timeout": -1}, {"settle": -1},
                   {"theme_mode": "click"}, {"site_dir": "/tmp/site"}):
        with pytest.raises(ValueError):
            shot_service.serve_shots(tmp_path / "requests", tmp_path / "output", **{**options(), **change})
