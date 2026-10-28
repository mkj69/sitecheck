# Changelog

## 0.3.0

Add `serve-shots`, a directory-queued screenshot service for sandboxed coding agents. Build requested worktrees, serve on an OS-assigned loopback port, capture themed pages and interaction states, and report overflow and JavaScript exceptions. Document the request protocol and add offline service tests.

## 0.2.0

Add navigation walks that test direct loads and home page clicks, with configurable widget and fallback checks. Add rendered text script checks with page rules and phrase exemptions. Add declarative JSON interaction walks with screenshots and step findings. Include an example and offline tests.

## 0.1.1

Group document overflow into one finding per page and viewport, with a culprit count that excludes clipped and offscreen elements. Capture tall pages in vertical tiles, stitch the PNG, and report truncation above the configurable maximum height. Show error counts by kind in report summaries.

## 0.1.0

Initial package with page discovery, Chrome pipe screenshots, smoke checks, documentation command runner, contact sheets, and reports.
