# Graph UI REV_V2 Validation

Date: 2026-03-29

## Screenshot Comparison

- Baseline screenshot: `.scratch/projects/66-graph-ui-refactor/ui-playwright-20260329-133345-256.png`
- Updated screenshot: `.scratch/projects/66-graph-ui-refactor/ui-playwright-20260329-134936-689871.png`
- Pixel diff ratio: `0.12592122395833333` (`116049 / 921600` changed pixels)
- Capture context: acceptance-style temporary runtime project, Playwright Chromium, viewport `1280x720`.

## Acceptance Check Status

- Command: `devenv shell -- pytest tests/acceptance/test_web_graph_ui.py -q -rs`
- Result: `4 passed` (with 2 known websocket deprecation warnings).

## Graph-Focused Notes

- The updated graph view applies density expansion, label-box-aware collision separation, hub crossing redistribution, and top-left overlay exclusion.
- Edge labels are now suppressed by default in full mode and shown conditionally for focus/selection/hover via Sigma reducers and events.
