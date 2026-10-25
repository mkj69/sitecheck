import pytest

from sitecheck.checks import overflow_findings


def box(**changes):
    return {"selector": "#wide", "left": 0, "right": 420, "width": 420,
            "height": 20, "display": "block", "visibility": "visible",
            "position": "static", "ancestors": [], **changes}


def layout(boxes, scroll_width=420, client_width=390):
    return {"boxes": boxes, "scrollWidth": scroll_width, "clientWidth": client_width}


def test_overflow_requires_document_width_and_groups_culprits():
    assert overflow_findings(layout([box()], scroll_width=390), 390) == []
    boxes = [box(selector=f"#item-{index}") for index in range(7)]
    findings = overflow_findings(layout(boxes), 390)
    assert len(findings) == 1
    assert findings[0]["kind"] == "overflow"
    assert findings[0]["count"] == 7
    assert "30px" in findings[0]["message"]
    assert "#item-4" in findings[0]["message"]
    assert "#item-5" not in findings[0]["message"]


@pytest.mark.parametrize("overflow", ["auto", "scroll", "hidden", "clip"])
def test_clipped_ancestor_inside_viewport_is_not_culprit(overflow):
    ancestor = {"overflowX": overflow, "left": 0, "right": 390}
    finding = overflow_findings(layout([box(ancestors=[ancestor])]), 390)[0]
    assert finding["count"] == 0
    assert "0 culprit elements" in finding["message"]


def test_unclipped_or_wide_ancestor_does_not_hide_culprit():
    boxes = [box(ancestors=[{"overflowX": "visible", "left": 0, "right": 390}]),
             box(ancestors=[{"overflowX": "auto", "left": 0, "right": 430}])]
    assert overflow_findings(layout(boxes), 390)[0]["count"] == 2


@pytest.mark.parametrize("changes", [
    {"position": "fixed"},
    {"visibility": "hidden"},
    {"display": "none"},
    {"width": 0},
    {"height": 0},
    {"left": -430, "right": -10},
    {"left": 390, "right": 810},
])
def test_non_culprit_boxes(changes):
    assert overflow_findings(layout([box(**changes)]), 390)[0]["count"] == 0


def test_left_edge_overflow_can_be_culprit():
    assert overflow_findings(layout([box(left=-20, right=100, width=120)]), 390)[0]["count"] == 1
