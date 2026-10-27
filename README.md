# sitecheck

Sitecheck finds pages, checks common static site problems, captures screenshots, and runs shell examples from Markdown. It is useful before publishing a site or reviewing a redesign.

Originally built for the Opulse release.

## Install

Python 3.10 or newer and Chrome are required for browser checks. Pillow is installed with the package. Chrome is found on `PATH`, or set `--chrome` or `SITECHECK_CHROME`.

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

## Quick start

Pass a URL or a directory. A directory is served on a free local port while the command runs.

```sh
sitecheck init
sitecheck pages examples/demo-site
sitecheck smoke examples/demo-site
sitecheck shots examples/demo-site
sitecheck all examples/demo-site
sitecheck doc-commands examples/demo-site/docs
sitecheck navwalk examples/demo-site
sitecheck walk examples/demo-site --script examples/walk.json
```

The demo includes a broken link and a wide panel. Reports go to `sitecheck-out/report.json`, `report.md`, and `report.html`. Screenshots and contact sheets appear there when requested. `smoke`, `doc-commands`, and `all` return a nonzero status when errors are found.

Overflow is reported once per page and viewport when the document is wider than its viewport. The finding includes a culprit count and up to five element selectors. Elements clipped by an ancestor inside the viewport, hidden elements, fixed elements, zero size elements, and offscreen elements are excluded from the culprit list. The report summary shows error counts by kind.

Screenshots are captured in vertical tiles of at most 8000 pixels and stitched into a PNG. Chrome does not scroll the page during capture. Use `--max-height 40000` to set the maximum captured height. Taller pages are truncated and the report records their full height. The same limit can be set with `max_height` in the configuration file.

## Configuration

`sitecheck init` writes `sitecheck.toml`. Command options override matching settings.

| Setting | Meaning | Default |
| --- | --- | --- |
| `source` | URL or directory | none |
| `output` | Report directory | `sitecheck-out` |
| `viewports` | Widths in pixels | `[1440, 390]` |
| `themes` | Screenshot themes | `light`, `dark` |
| `limit` | Maximum discovered pages | `100` |
| `include`, `exclude` | URL path globs | empty |
| `sitemap` | Read `/sitemap.xml` before crawling | `true` |
| `chrome` | Chrome executable | `PATH` or `SITECHECK_CHROME` |
| `browser_timeout` | Seconds allowed per Chrome command, overridden by `--timeout` | `40` |
| `max_height` | Maximum screenshot height in pixels, overridden by `--max-height` | `40000` |
| `theme_mode` | `media`, `attribute`, or `query` | `media` |
| `theme_attribute`, `theme_query` | Attribute or query key | `data-theme`, `theme` |
| `docs` | Markdown files or directories for `all` and `doc-commands` | `docs` |
| `doc_languages` | Fence languages to execute | `bash`, `sh`, `shell` |
| `doc_skip_marker` | Comment text that skips a block | `sitecheck: skip` |
| `doc_cwd`, `doc_timeout` | Command working directory and seconds per block | `.`, `30` |
| `doc_env` | Environment values passed to each command | empty |
| `allow` | Finding rules with `kind`, optional `page` and `message` globs | empty |
| `nav_selector` | CSS selector for home page navigation links | `nav a` |
| `widget_root`, `static_fallback` | CSS selectors for expected widget roots and visible fallback content | empty |
| `settle` | Seconds to wait after a page load or navigation | `1.5` |
| `lang_rules` | Page globs, forbidden scripts, and literal text exemptions | empty |

Each documentation block runs in a fresh Bash process with `-e` and `pipefail`. Use `--env NAME=VALUE` for a command environment variable. Failed blocks report their file, line, exit status, and output tail. The skip marker may appear anywhere inside a block.

An allow rule can suppress a known finding:

```toml
allow = [{ kind = "broken_link", page = "*/draft.html" }]
```

## Navigation walk

A direct load can work even when an in-site click leaves a widget uninitialised. `sitecheck navwalk SITE` discovers pages, loads each directly, then returns to the home page and follows a matching navigation link to every other page. It reports missing navigation links, wrong destinations, missing widget roots, visible static fallbacks, console errors, and uncaught JavaScript exceptions. Findings include `route` as `direct` or `nav`. JavaScript-rendered navigation links are supported, but pages not linked from the selected home navigation are reported as missing. Use `--include` or `--exclude` to scope discovery, and `--nav-selector`, `--widget-root`, `--static-fallback`, `--settle`, or `--width` to adjust checks. Selectors are optional except for navigation. When a widget root is configured it is expected on every selected page.

```toml
nav_selector = "header nav a[href]"
widget_root = ".interactive-widget"
static_fallback = ".widget-static, noscript"
settle = 2.0
```

## Rendered language

Source checks miss labels produced by JavaScript. `sitecheck lang SITE` reads visible `document.body.innerText` after rendering and reports forbidden writing systems by page. Define rules in `sitecheck.toml` before running the command. Match only the relevant language pages with a URL glob. Allowed phrases are removed literally from each rendered line before matching. Available scripts are `cjk`, `han`, `kana`, `hangul`, `cyrillic`, `arabic`, and `greek`. CJK includes Han, kana, and Hangul. Use `--settle` for delayed content and `--include` or `--exclude` to scope pages.

```toml
lang_rules = [{ page = "*/en/*", scripts = ["cjk"], allow = ["漢字 example"] }]
```

## Interaction walk

An idle page cannot prove that buttons, answer panels, and other interactions work. `sitecheck walk SITE --script examples/walk.json` runs a declarative JSON journey for each URL or page id listed in `urls`. The optional `pages` map defines ids. Relative URLs resolve against SITE, which may be a served directory or a URL. Absolute URLs work without SITE. Each target opens automatically before the steps; `{"open": "$target"}` reopens it. Supported steps are `open` with a URL or id, `click_text` with exact visible control text, `fill` with `selector` and `value`, `wait` with seconds or `{"text": "Ready", "timeout": 10}`, `assert_text` with a visible text fragment, and `screenshot` with a filename. Text checks use rendered `innerText`. A failed step stops that target and reports its step number while other targets continue. Screenshots go into the normal report output. The example at `examples/walk.json` works against the demo site.

All three commands write JSON, Markdown, and HTML reports and exit nonzero on unsuppressed findings. Browser checks require Chrome. Run offline unit tests with `pytest`.

## Limitations

Screenshots use a viewport of at most 8000 pixels and clip to page bounds. Browser walks do not scroll or follow anchors automatically. Link checks inspect HTML returned by the server, so links created only by JavaScript are outside their scope. Shell examples execute with the current user's permissions in the configured working directory.
