---
name: sitecheck
description: Check and screenshot static site changes, including from coding agents unable to run Chrome or listen on localhost.
---

# Sitecheck

## Screenshot service

When an agent cannot start Chrome or bind a loopback socket, ask a host-side operator to run `sitecheck serve-shots` outside the sandbox, sharing its request/output directories. Write an atomic `<unique-id>.json` request, poll for `<output>/<id>/DONE` or `ERROR`, then inspect `report.json` and the numbered PNGs. See the README's request schema and protocol; never assume `DONE` means there is no overflow or JavaScript exception. Use raw Python strings for embedded JS, an OS-assigned free port, and allow-list legitimate error-looking text when scanning page copy.

## Animation strips

Use `sitecheck strip URL --region '.panel' --aria-label 'Next step' --delays 0.05,0.25,0.45,0.7,1.1 --repeat 2 --output motion.png --timeout 150` to review UI animations and step-by-step viewers as stills. Choose one of `--click-selector`, `--button-text`, or `--aria-label`. The Python API is `sitecheck.strip.capture_strip(browser, url, output, region=..., button_text=..., delays=..., repeat=...)` with an entered `Chrome` browser. It enlarges the viewport, centers the region, and captures a fixed clip per click, with one row per repeat. Use generous timeouts: timings jitter under load and frames cannot prove smoothness between samples.

## Lessons

- Sticky headers can hide clip regions; enlarge the viewport and center the region before capturing.
- Sites defaulting to light may ignore `prefers-color-scheme`. Use `--theme-mode click --theme-selector SELECTOR --theme-attribute data-theme --theme-value dark` to click a palette toggle until its attribute matches.
