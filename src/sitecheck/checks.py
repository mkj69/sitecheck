"""Convert page data and layout boxes into findings."""

from __future__ import annotations

from .discovery import PageParser, check_links


def overflow_findings(layout: dict, viewport: int, tolerance: float = 1) -> list[dict]:
    """Return one page overflow finding, with visible unclipped culprits."""
    scroll_width = float(layout["scrollWidth"])
    client_width = float(layout["clientWidth"])
    if scroll_width <= client_width:
        return []

    culprits = []
    for box in layout["boxes"]:
        left = float(box.get("left", 0))
        right = float(box.get("right", left + float(box.get("width", 0))))
        if (box.get("display") == "none" or box.get("visibility") == "hidden"
                or box.get("position") == "fixed"
                or float(box.get("width", right - left)) <= 0
                or float(box.get("height", 0)) <= 0
                or right <= 0 or left >= viewport):
            continue
        if left >= -tolerance and right <= viewport + tolerance:
            continue
        if any(ancestor.get("overflowX") in ("auto", "scroll", "hidden", "clip")
               and float(ancestor["left"]) >= 0
               and float(ancestor["right"]) <= viewport
               for ancestor in box.get("ancestors", [])):
            continue
        culprits.append(box.get("selector", "element"))

    count = len(culprits)
    examples = ", ".join(culprits[:5])
    message = f"Document scrolls sideways by {scroll_width - client_width:g}px; {count} culprit elements"
    if examples:
        message += f": {examples}"
    return [{"kind": "overflow", "count": count, "message": message}]


def static_findings(url: str, page: PageParser, cache: dict | None = None) -> list[dict]:
    findings = check_links(url, page, cache)
    if not page.title.strip():
        findings.append({"kind": "missing_title", "message": "Page has no title"})
    findings.extend({"kind": "missing_alt", "message": f"Image {src} has no alt attribute"}
                    for src in page.images_without_alt)
    return findings


# Return page width and box data so Python can filter and group findings.
LAYOUT_JS = """(() => {
  const root = document.documentElement;
  const boxes = [...document.querySelectorAll('*')].map((el, index) => {
    const r = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    const ancestors = [];
    for (let parent = el.parentElement; parent; parent = parent.parentElement) {
      const parentStyle = getComputedStyle(parent);
      if (['auto', 'scroll', 'hidden', 'clip'].includes(parentStyle.overflowX)) {
        const bounds = parent.getBoundingClientRect();
        ancestors.push({overflowX: parentStyle.overflowX, left: bounds.left, right: bounds.right});
      }
    }
    return {selector: el.id ? '#' + el.id : el.tagName.toLowerCase() + ':nth(' + index + ')',
      left: r.left, right: r.right, width: r.width, height: r.height,
      display: style.display, visibility: style.visibility, position: style.position, ancestors};
  });
  return {scrollWidth: root.scrollWidth, clientWidth: root.clientWidth, boxes};
})()"""
