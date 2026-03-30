function colorWithAlpha(color, alpha) {
  if (typeof color !== "string" || !color.startsWith("#") || (color.length !== 7 && color.length !== 4)) {
    return color || "#9fb2c8";
  }
  let hex = color;
  if (hex.length === 4) {
    hex = `#${hex[1]}${hex[1]}${hex[2]}${hex[2]}${hex[3]}${hex[3]}`;
  }
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const a = Math.max(0, Math.min(1, alpha));
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

function roundRect(ctx, x, y, w, h, r) {
  const radius = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + w, y, x + w, y + h, radius);
  ctx.arcTo(x + w, y + h, x, y + h, radius);
  ctx.arcTo(x, y + h, x, y, radius);
  ctx.arcTo(x, y, x + w, y, radius);
  ctx.closePath();
}

function overlapArea(a, b) {
  const overlapW = Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x));
  const overlapH = Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));
  return overlapW * overlapH;
}

function compactLabel(text, tier) {
  const label = String(text || "");
  if (tier <= 2) return label;
  if (label.length <= 32) return label;
  return `${label.slice(0, 29)}...`;
}

function smallHash(input) {
  const text = String(input || "");
  let h = 0;
  for (let i = 0; i < text.length; i += 1) {
    h = (h * 31 + text.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

function buildBounds(graph) {
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  let count = 0;
  graph.forEachNode((nodeId, attrs) => {
    if (attrs.hidden || attrs.node_type === "__label__") return;
    const x = Number(attrs.x);
    const y = Number(attrs.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
    count += 1;
  });
  if (count === 0) return null;
  return { minX, minY, maxX, maxY };
}

function defaultCameraState() {
  return { x: 0.5, y: 0.5, ratio: 1.34, angle: 0 };
}

export function createRenderer({ graph, container, nodeLabelHitboxes }) {
  const SigmaCtor = globalThis.Sigma || globalThis.sigma?.Sigma;
  if (typeof SigmaCtor !== "function") {
    throw new Error("Sigma is not available from /static/vendor/sigma.min.js");
  }

  const drawnLabelRects = [];
  const tierLabelCounts = new Map([
    [1, 0],
    [2, 0],
    [3, 0],
    [4, 0],
  ]);
  const quadrantLabelCounts = new Map([
    ["nw", 0],
    ["ne", 0],
    ["sw", 0],
    ["se", 0],
  ]);
  let hoveredNodeId = null;
  let hoveredEdgeId = null;

  function nodeLabelTier(nodeId, data) {
    if (data.is_selected || data.is_pinned || (hoveredNodeId && hoveredNodeId === nodeId)) return 1;
    if (data.is_focus_neighbor) return 2;
    const degree = Number(graph.degree?.(nodeId) || 0);
    if (degree >= 5) return 3;
    return 4;
  }

  function quadrantForRect(rect, dims) {
    const cx = rect.x + rect.width / 2;
    const cy = rect.y + rect.height / 2;
    const east = cx >= dims.width / 2;
    const south = cy >= dims.height / 2;
    if (!east && !south) return "nw";
    if (east && !south) return "ne";
    if (!east && south) return "sw";
    return "se";
  }

  function shouldSuppressLabel(rect, tier, { isPeripheral = false, quadrant = "nw" } = {}) {
    const thresholdByTier = new Map([
      [1, 0.3],
      [2, 0.1],
      [3, 0.04],
      [4, 0.0],
    ]);
    const maxByTier = new Map([
      [1, 10],
      [2, 20],
      [3, 18],
      [4, 8],
    ]);
    const minQuadrantBudget = 3;
    const currentQuadrantCount = Number(quadrantLabelCounts.get(quadrant) || 0);
    const seen = Number(tierLabelCounts.get(tier) || 0);
    const tierCap = Number(maxByTier.get(tier) || 0);
    const relaxedCap = isPeripheral && tier >= 3 ? tierCap + 8 : tierCap;
    if (relaxedCap > 0 && seen >= relaxedCap && tier >= 3 && currentQuadrantCount >= minQuadrantBudget) return true;
    const minArea = Math.max(1, rect.width * rect.height);
    let threshold = Number(thresholdByTier.get(tier) || 0);
    if (isPeripheral && tier >= 3 && currentQuadrantCount < minQuadrantBudget) {
      threshold += 0.07;
    } else if (isPeripheral && tier >= 3) {
      threshold += 0.04;
    } else if (!isPeripheral && tier >= 3) {
      threshold = Math.max(0.0, threshold - 0.01);
    }
    for (const existing of drawnLabelRects) {
      if (existing.tier > tier) continue;
      const area = overlapArea(existing, rect);
      if (area <= 0) continue;
      const ratio = area / Math.min(minArea, existing.area);
      if (ratio > threshold) return true;
    }
    return false;
  }

  const renderer = new SigmaCtor(graph, container, {
    renderEdgeLabels: true,
    enableEdgeEvents: true,
    hideEdgesOnMove: true,
    hideLabelsOnMove: true,
    defaultNodeColor: "#9fb2c8",
    defaultEdgeColor: "#4f627d",
    minCameraRatio: 0.04,
    maxCameraRatio: 8,
    labelRenderedSizeThreshold: 0,
    labelDensity: 0.62,
    labelGridCellSize: 120,
    edgeLabelSize: "fixed",
    defaultEdgeLabelSize: 11,
    zIndex: true,
    stagePadding: 40,
    defaultDrawNodeLabel(context, data) {
      if (!data.label || data.hidden) return;
      const tier = nodeLabelTier(data.key, data);
      if (data.dimmed && tier >= 3) return;
      const ratio = renderer.getRenderParams().pixelRatio || window.devicePixelRatio || 1;
      const fontSize = data.size >= 7 ? 13 : 12;
      context.font = `${fontSize}px "IBM Plex Sans", sans-serif`;
      const text = compactLabel(String(data.label), tier);
      const textWidth = context.measureText(text).width;
      const padX = 8;
      const padY = 4;
      const width = textWidth + padX * 2;
      const height = fontSize + padY * 2;
      const x = data.x - width / 2;
      const degree = Number(graph.degree?.(data.key) || 0);
      const degreeOffset = degree >= 7 ? 11 : (degree >= 4 ? 7 : (degree >= 2 ? 4 : 0));
      const tierOffset = tier >= 3 ? 2 : 0;
      const bandOffset = ((degree % 3) - 1) * 2;
      const orderLike = /^order/i.test(text);
      const orderOffset = orderLike ? ((smallHash(data.key) % 5) - 2) * 5 : 0;
      const y = data.y - data.size - height - 4 - degreeOffset - tierOffset + bandOffset + orderOffset;
      const dims = renderer.getDimensions();

      if (x < 1 || y < 1 || x + width > dims.width - 1 || y + height > dims.height - 1) return;

      const rect = { x, y, width, height, area: Math.max(1, width * height), tier };
      const cx = x + width / 2;
      const cy = y + height / 2;
      const dx = cx - dims.width / 2;
      const dy = cy - dims.height / 2;
      const distNorm = Math.sqrt(dx * dx + dy * dy) / Math.max(1, Math.sqrt(dims.width * dims.width + dims.height * dims.height) * 0.5);
      const isPeripheral = distNorm >= 0.57;
      const quadrant = quadrantForRect(rect, dims);
      if (shouldSuppressLabel(rect, tier, { isPeripheral, quadrant })) return;

      roundRect(context, x, y, width, height, 5);
      context.fillStyle = colorWithAlpha(data.color || "#101826", 0.82);
      context.fill();
      context.strokeStyle = colorWithAlpha("#9fb2c8", 0.45);
      context.lineWidth = 1;
      context.stroke();

      context.fillStyle = "#e5edf7";
      context.textBaseline = "middle";
      context.fillText(text, x + padX, y + height / 2 + 0.5);

      const graphRect = container.getBoundingClientRect();
      const filterRect = document.getElementById("filter-bar")?.getBoundingClientRect() || null;
      if (filterRect) {
        const fx = filterRect.left - graphRect.left;
        const fy = filterRect.top - graphRect.top;
        const fw = filterRect.width;
        const fh = filterRect.height;
        const overlapW = Math.max(0, Math.min(x + width, fx + fw) - Math.max(x, fx));
        const overlapH = Math.max(0, Math.min(y + height, fy + fh) - Math.max(y, fy));
        if (overlapW > 0 && overlapH > 0) return;
      }

      drawnLabelRects.push(rect);
      tierLabelCounts.set(tier, Number(tierLabelCounts.get(tier) || 0) + 1);
      quadrantLabelCounts.set(quadrant, Number(quadrantLabelCounts.get(quadrant) || 0) + 1);
      nodeLabelHitboxes.set(data.key, {
        x: x * ratio,
        y: y * ratio,
        width: width * ratio,
        height: height * ratio,
      });
    },
    nodeReducer(nodeId, data) {
      const result = { ...data };
      if (result.hidden) result.hidden = true;
      if (result.dimmed) {
        result.color = colorWithAlpha(result.color || "#7f8ea6", 0.24);
        result.label = "";
      }
      return result;
    },
    edgeReducer(edgeId, data) {
      const result = { ...data };
      if (result.hidden) return { ...result, hidden: true };
      const sourceId = graph.source(edgeId);
      const targetId = graph.target(edgeId);
      const isHoverIncident =
        !!hoveredNodeId && (String(sourceId) === hoveredNodeId || String(targetId) === hoveredNodeId);
      const showLabel =
        result.show_label === true
        || (hoveredEdgeId != null && String(edgeId) === hoveredEdgeId)
        || isHoverIncident;
      if (!showLabel) {
        result.label = "";
      }
      if (!result.is_high_signal && !showLabel) {
        result.color = colorWithAlpha(result.color || "#4f627d", result.dense_scene ? 0.22 : 0.35);
      }
      if (result.dimmed) {
        result.color = colorWithAlpha(result.color || "#4f627d", 0.18);
        result.zIndex = 0;
      } else if (result.is_high_signal) {
        result.zIndex = 2;
      } else {
        result.zIndex = 1;
      }
      return result;
    },
  });

  renderer.on("beforeRender", () => {
    nodeLabelHitboxes.clear();
    drawnLabelRects.length = 0;
    tierLabelCounts.set(1, 0);
    tierLabelCounts.set(2, 0);
    tierLabelCounts.set(3, 0);
    tierLabelCounts.set(4, 0);
    quadrantLabelCounts.set("nw", 0);
    quadrantLabelCounts.set("ne", 0);
    quadrantLabelCounts.set("sw", 0);
    quadrantLabelCounts.set("se", 0);
  });

  renderer.on("enterNode", ({ node }) => {
    hoveredNodeId = String(node);
  });

  renderer.on("leaveNode", () => {
    hoveredNodeId = null;
  });

  renderer.on("enterEdge", ({ edge }) => {
    hoveredEdgeId = String(edge);
  });

  renderer.on("leaveEdge", () => {
    hoveredEdgeId = null;
  });

  function refresh() {
    renderer.refresh();
  }

  function fitVisible({ animate = true } = {}) {
    const camera = renderer.getCamera();
    const bounds = buildBounds(graph);
    if (!bounds) {
      const nextState = defaultCameraState();
      if (animate) {
        camera.animate(nextState, { duration: 300 });
        return;
      }
      camera.setState(nextState);
      return;
    }
    const nextState = defaultCameraState();
    if (animate) {
      camera.animate(nextState, { duration: 350 });
      return;
    }
    camera.setState(nextState);
  }

  function centerOnNode(nodeId, { animate = true, ratio = null } = {}) {
    if (!graph.hasNode(nodeId)) return;
    const attrs = graph.getNodeAttributes(nodeId);
    const camera = renderer.getCamera();
    const nextRatio = ratio == null ? camera.getState().ratio : ratio;
    const next = { x: Number(attrs.x), y: Number(attrs.y), ratio: nextRatio, angle: camera.getState().angle || 0 };
    if (animate) {
      camera.animate(next, { duration: 280 });
      return;
    }
    camera.setState(next);
  }

  function ensureNodeVisible(nodeId) {
    if (!graph.hasNode(nodeId)) return false;
    const attrs = graph.getNodeAttributes(nodeId);
    const point = renderer.graphToViewport({ x: attrs.x, y: attrs.y });
    const dims = renderer.getDimensions();
    const pad = 80;
    const visible = point.x >= pad && point.y >= pad && point.x <= dims.width - pad && point.y <= dims.height - pad;
    if (visible) return true;
    centerOnNode(nodeId, { animate: true });
    return false;
  }

  function destroy() {
    renderer.kill();
  }

  return {
    renderer,
    refresh,
    fitVisible,
    centerOnNode,
    ensureNodeVisible,
    destroy,
  };
}
