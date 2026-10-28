---
name: sitecheck
description: Check and screenshot static site changes, including from coding agents unable to run Chrome or listen on localhost.
---

# Sitecheck

## Screenshot service

When an agent cannot start Chrome or bind a loopback socket, ask a host-side operator to run `sitecheck serve-shots` outside the sandbox, sharing its request/output directories. Write an atomic `<unique-id>.json` request, poll for `<output>/<id>/DONE` or `ERROR`, then inspect `report.json` and the numbered PNGs. See the README's request schema and protocol; never assume `DONE` means there is no overflow or JavaScript exception. Use raw Python strings for embedded JS, an OS-assigned free port, and allow-list legitimate error-looking text when scanning page copy.
