"""Convert page data and layout boxes into findings."""

from __future__ import annotations

from .discovery import PageParser, check_links


def overflow_findings(boxes: list[dict], viewport: int, tolerance: float = 1) -> list[dict]:
    """Report visible boxes extending beyond either viewport edge."""
    findings = []
    for box in boxes:
        left = float(box.get("left", 0))
        right = float(box.get("right", left + float(box.get("width", 0))))
        if box.get("visible", True) and (left < -tolerance or right > viewport + tolerance):
            findings.append({"kind": "overflow", "message": f"{box.get('selector', 'element')} spans {left:g} to {right:g} at {viewport}px"})
    return findings


def static_findings(url: str, page: PageParser, cache: dict | None = None) -> list[dict]:
    findings = check_links(url, page, cache)
    if not page.title.strip():
        findings.append({"kind": "missing_title", "message": "Page has no title"})
    findings.extend({"kind": "missing_alt", "message": f"Image {src} has no alt attribute"}
                    for src in page.images_without_alt)
    return findings


# Return every box so Python can compare it with the requested viewport.
LAYOUT_JS = """(() => {
  return [...document.querySelectorAll('*')].map((el, index) => {
    const r = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    const visible = style.display !== 'none' && style.visibility !== 'hidden' && r.width > 0 && r.height > 0;
    return {selector: el.id ? '#' + el.id : el.tagName.toLowerCase() + ':nth(' + index + ')',
      left: r.left, right: r.right, width: r.width, visible};
  });
})()"""
