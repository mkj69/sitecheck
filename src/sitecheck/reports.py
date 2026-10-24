"""Write machine readable and browsable reports."""

from __future__ import annotations

from html import escape
import json
from pathlib import Path

from PIL import Image, ImageDraw


def contact_sheet(paths: list[Path], output: Path, columns: int = 3, thumb_width: int = 320) -> Path:
    if not paths or columns < 1 or thumb_width < 1:
        raise ValueError("A sheet needs images and positive dimensions")
    tiles = []
    for path in paths:
        with Image.open(path) as source:
            tile = source.convert("RGB")
        tile.thumbnail((thumb_width, thumb_width * 3))
        tiles.append((path, tile))
    cell_height = max(image.height for _, image in tiles) + 28
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * thumb_width, rows * cell_height), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (path, tile) in enumerate(tiles):
        x, y = (index % columns) * thumb_width, (index // columns) * cell_height
        draw.text((x + 5, y + 7), path.name[:45], fill="black")
        sheet.paste(tile, (x, y + 28))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    return output


def allowed(finding: dict, rules: list[dict]) -> bool:
    from fnmatch import fnmatch
    return any(fnmatch(finding.get("kind", ""), rule.get("kind", ""))
               and fnmatch(finding.get("page", ""), rule.get("page", "*"))
               and fnmatch(finding.get("message", ""), rule.get("message", "*")) for rule in rules)


def write_reports(output: Path, findings: list[dict], shots: list[dict] | None = None,
                  rules: list[dict] | None = None, commands: list[dict] | None = None) -> int:
    output.mkdir(parents=True, exist_ok=True)
    rules = rules or []
    marked = [{**item, "allowed": allowed(item, rules)} for item in findings]
    failures = [item for item in marked if not item["allowed"]]
    report = {"findings": marked, "screenshots": shots or [], "commands": commands or [],
              "error_count": len(failures)}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = ["# Sitecheck report", "", f"Errors: {report['error_count']}", "", "## Findings", ""]
    lines += [f"- {'Allowed' if item['allowed'] else 'Error'}: {item.get('page', '')} {item['kind']}: {item['message']}" for item in marked]
    if commands:
        lines += ["", "## Documentation commands", ""]
        lines += [f"- {item['file']}:{item['line']}: {'passed' if item['returncode'] == 0 else 'failed'} {item['output_tail']}" for item in commands]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    cards = []
    for shot in shots or []:
        path = escape(shot["path"], quote=True)
        cards.append(f'<figure><a href="{path}"><img src="{path}" loading="lazy" alt="Screenshot of {escape(shot["page"], quote=True)}"></a><figcaption>{escape(shot["page"])} at {shot["width"]}px, {escape(shot["theme"])}</figcaption></figure>')
    rows = "".join(f'<li class="{"allowed" if item["allowed"] else "error"}"><strong>{escape(item["kind"])}</strong> {escape(item.get("page", ""))}: {escape(item["message"])}</li>' for item in marked)
    html = f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>Sitecheck report</title>
<style>body{{font:16px system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#222}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem}}figure{{margin:0}}img{{max-width:100%;border:1px solid #ccc}}li{{margin:.5rem 0;overflow-wrap:anywhere}}.error{{color:#a00}}.allowed{{color:#666}}</style>
<h1>Sitecheck report</h1><p>{report['error_count']} errors</p><h2>Findings</h2><ul>{rows}</ul><h2>Screenshots</h2><div class="grid">{''.join(cards)}</div></html>'''
    (output / "report.html").write_text(html, encoding="utf-8")
    return report["error_count"]
