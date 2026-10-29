"""Capture successive frames of a clicked UI control as a PNG strip."""

from __future__ import annotations

import base64
from io import BytesIO
import json
import math
from pathlib import Path
import time

from PIL import Image

from .browser import BrowserError
from .shot_service import switch_theme


DEFAULT_DELAYS = (0.05, 0.25, 0.45, 0.7, 1.1)


def capture_strip(browser, url: str, output: Path, *, region: str,
                  click_selector: str | None = None, button_text: str | None = None,
                  aria_label: str | None = None, delays=DEFAULT_DELAYS,
                  repeat: int = 1, width: int = 1440, theme: str = "light",
                  theme_mode: str = "media", theme_selector: str | None = None,
                  theme_attribute: str = "data-theme", theme_value: str | None = None,
                  settle: float = 1.5) -> tuple[int, int]:
    """Open a page, click once per row, and save a fixed-region frame grid.

    The browser is an entered Chrome instance (or a compatible fake). Delays are
    seconds after each click; rows are consecutive interactions, not page resets.
    Returns the resulting image size in pixels.
    """
    actions = (click_selector, button_text, aria_label)
    if sum(action is not None for action in actions) != 1 or any(action == "" for action in actions if action is not None):
        raise ValueError("Provide exactly one nonempty click selector, button text, or aria-label")
    if not region:
        raise ValueError("Region selector is required")
    if type(width) is not int or width < 1 or type(repeat) is not int or repeat < 1:
        raise ValueError("Width and repeat must be positive integers")
    delays = tuple(delays)
    if not delays or any(not isinstance(delay, (int, float)) or not math.isfinite(delay) or delay < 0
                         for delay in delays) or any(later < earlier for earlier, later in zip(delays, delays[1:])):
        raise ValueError("Delays must be nonempty, finite, nonnegative, and ordered")
    if not isinstance(settle, (int, float)) or not math.isfinite(settle) or settle < 0:
        raise ValueError("Settle must be finite and nonnegative")
    if theme not in ("light", "dark") or theme_mode not in ("media", "click"):
        raise ValueError("Theme must be light or dark; theme mode must be media or click")
    if theme_mode == "click" and (not theme_selector or not theme_attribute or not (theme_value or theme)):
        raise ValueError("Click theme mode requires a toggle selector and theme attribute")

    browser.open(url, width, "light" if theme_mode == "click" else theme)
    if theme_mode == "click":
        switch_theme(browser, theme, theme_selector, theme_attribute, {theme: theme_value or theme})
    browser.pump(settle)
    selector_json = json.dumps(region)
    bounds = browser.evaluate(f"""(() => {{
      const element = document.querySelector({selector_json});
      if (!element) return null;
      const rect = element.getBoundingClientRect();
      return {{width: rect.width, height: rect.height}};
    }})()""")
    if not bounds or bounds["width"] <= 0 or bounds["height"] <= 0:
        raise BrowserError(f"Region not found or empty: {region}")
    if bounds["width"] > width or bounds["height"] > 7600:
        raise BrowserError("Region does not fit inside the capture viewport")
    height = max(900, math.ceil(bounds["height"]) + 400)
    browser.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height,
                 "deviceScaleFactor": 1, "mobile": width < 600})
    browser.pump(0.2)
    bounds = browser.evaluate(f"""(() => {{
      const element = document.querySelector({selector_json});
      if (!element) return null;
      element.scrollIntoView({{block: 'center', inline: 'nearest'}});
      const rect = element.getBoundingClientRect();
      return {{x: rect.left + scrollX, y: rect.top + scrollY,
               width: rect.width, height: rect.height,
               top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right}};
    }})()""")
    if not bounds or bounds["width"] <= 0 or bounds["height"] <= 0:
        raise BrowserError(f"Region not found or empty after resize: {region}")
    if (bounds["top"] < 0 or bounds["bottom"] > height or bounds["left"] < 0 or bounds["right"] > width
            or bounds["height"] > height):
        raise BrowserError("Region is outside the viewport; adjust the page layout or viewport width")
    clip = {"x": bounds["x"], "y": bounds["y"], "width": bounds["width"],
            "height": bounds["height"], "scale": 1}
    browser.pump(0.2)
    frames = []
    for _ in range(repeat):
        if click_selector is not None:
            clicked = browser.evaluate(f"""(() => {{
              const element = document.querySelector({json.dumps(click_selector)});
              if (!element || !element.getClientRects().length || element.disabled) return false;
              element.click(); return true;
            }})()""")
        elif aria_label is not None:
            clicked = browser.evaluate(f"""(() => {{
              const element = [...document.querySelectorAll('[aria-label]')]
                .find(item => item.getAttribute('aria-label') === {json.dumps(aria_label)} &&
                  item.getClientRects().length && !item.disabled);
              if (!element) return false;
              element.click(); return true;
            }})()""")
        else:
            clicked = browser.click_text(button_text, "button, [role=button]")
        started = time.monotonic()
        if not clicked:
            raise BrowserError("Click control not found, visible, or enabled")
        for delay in delays:
            while (remaining := started + delay - time.monotonic()) > 0:
                browser.pump(min(remaining, 0.02))
            result = browser.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True,
                                  "clip": clip})
            with Image.open(BytesIO(base64.b64decode(result["data"]))) as frame:
                frames.append(frame.convert("RGB"))
    frame_width, frame_height = frames[0].size
    if any(frame.size != (frame_width, frame_height) for frame in frames):
        raise BrowserError("Region capture changed size during animation")
    sheet = Image.new("RGB", (frame_width * len(delays), frame_height * repeat))
    for index, frame in enumerate(frames):
        sheet.paste(frame, ((index % len(delays)) * frame_width,
                            (index // len(delays)) * frame_height))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, format="PNG")
    return sheet.size
