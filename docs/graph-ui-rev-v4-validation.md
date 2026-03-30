# Graph UI REV_V4 Validation

Date: 2026-03-29

## Screenshot Comparison

- Baseline screenshot: `.scratch/projects/66-graph-ui-refactor/ui-playwright-20260329-155744-732.png`
- Updated screenshot: `.scratch/projects/66-graph-ui-refactor/ui-playwright-20260329-rev-v4-post.png`
- Pixel diff ratio: `0.10420572916666666` (`96036 / 921600` changed pixels)
- Capture context: acceptance-style temporary runtime project, Playwright Chromium, viewport `1280x720`.

## Acceptance Check Status

- Command: `devenv shell -- pytest tests/acceptance/test_web_graph_ui.py -q -rs`
- Result: `4 passed` (with 2 known websocket deprecation warnings).

## Graph-Focused Notes

- REV_V4 maximizes spread and safe-area occupancy while preserving interaction stability.
- Sigma.js built-in functionality remains the primary control surface:
  - `labelDensity` and `labelGridCellSize` for label culling,
  - `nodeReducer` / `edgeReducer` for center suppression and peripheral identity,
  - camera ratio defaults and bounds for first-paint zoomed-out framing.
- Layout engine reinforcement adds near-zero overlap enforcement, crossing deflection, and occupancy-sector balancing to reduce dense center knots.
