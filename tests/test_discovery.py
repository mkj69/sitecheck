from pathlib import Path
from urllib.parse import urlparse

from sitecheck.checks import LAYOUT_JS, overflow_findings, static_findings
from sitecheck import discovery


ORIGIN = "https://fixture.invalid/"


def fixture_fetch(directory: Path):
    def fetch(url: str, timeout: float = 10):
        path = urlparse(url).path.lstrip("/") or "index.html"
        file = directory / path
        return (200, file.read_bytes()) if file.is_file() else (404, b"")
    return fetch


def test_crawl_and_links(monkeypatch):
    directory = Path(__file__).parents[1] / "examples/demo-site"
    monkeypatch.setattr(discovery, "fetch", fixture_fetch(directory))
    pages = discovery.discover(ORIGIN, sitemap=False)
    assert len(pages) == 3
    assert any(page.endswith("about.html") for page in pages)
    assert len(discovery.discover(ORIGIN, sitemap=False, include=["/about.html"])) == 1
    assert len(discovery.discover(ORIGIN, sitemap=False, limit=2)) == 2
    _, body = discovery.fetch(ORIGIN)
    findings = static_findings(ORIGIN, discovery.parse_page(body))
    assert any(item["kind"] == "broken_link" for item in findings)
    assert not any(item["kind"] == "broken_anchor" for item in findings)


def test_sitemap_and_anchor(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text('<title>Start</title><a href="next.html#absent">Next</a>')
    (tmp_path / "next.html").write_text('<title>Next</title><h1 id="present">Hello</h1>')
    (tmp_path / "sitemap.xml").write_text(f'<urlset><url><loc>{ORIGIN}next.html</loc></url></urlset>')
    monkeypatch.setattr(discovery, "fetch", fixture_fetch(tmp_path))
    assert discovery.discover(ORIGIN) == [ORIGIN + "next.html"]
    _, body = discovery.fetch(ORIGIN)
    issues = discovery.check_links(ORIGIN, discovery.parse_page(body))
    assert issues[0]["kind"] == "broken_anchor"


def test_overflow_boxes():
    boxes = [
        {"selector": "#wide", "left": 0, "right": 1200},
        {"selector": "#okay", "left": 0, "right": 390},
        {"selector": "#hidden", "left": 0, "right": 900, "visible": False},
    ]
    assert [item["kind"] for item in overflow_findings(boxes, 390)] == ["overflow"]
    assert overflow_findings(boxes, 1440) == []


def test_layout_script_does_not_filter_with_browser_width():
    assert "window.innerWidth" not in LAYOUT_JS
    assert ".filter(" not in LAYOUT_JS


def test_missing_title_and_alt():
    page = discovery.parse_page(b'<img src="photo.png"><a href="#here">Here</a><h2 id="here">Here</h2>')
    assert [item["kind"] for item in static_findings(ORIGIN, page, {ORIGIN: (200, page)})] == ["missing_title", "missing_alt"]
