from __future__ import annotations

import importlib.util
from pathlib import Path

from PIL import Image


_SCRIPT_PATH = Path("scripts/playwright_screenshot.py")
_SPEC = importlib.util.spec_from_file_location("playwright_screenshot", _SCRIPT_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def _write_image(path: Path, *, color: tuple[int, int, int, int]) -> None:
    img = Image.new("RGBA", (10, 10), color=color)
    img.save(path)


def test_compute_masked_diff_reports_changed_pixels(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.png"
    current = tmp_path / "current.png"
    _write_image(baseline, color=(0, 0, 0, 255))
    _write_image(current, color=(0, 0, 0, 255))

    with Image.open(current) as image:
        image.putpixel((2, 2), (255, 255, 255, 255))
        image.save(current)

    changed, total, ratio = _MODULE._compute_masked_diff(current, baseline, [])

    assert changed == 1
    assert total == 100
    assert ratio == 0.01


def test_compute_masked_diff_honors_mask_rectangles(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.png"
    current = tmp_path / "current.png"
    _write_image(baseline, color=(0, 0, 0, 255))
    _write_image(current, color=(0, 0, 0, 255))

    with Image.open(current) as image:
        image.putpixel((2, 2), (255, 255, 255, 255))
        image.save(current)

    mask_rects = [{"left": 0, "top": 0, "right": 5, "bottom": 5}]
    changed, total, ratio = _MODULE._compute_masked_diff(current, baseline, mask_rects)

    assert changed == 0
    assert total == 100
    assert ratio == 0.0
