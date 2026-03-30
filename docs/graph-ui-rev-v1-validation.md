# Graph UI REV_V1 Validation

Date: 2026-03-29

## Screenshot Comparison

- Baseline screenshot: `.scratch/projects/66-graph-ui-refactor/ui-playwright-20260329-130146-010.png`
- Updated screenshot: `.scratch/projects/66-graph-ui-refactor/ui-playwright-20260329-133008-533433.png`
- Pixel diff ratio: `0.29379774305555556` (`270764 / 921600` changed pixels)
- Capture context: acceptance-style temporary runtime project, Playwright Chromium, viewport `1280x720`.

## Acceptance Check Status

- Command: `devenv shell -- pytest tests/acceptance/test_web_graph_ui.py -q -rs`
- Result: `4 passed` (with 2 known deprecation warnings from websocket stack).

## Notes

- The updated image reflects substantial graph readability/layout and sidebar interaction changes from `REV_V1` implementation.
- Diff ratio is intentionally non-trivial because the update includes spacing, label rendering, edge thinning, and sidebar structure changes.
