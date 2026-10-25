import json
from pathlib import Path

from PIL import Image

from sitecheck.docs import collect, extract, run
from sitecheck.reports import contact_sheet, write_reports


def test_extract_and_run(tmp_path):
    md = tmp_path / "guide.md"
    md.write_text('Intro\n```bash\nprintf "hello\\n"\n```\n\n```sh\n# sitecheck: skip\nexit 1\n```\n\n```shell\necho bad >&2\nexit 3\n```\n')
    blocks = collect([tmp_path])
    assert [block.line for block in blocks] == [2, 11]
    results = run(blocks, tmp_path)
    assert [item["returncode"] for item in results] == [0, 3]
    assert results[1]["output_tail"] == "bad"
    assert extract(md.read_text(), md, ["bash"]) == blocks[:1]


def test_contact_sheet_and_reports(tmp_path):
    paths = []
    for index in range(3):
        path = tmp_path / f"image{index}.png"
        Image.new("RGB", (100, 80), (index * 40, 0, 0)).save(path)
        paths.append(path)
    sheet = contact_sheet(paths, tmp_path / "sheet.png", columns=2, thumb_width=100)
    with Image.open(sheet) as image:
        assert image.size == (200, 216)
    output = tmp_path / "report"
    count = write_reports(output, [{"kind": "broken_link", "page": "/", "message": "missing"},
                                   {"kind": "overflow", "page": "/", "message": "wide"},
                                   {"kind": "overflow", "page": "/other", "message": "wide"}],
                          rules=[{"kind": "broken_link", "page": "/"}])
    assert count == 2
    report = json.loads((output / "report.json").read_text())
    assert report["findings"][0]["allowed"]
    assert report["error_counts_by_kind"] == {"overflow": 2}
    assert "2 errors (overflow: 2)" in (output / "report.html").read_text()
    assert "Errors: 2 (overflow: 2)" in (output / "report.md").read_text()
