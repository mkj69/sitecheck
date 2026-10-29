# sitecheck

Sitecheck finds pages, checks common static site problems, captures screenshots, and runs shell examples from Markdown. It is useful before publishing a site or reviewing a redesign.

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
sitecheck strip https://example.org/viewer --region '.panel' --button-text 'Next step' --output strip.png
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

## Screenshot service for sandboxed agents

Run `sitecheck serve-shots` **outside** the agent's sandbox, where Chrome and loopback sockets are available. The service watches a shared request directory, builds each requested worktree, serves its generated files on an OS-assigned free loopback port, captures full-page PNGs, and writes a JSON report. Leave it running while the agent edits the site. For example:

```sh
sitecheck serve-shots --requests /shared/shot-requests --output /shared/shot-output \
  --build-command 'npm run build' --site-dir dist
```

`--requests` defaults to `shot-requests`, `--output` to `shot-output`, and `--site-dir` to `site` relative to each worktree. The build command runs in the requested worktree using the service user's environment; it is required for requests with `"build": true`. `"build": false` uses an already-built directory. The service user must trust worktrees and requests: the build command executes there with that user's permissions. `--build-timeout` defaults to 300 seconds, `--timeout` to **150 seconds per Chrome call** (long captures can be slow on a loaded machine), `--settle` to 1.5 seconds after navigation and each click, and `--poll` to 2 seconds. `--chrome` or `SITECHECK_CHROME` selects Chrome.

Theme switching defaults to `--theme-mode media`, which emulates `prefers-color-scheme`. For sites controlled by an HTML attribute, use `--theme-mode attribute --theme-attribute data-theme`. For a site toggle, use `--theme-mode click --theme-selector 'button.theme-toggle' --theme-attribute data-theme`: the service loads with light media, checks the attribute on the root or body, and clicks the selector until it matches the requested theme (at most three times). The expected attribute values default to `light` and `dark`; override them with `--theme-light-value` and `--theme-dark-value` (for example, `default` and `slate`).

### Request JSON

Write one UTF-8 JSON file named `<unique-id>.json` in the request directory. IDs must start with an ASCII letter or digit, contain only ASCII letters, digits, `_` or `-`, and be at most 80 characters long. The object has these fields (unknown fields are rejected):

| Field | Type | Meaning |
| --- | --- | --- |
| `worktree` | string, required | Existing absolute path to the site worktree, visible to the service |
| `build` | boolean, optional | Run the configured build command before serving; default `true` |
| `shots` | nonempty array, required | Ordered page captures, one PNG per entry |

Each `shots` entry accepts `path` (local URL path, optionally with a query; default `/`), `width` (positive integer pixels; default `1440`), `theme` (`light` or `dark`; default `light`), `click` (array of exact visible button/tab labels, clicked in order), and `max_height` (positive integer pixels; default `6000`). Unknown fields, external URLs, and fragments are rejected. A missing button or invalid request produces `ERROR` rather than a misleading screenshot.

```json
{
  "worktree": "/shared/worktrees/my-site",
  "build": true,
  "shots": [
    {"path": "/", "width": 390, "theme": "light"},
    {"path": "/guide/?view=grid", "width": 1440, "theme": "dark",
     "click": ["Examples", "Next"], "max_height": 12000}
  ]
}
```

### Agent-side protocol

1. Generate a fresh unique ID for each attempt (for example, a UUID hex string). Write JSON to a temporary file **in the request directory**, then atomically rename it to `<id>.json` so the watcher never reads a partial request.
2. Poll `<output>/<id>/DONE` or `<output>/<id>/ERROR`. The service processes requests sequentially and ignores IDs that already have either marker; don't reuse an ID. If `ERROR` appears, read it for the traceback (and `build.log` for failed builds).
3. After `DONE`, read `<output>/<id>/report.json` (an array in shot order) and `<output>/<id>/0.png`, `1.png`, etc. Each entry contains the request `shot`, relative `png` filename, `scrollWidth`, `viewport`, `count` of elements whose right edge extends beyond the viewport outside a horizontal scroll box, up to 25 `overflowing` examples, `exceptions` from Chrome, and `capture` height/truncation metadata. A page can have a nonzero overflow count or JS exceptions and still finish with `DONE`; inspect the report.

Keep in-page JavaScript embedded in Python as **raw strings**: a `"\n"` escape inside a normal Python string may become a newline inside a JavaScript string literal, causing every evaluation to fail with a bare `Uncaught`. Bind the HTTP server to port `0` so the OS chooses an actually free port; reusing an occupied port may silently serve an old site and cause misleading 404s. When scanning rendered text for error words such as `undefined`, allow-list legitimate content that uses those words; prefer structured JS exceptions for actual runtime errors.

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

## Animation strips

Use `sitecheck strip` to review UI animations and step-by-step viewers from still frames. It opens one page, enlarges the viewport and centers a CSS-selected region away from sticky headers, then clicks a control and captures the **same page-coordinate clip** at each delay. Columns show successive moments after a click; each `--repeat` is another consecutive click in a new row (the page is not reloaded). Output is a single PNG, not a report. For example:

```sh
sitecheck strip https://example.org/viewer --region '.viewer-panel' \
  --aria-label 'Next step' --delays 0.05,0.25,0.45,0.7,1.1 \
  --repeat 2 --width 1440 --output motion.png --timeout 150
```

Choose exactly one of `--click-selector` (CSS), `--button-text` (exact visible button text), or `--aria-label` (exact aria-label attribute). For a local directory, pass `--page /path/` to select the page; a URL opens directly. `--theme dark` uses `prefers-color-scheme` media emulation by default. If the site defaults to light regardless of media settings, use `--theme-mode click --theme-selector '.palette-toggle' --theme-attribute data-theme --theme-value dark` to click until the HTML or body attribute matches the requested value (at most three clicks). Use `--settle` to wait before choosing the clip. The default delays are `0.05,0.25,0.45,0.7,1.1` seconds; set `--repeat` for sequential transitions. In Python, use `from sitecheck.strip import capture_strip` with an entered `Chrome` browser and the same keyword arguments; it returns the PNG dimensions.

Capture and scheduling introduce timing jitter under load. Use generous `--timeout` values and treat the stated delays as approximate. The clip stays fixed even when the target or page moves, and a CSS region must fit within the viewport; scroll or sticky overlays can still affect what appears in the image.

### Lessons

- Sticky headers can hide clip regions; make the viewport taller and center the target before capturing.
- A site whose default theme is light may ignore `prefers-color-scheme`; click its palette toggle and verify the resulting attribute instead.

## Limitations

Screenshots use a viewport of at most 8000 pixels and clip to page bounds. Browser walks do not scroll or follow anchors automatically. Link checks inspect HTML returned by the server, so links created only by JavaScript are outside their scope. Shell examples execute with the current user's permissions in the configured working directory.
