# Graph UI REV_V3 Validation

Date: 2026-03-29

## Screenshot Comparison

- Baseline screenshot: `.scratch/projects/66-graph-ui-refactor/ui-playwright-20260329-135330-701.png`
- Updated screenshot: `.scratch/projects/66-graph-ui-refactor/ui-playwright-20260329-141051-750734.png`
- Pixel diff ratio: `0.11581488715277778` (`106735 / 921600` changed pixels)
- Capture context: acceptance-style temporary runtime project, Playwright Chromium, viewport `1280x720`.

## Acceptance Check Status

- Command: `devenv shell -- pytest tests/acceptance/test_web_graph_ui.py -q -rs`
- Result: `4 passed` (with 2 known websocket deprecation warnings).

## Graph-Focused Notes

- REV_V3 increases global spread pressure and dense-cluster spacing floors to push the graph toward maximum legibility.
- Sigma built-in functionality is used heavily for readability control:
  - `labelDensity` and `labelGridCellSize` for label culling,
  - `nodeReducer` / `edgeReducer` for conditional label and edge emphasis,
  - hover events (`enterNode`, `leaveNode`, `enterEdge`, `leaveEdge`) for contextual reveal.
