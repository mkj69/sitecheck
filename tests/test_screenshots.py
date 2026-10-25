import base64
from io import BytesIO

from PIL import Image

from sitecheck.browser import Chrome


def test_tall_screenshot_uses_clips_and_stitches_without_scrolling(tmp_path):
    browser = Chrome.__new__(Chrome)
    heights = iter([19000, 19000])
    browser.evaluate = lambda _expression: next(heights)
    browser.pump = lambda _seconds: None
    calls = []

    def call(method, params):
        calls.append((method, params))
        if method == "Page.captureScreenshot":
            clip = params["clip"]
            color = (clip["y"] // 8000 * 80, 20, 30)
            tile = Image.new("RGB", (clip["width"], clip["height"]), color)
            data = BytesIO()
            tile.save(data, format="PNG")
            return {"data": base64.b64encode(data.getvalue()).decode()}
        return {}

    browser.call = call
    output = tmp_path / "tall.png"
    result = browser.screenshot(output, 2, max_height=17000)
    assert result == {"height": 17000, "full_height": 19000, "truncated": True}
    assert [params["clip"]["y"] for method, params in calls
            if method == "Page.captureScreenshot"] == [0, 8000, 16000]
    assert [params["clip"]["height"] for method, params in calls
            if method == "Page.captureScreenshot"] == [8000, 8000, 1000]
    assert all(params["captureBeyondViewport"] for method, params in calls
               if method == "Page.captureScreenshot")
    assert not any("scroll" in method.lower() for method, _params in calls)
    with Image.open(output) as image:
        assert image.size == (2, 17000)
        assert [image.getpixel((0, y)) for y in (7999, 8000, 15999, 16000)] == [
            (0, 20, 30), (80, 20, 30), (80, 20, 30), (160, 20, 30)]
