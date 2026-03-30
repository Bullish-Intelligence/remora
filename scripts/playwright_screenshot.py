#!/usr/bin/env python3
"""Capture a screenshot of a URL using Playwright Chromium."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import Page, sync_playwright


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Target URL to capture.")
    parser.add_argument(
        "--out",
        required=True,
        help="Output PNG path.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=1600,
        help="Viewport width in pixels (default: 1600).",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=900,
        help="Viewport height in pixels (default: 900).",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        help="Navigation/selector timeout in milliseconds (default: 30000).",
    )
    parser.add_argument(
        "--wait-until",
        choices=["load", "domcontentloaded", "networkidle", "commit"],
        default="domcontentloaded",
        help="Playwright wait strategy for page.goto (default: domcontentloaded).",
    )
    parser.add_argument(
        "--selector",
        default=None,
        help="Optional selector to wait for before screenshot.",
    )
    parser.add_argument(
        "--full-page",
        action="store_true",
        help="Capture full page instead of viewport only.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run Chromium headed (default: headless).",
    )
    parser.add_argument(
        "--compare-to",
        default=None,
        help="Optional baseline PNG path for diff comparison.",
    )
    parser.add_argument(
        "--min-diff-ratio",
        type=float,
        default=0.0,
        help=(
            "Minimum changed-pixel ratio required when --compare-to is used. "
            "If actual ratio is lower, command exits non-zero."
        ),
    )
    parser.add_argument(
        "--mask-selector",
        action="append",
        default=[],
        help="CSS selector to mask in both screenshots before diffing. Repeatable.",
    )
    parser.add_argument(
        "--no-mask-default-dynamic",
        action="store_true",
        help="Disable default dynamic masks (#events, #timeline-container) during comparison.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON output.",
    )
    return parser.parse_args()


def _collect_mask_rects(page: Page, selectors: list[str]) -> list[dict[str, int]]:
    if not selectors:
        return []
    rects = page.evaluate(
        """
        (selectors) => {
          const out = [];
          for (const selector of selectors) {
            const elements = Array.from(document.querySelectorAll(selector));
            for (const element of elements) {
              if (!element) continue;
              const style = window.getComputedStyle(element);
              if (style.display === "none" || style.visibility === "hidden") continue;
              const rect = element.getBoundingClientRect();
              if (!rect || rect.width <= 0 || rect.height <= 0) continue;
              out.push({
                selector,
                left: rect.left,
                top: rect.top,
                right: rect.right,
                bottom: rect.bottom,
              });
            }
          }
          return out;
        }
        """,
        selectors,
    )
    normalized: list[dict[str, int]] = []
    for rect in rects or []:
        left = int(round(float(rect.get("left", 0))))
        top = int(round(float(rect.get("top", 0))))
        right = int(round(float(rect.get("right", left))))
        bottom = int(round(float(rect.get("bottom", top))))
        if right <= left or bottom <= top:
            continue
        normalized.append(
            {
                "selector": str(rect.get("selector", "")),
                "left": left,
                "top": top,
                "right": right,
                "bottom": bottom,
            }
        )
    return normalized


def _compute_masked_diff(current_path: Path, baseline_path: Path, mask_rects: list[dict[str, int]]) -> tuple[int, int, float]:
    try:
        from PIL import Image, ImageChops, ImageDraw
    except ImportError as exc:  # pragma: no cover - dependency dependent
        raise RuntimeError("Pillow is required for --compare-to diffing") from exc

    with Image.open(current_path).convert("RGBA") as current_img, Image.open(baseline_path).convert("RGBA") as baseline_img:
        if current_img.size != baseline_img.size:
            raise ValueError(
                f"Image sizes differ: current={current_img.size} baseline={baseline_img.size}"
            )

        current_work = current_img.copy()
        baseline_work = baseline_img.copy()
        if mask_rects:
            draw_current = ImageDraw.Draw(current_work)
            draw_baseline = ImageDraw.Draw(baseline_work)
            for rect in mask_rects:
                draw_rect = [rect["left"], rect["top"], rect["right"], rect["bottom"]]
                draw_current.rectangle(draw_rect, fill=(0, 0, 0, 255))
                draw_baseline.rectangle(draw_rect, fill=(0, 0, 0, 255))

        diff_img = ImageChops.difference(current_work, baseline_work)
        width, height = current_work.size
        total_pixels = max(1, width * height)
        raw = diff_img.tobytes()
        changed_pixels = 0
        for index in range(0, len(raw), 4):
            if raw[index] or raw[index + 1] or raw[index + 2] or raw[index + 3]:
                changed_pixels += 1
        diff_ratio = changed_pixels / total_pixels
        return changed_pixels, total_pixels, diff_ratio


def main() -> int:
    args = _parse_args()
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    default_dynamic_selectors = ["#events", "#timeline-container"]
    compare_path: Path | None = None
    if args.compare_to:
        compare_path = Path(args.compare_to).expanduser().resolve()
        if not compare_path.exists():
            print(f"Baseline screenshot not found: {compare_path}")
            return 4

    mask_selectors = list(args.mask_selector)
    if compare_path and not args.no_mask_default_dynamic:
        for selector in default_dynamic_selectors:
            if selector not in mask_selectors:
                mask_selectors.append(selector)

    mask_rects: list[dict[str, int]] = []

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=not args.headed)
            context = browser.new_context(
                viewport={"width": args.width, "height": args.height}
            )
            page = context.new_page()
            page.goto(args.url, wait_until=args.wait_until, timeout=args.timeout_ms)
            if args.selector:
                page.wait_for_selector(args.selector, timeout=args.timeout_ms)
            if compare_path:
                mask_rects = _collect_mask_rects(page, mask_selectors)
            page.screenshot(path=str(out_path), full_page=args.full_page)
            context.close()
            browser.close()
    except PlaywrightTimeoutError as exc:
        print(f"Timed out while capturing screenshot: {exc}")
        return 2
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"Screenshot capture failed: {exc}")
        return 1

    payload: dict[str, object] = {
        "ok": True,
        "url": args.url,
        "path": str(out_path),
        "bytes": out_path.stat().st_size,
    }

    if compare_path:
        try:
            changed_pixels, total_pixels, diff_ratio = _compute_masked_diff(
                out_path,
                compare_path,
                mask_rects,
            )
        except Exception as exc:  # pragma: no cover - dependency/environment dependent
            print(f"Screenshot comparison failed: {exc}")
            return 5

        payload.update(
            {
                "compared_to": str(compare_path),
                "changed_pixels": changed_pixels,
                "total_pixels": total_pixels,
                "diff_ratio": diff_ratio,
                "min_diff_ratio": args.min_diff_ratio,
                "mask_selectors": mask_selectors,
                "mask_rect_count": len(mask_rects),
            }
        )
        if args.min_diff_ratio > 0 and diff_ratio < args.min_diff_ratio:
            payload["ok"] = False
            payload["reason"] = "diff_ratio_below_threshold"
            if args.json:
                print(json.dumps(payload))
            else:
                print(
                    "Diff ratio below threshold: "
                    f"actual={diff_ratio:.6f} threshold={args.min_diff_ratio:.6f}"
                )
            return 3

    if args.json:
        print(json.dumps(payload))
    else:
        base = f"Saved screenshot: {out_path} ({payload['bytes']} bytes)"
        if compare_path:
            base += (
                f" | diff_ratio={payload['diff_ratio']:.6f}"
                f" changed={payload['changed_pixels']}/{payload['total_pixels']}"
                f" masks={payload['mask_rect_count']}"
            )
        print(base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
