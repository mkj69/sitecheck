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
```

The demo includes a broken link and a wide panel. Reports go to `sitecheck-out/report.json`, `report.md`, and `report.html`. Screenshots and contact sheets appear there when requested. `smoke`, `doc-commands`, and `all` return a nonzero status when errors are found.

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
| `theme_mode` | `media`, `attribute`, or `query` | `media` |
| `theme_attribute`, `theme_query` | Attribute or query key | `data-theme`, `theme` |
| `docs` | Markdown files or directories for `all` and `doc-commands` | `docs` |
| `doc_languages` | Fence languages to execute | `bash`, `sh`, `shell` |
| `doc_skip_marker` | Comment text that skips a block | `sitecheck: skip` |
| `doc_cwd`, `doc_timeout` | Command working directory and seconds per block | `.`, `30` |
| `doc_env` | Environment values passed to each command | empty |
| `allow` | Finding rules with `kind`, optional `page` and `message` globs | empty |

Each documentation block runs in a fresh Bash process with `-e` and `pipefail`. Use `--env NAME=VALUE` for a command environment variable. Failed blocks report their file, line, exit status, and output tail. The skip marker may appear anywhere inside a block.

An allow rule can suppress a known finding:

```toml
allow = [{ kind = "broken_link", page = "*/draft.html" }]
```

## Limitations

Screenshots use a tall viewport and clip to page bounds. Sitecheck never scrolls or navigates to anchors in Chrome. Pages taller than 16000 pixels produce a browser error. Pages that depend on scrolling or complex user interaction may need separate tests. Link checks inspect HTML returned by the server, so links created only by JavaScript are outside their scope. Shell examples execute with the current user's permissions in the configured working directory.
