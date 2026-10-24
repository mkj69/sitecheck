"""Discover pages and check ordinary HTML links without a browser."""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from fnmatch import fnmatch
from functools import partial
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urljoin, urlparse, unquote
from urllib.request import urlopen
import xml.etree.ElementTree as ET


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.images_without_alt: list[str] = []
        self.title = ""
        self._title = False

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if data.get("id"):
            self.ids.add(data["id"])
        if tag == "a":
            if data.get("name"):
                self.ids.add(data["name"])
            if data.get("href"):
                self.links.append(data["href"])
        if tag == "img" and not data.get("alt") and "alt" not in data:
            self.images_without_alt.append(data.get("src", "<image>"))
        if tag == "title":
            self._title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._title = False

    def handle_data(self, data):
        if self._title:
            self.title += data


def fetch(url: str, timeout: float = 10) -> tuple[int, bytes]:
    try:
        with urlopen(url, timeout=timeout) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def parse_page(body: bytes) -> PageParser:
    page = PageParser()
    page.feed(body.decode("utf-8", errors="replace"))
    return page


def same_site(url: str, root: str) -> bool:
    return urlparse(url).netloc == urlparse(root).netloc and urlparse(url).scheme == urlparse(root).scheme


def page_url(url: str) -> str:
    return urldefrag(url)[0]


def selected(url: str, include: list[str], exclude: list[str]) -> bool:
    path = unquote(urlparse(url).path) or "/"
    return (not include or any(fnmatch(path, pattern) for pattern in include)) and not any(
        fnmatch(path, pattern) for pattern in exclude
    )


def crawl_key(url: str) -> str:
    parsed = urlparse(url)
    if parsed.path.endswith("/index.html"):
        return url[: -len("index.html")]
    return url


def discover(start: str, *, include: list[str] | None = None, exclude: list[str] | None = None,
             limit: int = 100, sitemap: bool = True) -> list[str]:
    if limit < 1:
        raise ValueError("limit must be positive")
    include, exclude = include or [], exclude or []
    start = page_url(start)
    root = f"{urlparse(start).scheme}://{urlparse(start).netloc}"
    if sitemap:
        try:
            status, body = fetch(urljoin(root, "/sitemap.xml"))
            if status < 400:
                tree = ET.fromstring(body)
                urls = [page_url(node.text.strip()) for node in tree.iter()
                        if node.tag.rsplit("}", 1)[-1] == "loc" and node.text]
                pages = list(dict.fromkeys(url for url in urls if same_site(url, start)
                                           and selected(url, include, exclude)))
                if pages:
                    return pages[:limit]
        except (OSError, ET.ParseError, ValueError):
            pass
    pending = deque([start])
    seen: set[str] = set()
    pages: list[str] = []
    while pending and len(pages) < limit:
        url = pending.popleft()
        key = crawl_key(url)
        if key in seen:
            continue
        seen.add(key)
        try:
            status, body = fetch(url)
        except (URLError, OSError):
            continue
        if status >= 400:
            continue
        if selected(url, include, exclude):
            pages.append(url)
        parsed = parse_page(body)
        for href in parsed.links:
            child = page_url(urljoin(url, href))
            path = urlparse(child).path.lower()
            if same_site(child, start) and (path.endswith(("/", ".html", ".htm")) or not Path(path).suffix):
                if crawl_key(child) not in seen:
                    pending.append(child)
    return pages


def check_links(url: str, page: PageParser, cache: dict[str, tuple[int, PageParser | None]] | None = None) -> list[dict]:
    """Check internal destinations and fragments. Cache destination fetches across pages."""
    cache = cache if cache is not None else {}
    issues: list[dict] = []
    for href in page.links:
        dest = urljoin(url, href)
        if not same_site(dest, url):
            continue
        target, fragment = urldefrag(dest)
        if target not in cache:
            try:
                status, body = fetch(target)
                cache[target] = status, parse_page(body) if status < 400 else None
            except (URLError, OSError) as exc:
                cache[target] = 0, None
        status, parsed = cache[target]
        if status == 0 or status >= 400:
            issues.append({"kind": "broken_link", "message": f"{href} returned {status or 'connection error'}"})
        elif fragment and parsed and unquote(fragment) not in parsed.ids:
            issues.append({"kind": "broken_anchor", "message": f"{href} has no target"})
    return issues


@contextmanager
def serve(directory: Path):
    """Serve a directory on a free loopback port for the duration of a command."""
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = partial(QuietHandler, directory=str(directory.resolve()))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
