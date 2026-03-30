function hashUnit(input) {
  let h = 2166136261;
  const text = String(input ?? "");
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  const positive = h >>> 0;
  return positive / 4294967295;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function estimateLabelWidth(attrs) {
  const text = String(attrs?.label || attrs?.node_name || attrs?.full_name || "");
  if (!text) return 56;
  return Math.max(56, Math.min(300, text.length * 7 + 18));
}

function estimateLabelHeight(attrs) {
  const size = Number(attrs?.size || 8);
  return Math.max(18, 13 + size * 0.9);
}

function labelCollisionExtents(attrs) {
  const size = Number(attrs?.size || 8);
  const hx = Math.max(size * 1.4, estimateLabelWidth(attrs) * 0.22);
  const hy = Math.max(size * 1.2, estimateLabelHeight(attrs) * 1.02);
  return { hx, hy };
}

function nodeSpacing(graph, nodeId, attrs) {
  const base = 20;
  const size = Number(attrs?.size || 8);
  const type = String(attrs?.node_type || "");
  const typeBonus =
    type === "class"
      ? 13
      : (type === "method" ? 9 : (type === "function" ? 8 : (type === "virtual" ? 10 : 6)));
  const degree = Number(graph.degree?.(nodeId) || 0);
  const degreeBonus = Math.min(18, Math.sqrt(Math.max(0, degree)) * 5);
  const labelBonus = Math.min(56, estimateLabelWidth(attrs) * 0.22) + Math.min(24, estimateLabelHeight(attrs) * 0.35);
  return base + size * 1.4 + typeBonus + degreeBonus + labelBonus;
}

export function createLayoutEngine() {
  let pinnedNodeId = null;
  let exclusionZones = [];

  function initializeLayout(graph, { seed = 42 } = {}) {
    let index = 0;
    graph.forEachNode((nodeId, attrs) => {
      if (attrs.node_type === "__label__") return;
      const x = Number(attrs.x);
      const y = Number(attrs.y);
      if (Number.isFinite(x) && Number.isFinite(y)) return;
      const ux = hashUnit(`${seed}:${nodeId}:x:${index}`);
      const uy = hashUnit(`${seed}:${nodeId}:y:${index}`);
      const angle = ux * Math.PI * 2;
      const radius = 80 + uy * 260;
      graph.setNodeAttribute(nodeId, "x", Math.cos(angle) * radius);
      graph.setNodeAttribute(nodeId, "y", Math.sin(angle) * radius);
      index += 1;
    });
  }

  function relaxCollisions(
    graph,
    nodes,
    {
      minRounds = 8,
      maxRounds = 22,
      targetAverageOverlap = 0.045,
    } = {},
  ) {
    let previousAverage = Number.POSITIVE_INFINITY;
    for (let round = 0; round < maxRounds; round += 1) {
      let collisions = 0;
      let overlapBudget = 0;
      for (let i = 0; i < nodes.length; i += 1) {
        const aId = nodes[i];
        const a = graph.getNodeAttributes(aId);
        for (let j = i + 1; j < nodes.length; j += 1) {
          const bId = nodes[j];
          const b = graph.getNodeAttributes(bId);
          const aBox = labelCollisionExtents(a);
          const bBox = labelCollisionExtents(b);
          const minDist = Math.max(
            nodeSpacing(graph, aId, a),
            nodeSpacing(graph, bId, b),
          );
          let dx = Number(b.x) - Number(a.x);
          let dy = Number(b.y) - Number(a.y);
          let d = Math.sqrt(dx * dx + dy * dy);
          if (!Number.isFinite(d) || d < 0.0001) {
            const jitter = (hashUnit(`${aId}:${bId}:${round}`) - 0.5) * 0.5;
            dx = 0.02 + jitter;
            dy = 0.02 - jitter;
            d = Math.sqrt(dx * dx + dy * dy);
          }
          const overlapX = aBox.hx + bBox.hx - Math.abs(dx);
          const overlapY = aBox.hy + bBox.hy - Math.abs(dy);
          if (overlapX > 0 && overlapY > 0) {
            collisions += 1;
            const normX = overlapX / Math.max(1, aBox.hx + bBox.hx);
            const normY = overlapY / Math.max(1, aBox.hy + bBox.hy);
            overlapBudget += Math.max(normX, normY);
            const sx = dx >= 0 ? 1 : -1;
            const sy = dy >= 0 ? 1 : -1;
            const pushX = overlapX * 0.5;
            const pushY = overlapY * 0.5;
            if (!(pinnedNodeId && aId === pinnedNodeId)) {
              graph.setNodeAttribute(aId, "x", Number(a.x) - sx * (pushX * 0.5));
              graph.setNodeAttribute(aId, "y", Number(a.y) - sy * (pushY * 0.5));
            }
            if (!(pinnedNodeId && bId === pinnedNodeId)) {
              graph.setNodeAttribute(bId, "x", Number(b.x) + sx * (pushX * 0.5));
              graph.setNodeAttribute(bId, "y", Number(b.y) + sy * (pushY * 0.5));
            }
          }
          if (d >= minDist) continue;
          collisions += 1;
          const overlap = minDist - d;
          overlapBudget += overlap / minDist;
          const push = overlap * (overlapX > 0 && overlapY > 0 ? 0.34 : 0.52);
          const ux = dx / d;
          const uy = dy / d;
          if (!(pinnedNodeId && aId === pinnedNodeId)) {
            graph.setNodeAttribute(aId, "x", Number(a.x) - ux * push);
            graph.setNodeAttribute(aId, "y", Number(a.y) - uy * push);
          }
          if (!(pinnedNodeId && bId === pinnedNodeId)) {
            graph.setNodeAttribute(bId, "x", Number(b.x) + ux * push);
            graph.setNodeAttribute(bId, "y", Number(b.y) + uy * push);
          }
        }
      }
      const averageOverlap = collisions > 0 ? overlapBudget / collisions : 0;
      const roundsMet = round + 1 >= minRounds;
      if (!roundsMet) {
        previousAverage = averageOverlap;
        continue;
      }
      if (averageOverlap <= targetAverageOverlap) break;
      if (averageOverlap >= previousAverage - 0.0015) break;
      previousAverage = averageOverlap;
    }
  }

  function normalizeViewportSpread(
    graph,
    nodes,
    {
      minFill = 0.92,
      maxFill = 0.98,
    } = {},
  ) {
    if (!Array.isArray(nodes) || nodes.length < 2) return;

    let minX = Number.POSITIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;
    let sumX = 0;
    let sumY = 0;
    let spacingSum = 0;
    let count = 0;

    for (const nodeId of nodes) {
      if (!graph.hasNode(nodeId)) continue;
      const attrs = graph.getNodeAttributes(nodeId);
      const x = Number(attrs.x);
      const y = Number(attrs.y);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
      sumX += x;
      sumY += y;
      spacingSum += nodeSpacing(graph, nodeId, attrs);
      count += 1;
    }

    if (count < 2) return;

    const spanX = Math.max(1, maxX - minX);
    const spanY = Math.max(1, maxY - minY);
    const centerX = sumX / count;
    const centerY = sumY / count;
    const avgSpacing = spacingSum / count;
    const targetScale = Math.sqrt(count);
    const targetWidth = Math.max(300, targetScale * avgSpacing * 1.9);
    const targetHeight = Math.max(220, targetScale * avgSpacing * 1.65);
    const fillX = spanX / targetWidth;
    const fillY = spanY / targetHeight;
    let scale = 1;

    if (fillX < minFill || fillY < minFill) {
      const needX = fillX < minFill ? minFill / Math.max(0.0001, fillX) : 1;
      const needY = fillY < minFill ? minFill / Math.max(0.0001, fillY) : 1;
      scale = Math.max(needX, needY);
    } else if (fillX > maxFill || fillY > maxFill) {
      const trimX = fillX > maxFill ? maxFill / fillX : 1;
      const trimY = fillY > maxFill ? maxFill / fillY : 1;
      scale = Math.min(trimX, trimY);
    }

    if (!Number.isFinite(scale) || Math.abs(scale - 1) < 0.01) return;

    for (const nodeId of nodes) {
      if (!graph.hasNode(nodeId)) continue;
      if (pinnedNodeId && nodeId === pinnedNodeId) continue;
      const attrs = graph.getNodeAttributes(nodeId);
      const x = Number(attrs.x);
      const y = Number(attrs.y);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      graph.setNodeAttribute(nodeId, "x", centerX + (x - centerX) * scale);
      graph.setNodeAttribute(nodeId, "y", centerY + (y - centerY) * scale);
    }
  }

  function expandDenseCells(
    graph,
    nodes,
    {
      cellSize = 170,
      minNodesPerCell = 4,
      maxPasses = 3,
      maxPush = 36,
    } = {},
  ) {
    if (!Array.isArray(nodes) || nodes.length < minNodesPerCell) return;
    for (let pass = 0; pass < maxPasses; pass += 1) {
      const cells = new Map();
      for (const nodeId of nodes) {
        if (!graph.hasNode(nodeId)) continue;
        const attrs = graph.getNodeAttributes(nodeId);
        if (attrs.hidden || attrs.node_type === "__label__") continue;
        const x = Number(attrs.x);
        const y = Number(attrs.y);
        if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
        const cx = Math.floor(x / cellSize);
        const cy = Math.floor(y / cellSize);
        const key = `${cx}:${cy}`;
        if (!cells.has(key)) cells.set(key, []);
        cells.get(key).push(nodeId);
      }

      let moved = 0;
      for (const group of cells.values()) {
        if (!Array.isArray(group) || group.length < minNodesPerCell) continue;

        let centroidX = 0;
        let centroidY = 0;
        let spacingSum = 0;
        const snapshots = [];
        for (const nodeId of group) {
          const attrs = graph.getNodeAttributes(nodeId);
          const x = Number(attrs.x);
          const y = Number(attrs.y);
          if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
          snapshots.push({ nodeId, x, y, attrs });
          centroidX += x;
          centroidY += y;
          spacingSum += nodeSpacing(graph, nodeId, attrs);
        }
        if (snapshots.length < minNodesPerCell) continue;
        centroidX /= snapshots.length;
        centroidY /= snapshots.length;

        let nearestSum = 0;
        for (let i = 0; i < snapshots.length; i += 1) {
          let nearest = Number.POSITIVE_INFINITY;
          const a = snapshots[i];
          for (let j = 0; j < snapshots.length; j += 1) {
            if (i === j) continue;
            const b = snapshots[j];
            const dx = a.x - b.x;
            const dy = a.y - b.y;
            const d = Math.sqrt(dx * dx + dy * dy);
            if (d < nearest) nearest = d;
          }
          if (Number.isFinite(nearest)) nearestSum += nearest;
        }
        const avgNearest = nearestSum / snapshots.length;
        const targetSpacing = spacingSum / snapshots.length;
        if (!Number.isFinite(avgNearest) || !Number.isFinite(targetSpacing)) continue;
        if (avgNearest >= targetSpacing * 0.78) continue;

        for (const item of snapshots) {
          if (pinnedNodeId && item.nodeId === pinnedNodeId) continue;
          let dx = item.x - centroidX;
          let dy = item.y - centroidY;
          let d = Math.sqrt(dx * dx + dy * dy);
          if (!Number.isFinite(d) || d < 0.0001) {
            const jitter = (hashUnit(`${item.nodeId}:${pass}`) - 0.5) * 0.6;
            dx = 0.2 + jitter;
            dy = -0.2 + jitter;
            d = Math.sqrt(dx * dx + dy * dy);
          }
          const deficit = Math.max(0, targetSpacing - avgNearest);
          const crowdFactor = Math.max(1, snapshots.length - minNodesPerCell + 1);
          const push = clamp(deficit * 0.34 + crowdFactor * 1.9, 4.0, maxPush);
          const ux = dx / d;
          const uy = dy / d;
          graph.setNodeAttribute(item.nodeId, "x", item.x + ux * push);
          graph.setNodeAttribute(item.nodeId, "y", item.y + uy * push);
          moved += 1;
        }
      }

      if (moved === 0) break;
      relaxCollisions(graph, nodes, {
        minRounds: 6,
        maxRounds: 14,
        targetAverageOverlap: 0.048,
      });
    }
  }

  function enforceLocalSpacingFloor(
    graph,
    nodes,
    {
      cellSize = 190,
      minBaseFloor = 72,
      maxRounds = 4,
    } = {},
  ) {
    if (!Array.isArray(nodes) || nodes.length < 2) return;
    for (let round = 0; round < maxRounds; round += 1) {
      const cells = new Map();
      for (const nodeId of nodes) {
        if (!graph.hasNode(nodeId)) continue;
        const attrs = graph.getNodeAttributes(nodeId);
        if (attrs.hidden || attrs.node_type === "__label__") continue;
        const x = Number(attrs.x);
        const y = Number(attrs.y);
        if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
        const cx = Math.floor(x / cellSize);
        const cy = Math.floor(y / cellSize);
        const key = `${cx}:${cy}`;
        if (!cells.has(key)) cells.set(key, []);
        cells.get(key).push(nodeId);
      }

      let adjusted = 0;
      for (const group of cells.values()) {
        if (!Array.isArray(group) || group.length < 2) continue;
        const denseBoost = group.length >= 6 ? 30 : (group.length >= 5 ? 24 : (group.length >= 4 ? 16 : 10));
        for (let i = 0; i < group.length; i += 1) {
          const aId = group[i];
          const a = graph.getNodeAttributes(aId);
          for (let j = i + 1; j < group.length; j += 1) {
            const bId = group[j];
            const b = graph.getNodeAttributes(bId);
            let dx = Number(b.x) - Number(a.x);
            let dy = Number(b.y) - Number(a.y);
            let d = Math.sqrt(dx * dx + dy * dy);
            if (!Number.isFinite(d) || d < 0.001) {
              dx = 0.02;
              dy = 0.02;
              d = Math.sqrt(dx * dx + dy * dy);
            }
            const floorA = minBaseFloor + Math.min(34, Math.sqrt(Math.max(0, graph.degree(aId))) * 7.5);
            const floorB = minBaseFloor + Math.min(34, Math.sqrt(Math.max(0, graph.degree(bId))) * 7.5);
            const floor = Math.max(floorA, floorB) + denseBoost;
            if (d >= floor) continue;
            const overlap = floor - d;
            const ux = dx / d;
            const uy = dy / d;
            const push = overlap * 0.64;
            if (!(pinnedNodeId && aId === pinnedNodeId)) {
              graph.setNodeAttribute(aId, "x", Number(a.x) - ux * push);
              graph.setNodeAttribute(aId, "y", Number(a.y) - uy * push);
            }
            if (!(pinnedNodeId && bId === pinnedNodeId)) {
              graph.setNodeAttribute(bId, "x", Number(b.x) + ux * push);
              graph.setNodeAttribute(bId, "y", Number(b.y) + uy * push);
            }
            adjusted += 1;
          }
        }
      }
      if (adjusted === 0) break;
    }
  }

  function enforceNearZeroOverlap(
    graph,
    nodes,
    {
      maxRounds = 18,
      targetNormalizedOverlap = 0.012,
    } = {},
  ) {
    if (!Array.isArray(nodes) || nodes.length < 2) return;
    for (let round = 0; round < maxRounds; round += 1) {
      let collisions = 0;
      let overlapScore = 0;
      for (let i = 0; i < nodes.length; i += 1) {
        const aId = nodes[i];
        if (!graph.hasNode(aId)) continue;
        const a = graph.getNodeAttributes(aId);
        for (let j = i + 1; j < nodes.length; j += 1) {
          const bId = nodes[j];
          if (!graph.hasNode(bId)) continue;
          const b = graph.getNodeAttributes(bId);
          const ax = Number(a.x);
          const ay = Number(a.y);
          const bx = Number(b.x);
          const by = Number(b.y);
          if (![ax, ay, bx, by].every(Number.isFinite)) continue;
          let dx = bx - ax;
          let dy = by - ay;
          let d = Math.sqrt(dx * dx + dy * dy);
          if (!Number.isFinite(d) || d < 0.001) {
            dx = 0.03;
            dy = 0.03;
            d = Math.sqrt(dx * dx + dy * dy);
          }
          const aBox = labelCollisionExtents(a);
          const bBox = labelCollisionExtents(b);
          const overlapX = aBox.hx + bBox.hx - Math.abs(dx);
          const overlapY = aBox.hy + bBox.hy - Math.abs(dy);
          if (overlapX <= 0 || overlapY <= 0) continue;
          collisions += 1;
          const normX = overlapX / Math.max(1, aBox.hx + bBox.hx);
          const normY = overlapY / Math.max(1, aBox.hy + bBox.hy);
          overlapScore += Math.max(normX, normY);
          const pushX = overlapX * 0.56;
          const pushY = overlapY * 0.56;
          const sx = dx >= 0 ? 1 : -1;
          const sy = dy >= 0 ? 1 : -1;
          if (!(pinnedNodeId && aId === pinnedNodeId)) {
            graph.setNodeAttribute(aId, "x", ax - sx * pushX * 0.5);
            graph.setNodeAttribute(aId, "y", ay - sy * pushY * 0.5);
          }
          if (!(pinnedNodeId && bId === pinnedNodeId)) {
            graph.setNodeAttribute(bId, "x", bx + sx * pushX * 0.5);
            graph.setNodeAttribute(bId, "y", by + sy * pushY * 0.5);
          }
        }
      }
      if (collisions === 0) break;
      const normalized = overlapScore / collisions;
      if (normalized <= targetNormalizedOverlap) break;
    }
  }

  function spreadHubNeighbors(
    graph,
    nodes,
    {
      minHubDegree = 4,
      blend = 0.42,
    } = {},
  ) {
    if (!Array.isArray(nodes) || nodes.length < 6) return;
    const nodeSet = new Set(nodes);
    for (const hubId of nodes) {
      if (!graph.hasNode(hubId)) continue;
      if (graph.degree(hubId) < minHubDegree) continue;
      const hubAttrs = graph.getNodeAttributes(hubId);
      const hx = Number(hubAttrs.x);
      const hy = Number(hubAttrs.y);
      if (!Number.isFinite(hx) || !Number.isFinite(hy)) continue;
      const neighbors = (graph.neighbors(hubId) || [])
        .filter((neighborId) => nodeSet.has(neighborId) && graph.hasNode(neighborId))
        .filter((neighborId) => !graph.getNodeAttribute(neighborId, "hidden"))
        .filter((neighborId) => !(pinnedNodeId && neighborId === pinnedNodeId));
      if (neighbors.length < minHubDegree) continue;

      const arranged = [];
      let angleSum = 0;
      let radiusSum = 0;
      for (const neighborId of neighbors) {
        const attrs = graph.getNodeAttributes(neighborId);
        const nx = Number(attrs.x);
        const ny = Number(attrs.y);
        if (!Number.isFinite(nx) || !Number.isFinite(ny)) continue;
        const dx = nx - hx;
        const dy = ny - hy;
        const angle = Math.atan2(dy, dx);
        const radius = Math.sqrt(dx * dx + dy * dy);
        arranged.push({ neighborId, nx, ny, angle, radius });
        angleSum += angle;
        radiusSum += radius;
      }
      if (arranged.length < minHubDegree) continue;
      arranged.sort((a, b) => a.angle - b.angle);
      const centerAngle = angleSum / arranged.length;
      const avgRadius = radiusSum / arranged.length;
      const baseRadius = Math.max(72, avgRadius, nodeSpacing(graph, hubId, hubAttrs) * 1.45);
      const arc = Math.min(Math.PI * 1.95, Math.PI * 1.08 + arranged.length * 0.22);
      const start = centerAngle - arc / 2;
      const count = arranged.length;
      for (let i = 0; i < arranged.length; i += 1) {
        const item = arranged[i];
        const ratio = count > 1 ? i / (count - 1) : 0.5;
        const targetAngle = start + arc * ratio;
        const ringOffset = (i % 4) * 18;
        const targetRadius = baseRadius + ringOffset;
        const tx = hx + Math.cos(targetAngle) * targetRadius;
        const ty = hy + Math.sin(targetAngle) * targetRadius;
        const nextX = item.nx * (1 - blend) + tx * blend;
        const nextY = item.ny * (1 - blend) + ty * blend;
        graph.setNodeAttribute(item.neighborId, "x", nextX);
        graph.setNodeAttribute(item.neighborId, "y", nextY);
      }
    }
  }

  function deconflictHubCorridors(
    graph,
    nodes,
    {
      minHubDegree = 4,
      minAngleGap = 0.22,
      maxRounds = 2,
    } = {},
  ) {
    if (!Array.isArray(nodes) || nodes.length < 6) return;
    const nodeSet = new Set(nodes);
    for (let round = 0; round < maxRounds; round += 1) {
      let adjusted = 0;
      for (const hubId of nodes) {
        if (!graph.hasNode(hubId)) continue;
        if (graph.degree(hubId) < minHubDegree) continue;
        const hub = graph.getNodeAttributes(hubId);
        const hx = Number(hub.x);
        const hy = Number(hub.y);
        if (!Number.isFinite(hx) || !Number.isFinite(hy)) continue;
        const neighbors = (graph.neighbors(hubId) || [])
          .filter((id) => nodeSet.has(id) && graph.hasNode(id))
          .filter((id) => !(pinnedNodeId && id === pinnedNodeId))
          .map((id) => {
            const attrs = graph.getNodeAttributes(id);
            const nx = Number(attrs.x);
            const ny = Number(attrs.y);
            const dx = nx - hx;
            const dy = ny - hy;
            const angle = Math.atan2(dy, dx);
            const radius = Math.sqrt(dx * dx + dy * dy);
            return { id, attrs, nx, ny, angle, radius };
          })
          .filter((item) => Number.isFinite(item.radius) && item.radius > 0.001)
          .sort((a, b) => a.angle - b.angle);
        if (neighbors.length < minHubDegree) continue;
        for (let i = 0; i < neighbors.length - 1; i += 1) {
          const a = neighbors[i];
          const b = neighbors[i + 1];
          const gap = b.angle - a.angle;
          if (gap >= minAngleGap) continue;
          const deficit = minAngleGap - gap;
          const tangentAx = -Math.sin(a.angle);
          const tangentAy = Math.cos(a.angle);
          const tangentBx = Math.sin(b.angle);
          const tangentBy = -Math.cos(b.angle);
          const pushA = deficit * Math.max(10, a.radius * 0.16);
          const pushB = deficit * Math.max(10, b.radius * 0.16);
          graph.setNodeAttribute(a.id, "x", a.nx + tangentAx * pushA);
          graph.setNodeAttribute(a.id, "y", a.ny + tangentAy * pushA);
          graph.setNodeAttribute(b.id, "x", b.nx + tangentBx * pushB);
          graph.setNodeAttribute(b.id, "y", b.ny + tangentBy * pushB);
          adjusted += 1;
        }
      }
      if (adjusted === 0) break;
      relaxCollisions(graph, nodes, {
        minRounds: 5,
        maxRounds: 12,
        targetAverageOverlap: 0.038,
      });
    }
  }

  function deflectCrossingCorridors(
    graph,
    nodes,
    {
      minHubDegree = 4,
      angleThreshold = 0.16,
      radiusThreshold = 34,
      maxRounds = 2,
    } = {},
  ) {
    if (!Array.isArray(nodes) || nodes.length < 6) return;
    const nodeSet = new Set(nodes);
    for (let round = 0; round < maxRounds; round += 1) {
      let moved = 0;
      for (const hubId of nodes) {
        if (!graph.hasNode(hubId)) continue;
        if (graph.degree(hubId) < minHubDegree) continue;
        const hub = graph.getNodeAttributes(hubId);
        const hx = Number(hub.x);
        const hy = Number(hub.y);
        if (!Number.isFinite(hx) || !Number.isFinite(hy)) continue;
        const neighbors = (graph.neighbors(hubId) || [])
          .filter((id) => nodeSet.has(id) && graph.hasNode(id))
          .filter((id) => !(pinnedNodeId && id === pinnedNodeId))
          .map((id) => {
            const attrs = graph.getNodeAttributes(id);
            const nx = Number(attrs.x);
            const ny = Number(attrs.y);
            const dx = nx - hx;
            const dy = ny - hy;
            const angle = Math.atan2(dy, dx);
            const radius = Math.sqrt(dx * dx + dy * dy);
            return { id, nx, ny, angle, radius };
          })
          .filter((item) => Number.isFinite(item.radius) && item.radius > 0.001)
          .sort((a, b) => a.angle - b.angle);
        if (neighbors.length < minHubDegree) continue;
        for (let i = 0; i < neighbors.length - 1; i += 1) {
          const a = neighbors[i];
          const b = neighbors[i + 1];
          const gap = Math.abs(b.angle - a.angle);
          const rGap = Math.abs(b.radius - a.radius);
          if (gap > angleThreshold || rGap > radiusThreshold) continue;
          const midAngle = (a.angle + b.angle) / 2;
          const rx = Math.cos(midAngle);
          const ry = Math.sin(midAngle);
          const radialPush = Math.max(10, (angleThreshold - gap) * 80);
          const tangentPush = Math.max(8, (radiusThreshold - rGap) * 0.22);
          const tx = -Math.sin(midAngle);
          const ty = Math.cos(midAngle);
          graph.setNodeAttribute(a.id, "x", a.nx - rx * radialPush + tx * tangentPush);
          graph.setNodeAttribute(a.id, "y", a.ny - ry * radialPush + ty * tangentPush);
          graph.setNodeAttribute(b.id, "x", b.nx + rx * radialPush - tx * tangentPush);
          graph.setNodeAttribute(b.id, "y", b.ny + ry * radialPush - ty * tangentPush);
          moved += 1;
        }
      }
      if (moved === 0) break;
      relaxCollisions(graph, nodes, {
        minRounds: 4,
        maxRounds: 12,
        targetAverageOverlap: 0.037,
      });
    }
  }

  function applyExclusionZones(
    graph,
    nodes,
    {
      defaultPadding = 20,
      maxPasses = 3,
    } = {},
  ) {
    if (!Array.isArray(exclusionZones) || exclusionZones.length === 0) return;
    if (!Array.isArray(nodes) || nodes.length === 0) return;
    for (let pass = 0; pass < maxPasses; pass += 1) {
      let moved = 0;
      for (const nodeId of nodes) {
        if (!graph.hasNode(nodeId)) continue;
        if (pinnedNodeId && nodeId === pinnedNodeId) continue;
        const attrs = graph.getNodeAttributes(nodeId);
        const x = Number(attrs.x);
        const y = Number(attrs.y);
        if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
        for (const zone of exclusionZones) {
          const left = Number(zone.left);
          const right = Number(zone.right);
          const top = Number(zone.top);
          const bottom = Number(zone.bottom);
          if (![left, right, top, bottom].every(Number.isFinite)) continue;
          const pad = Number.isFinite(Number(zone.padding))
            ? Number(zone.padding)
            : defaultPadding;
          const ext = labelCollisionExtents(attrs);
          const minX = left - pad - ext.hx * 0.52;
          const maxX = right + pad + ext.hx * 0.52;
          const minY = top - pad - ext.hy * 0.52;
          const maxY = bottom + pad + ext.hy * 0.52;
          if (x < minX || x > maxX || y < minY || y > maxY) continue;
          const toLeft = Math.abs(x - minX);
          const toRight = Math.abs(maxX - x);
          const toTop = Math.abs(y - minY);
          const toBottom = Math.abs(maxY - y);
          const nearest = Math.min(toLeft, toRight, toTop, toBottom);
          let nx = x;
          let ny = y;
          if (nearest === toLeft) nx = minX - 2;
          else if (nearest === toRight) nx = maxX + 2;
          else if (nearest === toTop) ny = minY - 2;
          else ny = maxY + 2;
          graph.setNodeAttribute(nodeId, "x", nx);
          graph.setNodeAttribute(nodeId, "y", ny);
          moved += 1;
          break;
        }
      }
      if (moved === 0) break;
      relaxCollisions(graph, nodes, {
        minRounds: 4,
        maxRounds: 10,
        targetAverageOverlap: 0.05,
      });
    }
  }

  function shapeToCanvasBoundary(
    graph,
    nodes,
    {
      strength = 0.26,
      minRadiusX = 220,
      minRadiusY = 180,
    } = {},
  ) {
    if (!Array.isArray(nodes) || nodes.length < 4) return;
    let minX = Number.POSITIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;
    let sumX = 0;
    let sumY = 0;
    let count = 0;
    for (const nodeId of nodes) {
      if (!graph.hasNode(nodeId)) continue;
      const attrs = graph.getNodeAttributes(nodeId);
      if (attrs.hidden || attrs.node_type === "__label__") continue;
      const x = Number(attrs.x);
      const y = Number(attrs.y);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
      sumX += x;
      sumY += y;
      count += 1;
    }
    if (count < 4) return;
    const centerX = sumX / count;
    const centerY = sumY / count;
    const rx = Math.max(minRadiusX, (maxX - minX) / 2);
    const ry = Math.max(minRadiusY, (maxY - minY) / 2);
    const targetRx = rx * 1.18;
    const targetRy = ry * 1.18;
    const blend = clamp(strength, 0.05, 0.35);
    for (const nodeId of nodes) {
      if (!graph.hasNode(nodeId)) continue;
      if (pinnedNodeId && nodeId === pinnedNodeId) continue;
      const attrs = graph.getNodeAttributes(nodeId);
      const x = Number(attrs.x);
      const y = Number(attrs.y);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      const dx = x - centerX;
      const dy = y - centerY;
      const theta = Math.atan2(dy, dx);
      const tx = centerX + Math.cos(theta) * targetRx;
      const ty = centerY + Math.sin(theta) * targetRy;
      graph.setNodeAttribute(nodeId, "x", x * (1 - blend) + tx * blend);
      graph.setNodeAttribute(nodeId, "y", y * (1 - blend) + ty * blend);
    }
  }

  function rebalanceOccupancySectors(
    graph,
    nodes,
    {
      sectors = 8,
      rounds = 2,
      blend = 0.36,
      sparseFactor = 0.78,
      denseFactor = 1.22,
    } = {},
  ) {
    if (!Array.isArray(nodes) || nodes.length < sectors + 2) return;
    for (let round = 0; round < rounds; round += 1) {
      let sumX = 0;
      let sumY = 0;
      let count = 0;
      const entries = [];
      for (const nodeId of nodes) {
        if (!graph.hasNode(nodeId)) continue;
        if (pinnedNodeId && nodeId === pinnedNodeId) continue;
        const attrs = graph.getNodeAttributes(nodeId);
        if (attrs.hidden || attrs.node_type === "__label__") continue;
        const x = Number(attrs.x);
        const y = Number(attrs.y);
        if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
        entries.push({ nodeId, x, y });
        sumX += x;
        sumY += y;
        count += 1;
      }
      if (count < sectors + 2) return;
      const centerX = sumX / count;
      const centerY = sumY / count;
      const sectorBuckets = Array.from({ length: sectors }, () => []);
      for (const entry of entries) {
        const angle = Math.atan2(entry.y - centerY, entry.x - centerX);
        const norm = angle < 0 ? angle + Math.PI * 2 : angle;
        const sector = Math.floor((norm / (Math.PI * 2)) * sectors) % sectors;
        const radius = Math.sqrt((entry.x - centerX) ** 2 + (entry.y - centerY) ** 2);
        sectorBuckets[sector].push({ ...entry, angle: norm, radius });
      }
      const target = count / sectors;
      const sparse = [];
      const dense = [];
      for (let i = 0; i < sectors; i += 1) {
        const size = sectorBuckets[i].length;
        if (size < target * sparseFactor) sparse.push(i);
        else if (size > target * denseFactor) dense.push(i);
      }
      if (sparse.length === 0 || dense.length === 0) break;
      let moved = 0;
      for (const denseSector of dense) {
        const bucket = sectorBuckets[denseSector]
          .slice()
          .sort((a, b) => b.radius - a.radius);
        const overflow = Math.max(0, Math.floor(bucket.length - target * denseFactor));
        const moveCount = Math.max(1, Math.min(bucket.length, overflow + 1));
        for (let i = 0; i < moveCount; i += 1) {
          const item = bucket[i];
          const targetSector = sparse[(i + denseSector) % sparse.length];
          const targetAngle = ((targetSector + 0.5) / sectors) * Math.PI * 2;
          const targetRadius = item.radius * 1.12;
          const tx = centerX + Math.cos(targetAngle) * targetRadius;
          const ty = centerY + Math.sin(targetAngle) * targetRadius;
          const nx = item.x * (1 - blend) + tx * blend;
          const ny = item.y * (1 - blend) + ty * blend;
          graph.setNodeAttribute(item.nodeId, "x", nx);
          graph.setNodeAttribute(item.nodeId, "y", ny);
          moved += 1;
        }
      }
      if (moved === 0) break;
      relaxCollisions(graph, nodes, {
        minRounds: 4,
        maxRounds: 10,
        targetAverageOverlap: 0.038,
      });
    }
  }

  function runForce(graph, {
    iterations = 80,
    repulsion = 7000,
    attraction = 0.005,
    gravity = 0.003,
    maxStep = 8.0,
    cooling = 0.99,
  } = {}) {
    const nodes = graph.nodes().filter((id) => {
      const attrs = graph.getNodeAttributes(id);
      return attrs.node_type !== "__label__" && !attrs.hidden;
    });
    if (nodes.length <= 1) return;

    const disp = new Map();
    let temperature = maxStep;

    for (let iter = 0; iter < iterations; iter += 1) {
      for (const id of nodes) {
        disp.set(id, { x: 0, y: 0 });
      }

      for (let i = 0; i < nodes.length; i += 1) {
        const aId = nodes[i];
        const a = graph.getNodeAttributes(aId);
        for (let j = i + 1; j < nodes.length; j += 1) {
          const bId = nodes[j];
          const b = graph.getNodeAttributes(bId);
          let dx = Number(a.x) - Number(b.x);
          let dy = Number(a.y) - Number(b.y);
          let d2 = dx * dx + dy * dy;
          if (!Number.isFinite(d2) || d2 < 0.0001) {
            dx = 0.01;
            dy = 0.01;
            d2 = 0.0002;
          }
          const d = Math.sqrt(d2);
          const force = repulsion / Math.max(10, d2);
          const fx = (dx / d) * force;
          const fy = (dy / d) * force;

          const ad = disp.get(aId);
          const bd = disp.get(bId);
          ad.x += fx;
          ad.y += fy;
          bd.x -= fx;
          bd.y -= fy;
        }
      }

      graph.forEachEdge((edgeId, edge) => {
        const sourceId = graph.source(edgeId);
        const targetId = graph.target(edgeId);
        if (!disp.has(sourceId) || !disp.has(targetId)) return;
        if (edge.hidden) return;
        const s = graph.getNodeAttributes(sourceId);
        const t = graph.getNodeAttributes(targetId);
        let dx = Number(t.x) - Number(s.x);
        let dy = Number(t.y) - Number(s.y);
        let d = Math.sqrt(dx * dx + dy * dy);
        if (!Number.isFinite(d) || d < 0.0001) d = 0.0001;
        const force = d * attraction;
        const fx = (dx / d) * force;
        const fy = (dy / d) * force;
        const sd = disp.get(sourceId);
        const td = disp.get(targetId);
        sd.x += fx;
        sd.y += fy;
        td.x -= fx;
        td.y -= fy;
      });

      for (const id of nodes) {
        if (pinnedNodeId && id === pinnedNodeId) continue;
        const attrs = graph.getNodeAttributes(id);
        const d = disp.get(id);
        d.x -= Number(attrs.x) * gravity;
        d.y -= Number(attrs.y) * gravity;
        const stepX = clamp(d.x, -temperature, temperature);
        const stepY = clamp(d.y, -temperature, temperature);
        graph.setNodeAttribute(id, "x", Number(attrs.x) + stepX);
        graph.setNodeAttribute(id, "y", Number(attrs.y) + stepY);
      }

      temperature *= cooling;
    }

    relaxCollisions(graph, nodes, {
      minRounds: 10,
      maxRounds: 26,
      targetAverageOverlap: 0.04,
    });
    expandDenseCells(graph, nodes, {
      cellSize: 168,
      minNodesPerCell: 4,
      maxPasses: 4,
      maxPush: 38,
    });
    enforceLocalSpacingFloor(graph, nodes, {
      cellSize: 192,
      minBaseFloor: 74,
      maxRounds: 4,
    });
    spreadHubNeighbors(graph, nodes, {
      minHubDegree: 4,
      blend: 0.42,
    });
    deconflictHubCorridors(graph, nodes, {
      minHubDegree: 4,
      minAngleGap: 0.28,
      maxRounds: 3,
    });
    deflectCrossingCorridors(graph, nodes, {
      minHubDegree: 4,
      angleThreshold: 0.17,
      radiusThreshold: 36,
      maxRounds: 2,
    });
    relaxCollisions(graph, nodes, {
      minRounds: 8,
      maxRounds: 18,
      targetAverageOverlap: 0.038,
    });
    normalizeViewportSpread(graph, nodes, {
      minFill: 0.92,
      maxFill: 0.98,
    });
    shapeToCanvasBoundary(graph, nodes, {
      strength: 0.28,
      minRadiusX: 260,
      minRadiusY: 210,
    });
    rebalanceOccupancySectors(graph, nodes, {
      sectors: 8,
      rounds: 2,
      blend: 0.34,
      sparseFactor: 0.76,
      denseFactor: 1.2,
    });
    applyExclusionZones(graph, nodes, {
      defaultPadding: 20,
      maxPasses: 3,
    });
    normalizeViewportSpread(graph, nodes, {
      minFill: 0.93,
      maxFill: 0.985,
    });
    relaxCollisions(graph, nodes, {
      minRounds: 5,
      maxRounds: 12,
      targetAverageOverlap: 0.038,
    });
    enforceNearZeroOverlap(graph, nodes, {
      maxRounds: 20,
      targetNormalizedOverlap: 0.01,
    });
  }

  function runInitialLayout(graph, { iterations = 340 } = {}) {
    runForce(graph, {
      iterations,
      maxStep: 14.2,
      repulsion: 16800,
      attraction: 0.0039,
      gravity: 0.0015,
      cooling: 0.994,
    });
  }

  function reheatLayout(graph, { iterations = 110 } = {}) {
    runForce(graph, {
      iterations,
      maxStep: 4.6,
      repulsion: 6200,
      attraction: 0.0052,
      gravity: 0.0028,
      cooling: 0.989,
    });
  }

  function setPinnedNode(nodeId) {
    pinnedNodeId = nodeId == null ? null : String(nodeId);
  }

  function setExclusionZones(zones) {
    if (!Array.isArray(zones)) {
      exclusionZones = [];
      return;
    }
    exclusionZones = zones
      .filter((zone) => zone && typeof zone === "object")
      .map((zone) => ({
        left: Number(zone.left),
        right: Number(zone.right),
        top: Number(zone.top),
        bottom: Number(zone.bottom),
        padding: Number(zone.padding),
      }))
      .filter((zone) =>
        [zone.left, zone.right, zone.top, zone.bottom].every(Number.isFinite)
        && zone.left < zone.right
        && zone.top < zone.bottom,
      );
  }

  function getPinnedNode() {
    return pinnedNodeId;
  }

  function disposeLayout() {
    pinnedNodeId = null;
  }

  return {
    initializeLayout,
    runInitialLayout,
    reheatLayout,
    setPinnedNode,
    setExclusionZones,
    getPinnedNode,
    disposeLayout,
  };
}
