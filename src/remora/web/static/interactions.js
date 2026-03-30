function bfsNeighborhood(graph, rootId, maxDepth) {
  const visited = new Set();
  const queue = [{ id: rootId, depth: 0 }];
  while (queue.length > 0) {
    const { id, depth } = queue.shift();
    if (visited.has(id)) continue;
    visited.add(id);
    if (depth >= maxDepth) continue;
    const neighbors = graph.neighbors(id) || [];
    for (const neighbor of neighbors) {
      if (!visited.has(neighbor)) queue.push({ id: neighbor, depth: depth + 1 });
    }
  }
  return visited;
}

function edgeBaseColor(label, isCrossFile) {
  if (label === "imports") return isCrossFile ? "#8fd1ff" : "#6cc6ff";
  if (label === "inherits") return isCrossFile ? "#c4b5ff" : "#ad97ff";
  if (label === "contains") return "#596d88";
  return isCrossFile ? "#8fd1ff" : "#78b8ff";
}

export function createInteractions({ graph, renderer }) {
  const HIGH_SIGNAL_EDGE_TYPES = new Set(["imports", "inherits", "calls", "references"]);
  const state = {
    selectedNodeId: null,
    focusMode: "full",
    hiddenNodeTypes: new Set(),
    hiddenEdgeTypes: new Set(),
    crossFileOnly: false,
    showContextTethers: true,
    pinSelected: false,
    visibilityStats: {
      totalNodes: 0,
      visibleNodes: 0,
      totalEdges: 0,
      visibleEdges: 0,
      hiddenByThinning: 0,
      focusMode: "full",
    },
  };

  function selectedFocusSet() {
    if (!state.selectedNodeId || !graph.hasNode(state.selectedNodeId)) return null;
    if (state.focusMode === "hop1") return bfsNeighborhood(graph, state.selectedNodeId, 1);
    if (state.focusMode === "hop2") return bfsNeighborhood(graph, state.selectedNodeId, 2);
    return null;
  }

  function applyVisibility() {
    const focusSet = selectedFocusSet();
    const selectedId =
      state.selectedNodeId && graph.hasNode(state.selectedNodeId)
        ? state.selectedNodeId
        : null;
    const selectedNeighbors = selectedId ? bfsNeighborhood(graph, selectedId, 1) : null;

    let visibleNodeCount = 0;
    graph.forEachNode((nodeId, attrs) => {
      const hiddenByType = state.hiddenNodeTypes.has(String(attrs.node_type || ""));
      const hiddenByFocus = focusSet ? !focusSet.has(nodeId) : false;
      const hidden = hiddenByType || hiddenByFocus;
      graph.setNodeAttribute(nodeId, "hidden", hidden);
      graph.removeNodeAttribute(nodeId, "dimmed");
      if (!hidden) visibleNodeCount += 1;
      graph.setNodeAttribute(nodeId, "is_selected", selectedId ? nodeId === selectedId : false);
      graph.setNodeAttribute(
        nodeId,
        "is_pinned",
        !!(state.pinSelected && selectedId && nodeId === selectedId),
      );
      graph.setNodeAttribute(
        nodeId,
        "is_focus_neighbor",
        !!(selectedNeighbors && nodeId !== selectedId && selectedNeighbors.has(nodeId)),
      );
    });

    const containsCandidates = [];
    let eligibleEdgeCount = 0;
    let containsBudget = Number.POSITIVE_INFINITY;

    graph.forEachEdge((edgeId, attrs, sourceId, targetId) => {
      const hiddenByType = state.hiddenEdgeTypes.has(String(attrs.label || ""));
      const hiddenByCrossFile = state.crossFileOnly && !attrs.is_cross_file;
      const hiddenByTether = !state.showContextTethers && !!attrs.is_context_tether;
      const hiddenByNode =
        (graph.hasNode(sourceId) && graph.getNodeAttribute(sourceId, "hidden")) ||
        (graph.hasNode(targetId) && graph.getNodeAttribute(targetId, "hidden"));
      const baseHidden = hiddenByType || hiddenByCrossFile || hiddenByTether || hiddenByNode;
      if (baseHidden) return;
      eligibleEdgeCount += 1;
      if (String(attrs.label || "") === "contains") {
        containsCandidates.push(edgeId);
      }
    });

    if (eligibleEdgeCount > 200) {
      containsBudget = Math.max(12, Math.floor(eligibleEdgeCount * 0.12));
    } else if (eligibleEdgeCount > 160) {
      containsBudget = Math.max(16, Math.floor(eligibleEdgeCount * 0.18));
    } else if (eligibleEdgeCount > 120) {
      containsBudget = Math.max(22, Math.floor(eligibleEdgeCount * 0.26));
    } else if (eligibleEdgeCount > 80) {
      containsBudget = Math.max(28, Math.floor(eligibleEdgeCount * 0.4));
    }
    const denseCrossingScene = eligibleEdgeCount >= 96;

    const containsKeep = new Set();
    if (Number.isFinite(containsBudget) && containsCandidates.length > containsBudget) {
      if (selectedNeighbors) {
        for (const edgeId of containsCandidates) {
          const sourceId = graph.source(edgeId);
          const targetId = graph.target(edgeId);
          if (selectedNeighbors.has(sourceId) && selectedNeighbors.has(targetId)) {
            containsKeep.add(edgeId);
          }
        }
      }
      for (const edgeId of containsCandidates) {
        if (containsKeep.size >= containsBudget) break;
        containsKeep.add(edgeId);
      }
    } else {
      for (const edgeId of containsCandidates) {
        containsKeep.add(edgeId);
      }
    }

    let hiddenByThinningCount = 0;
    let visibleEdgeCount = 0;
    graph.forEachEdge((edgeId, attrs, sourceId, targetId) => {
      const label = String(attrs.label || "");
      const highSignal = HIGH_SIGNAL_EDGE_TYPES.has(label) || !!attrs.is_cross_file;
      const hiddenByType = state.hiddenEdgeTypes.has(String(attrs.label || ""));
      const hiddenByCrossFile = state.crossFileOnly && !attrs.is_cross_file;
      const hiddenByTether = !state.showContextTethers && !!attrs.is_context_tether;
      const isContains = label === "contains";
      const hiddenByThinning =
        isContains && Number.isFinite(containsBudget) && !containsKeep.has(edgeId);
      const hiddenByNode =
        (graph.hasNode(sourceId) && graph.getNodeAttribute(sourceId, "hidden")) ||
        (graph.hasNode(targetId) && graph.getNodeAttribute(targetId, "hidden"));
      const hidden = hiddenByType || hiddenByCrossFile || hiddenByTether || hiddenByThinning || hiddenByNode;
      const selectedIncident =
        !!selectedId && (String(sourceId) === String(selectedId) || String(targetId) === String(selectedId));
      const focusIncident =
        !!selectedNeighbors && selectedNeighbors.has(sourceId) && selectedNeighbors.has(targetId);
      const showLabel = !hidden && (selectedIncident || (focusIncident && highSignal));
      graph.setEdgeAttribute(
        edgeId,
        "hidden",
        hidden,
      );
      graph.setEdgeAttribute(edgeId, "show_label", showLabel);
      graph.setEdgeAttribute(edgeId, "is_high_signal", highSignal);
      graph.setEdgeAttribute(edgeId, "dense_scene", denseCrossingScene);
      graph.removeEdgeAttribute(edgeId, "dimmed");
      graph.setEdgeAttribute(edgeId, "size", highSignal ? 2.2 : (denseCrossingScene ? 0.72 : 0.95));
      graph.setEdgeAttribute(
        edgeId,
        "color",
        highSignal
          ? edgeBaseColor(label, !!attrs.is_cross_file)
          : (denseCrossingScene ? "#42556e" : "#4f627d"),
      );
      if (!hidden) visibleEdgeCount += 1;
      if (hiddenByThinning) hiddenByThinningCount += 1;
    });

    if (state.selectedNodeId && graph.hasNode(state.selectedNodeId)) {
      const keep = selectedNeighbors || bfsNeighborhood(graph, state.selectedNodeId, 1);
      graph.forEachNode((nodeId) => {
        graph.setNodeAttribute(nodeId, "dimmed", !keep.has(nodeId));
      });
      graph.forEachEdge((edgeId, attrs, sourceId, targetId) => {
        if (attrs.hidden) return;
        if (!keep.has(sourceId) || !keep.has(targetId)) {
          graph.setEdgeAttribute(edgeId, "dimmed", true);
        }
      });
    }

    state.visibilityStats = {
      totalNodes: graph.order,
      visibleNodes: visibleNodeCount,
      totalEdges: graph.size,
      visibleEdges: visibleEdgeCount,
      hiddenByThinning: hiddenByThinningCount,
      focusMode: state.focusMode,
    };

    renderer.refresh();
  }

  function selectNode(nodeId) {
    state.selectedNodeId = nodeId == null ? null : String(nodeId);
    applyVisibility();
  }

  function clearSelection() {
    state.selectedNodeId = null;
    state.pinSelected = false;
    applyVisibility();
  }

  function setFocusMode(mode) {
    state.focusMode = mode;
    applyVisibility();
  }

  function toggleNodeType(type) {
    if (state.hiddenNodeTypes.has(type)) state.hiddenNodeTypes.delete(type);
    else state.hiddenNodeTypes.add(type);
    applyVisibility();
  }

  function toggleEdgeType(type) {
    if (state.hiddenEdgeTypes.has(type)) state.hiddenEdgeTypes.delete(type);
    else state.hiddenEdgeTypes.add(type);
    applyVisibility();
  }

  function toggleCrossFileOnly() {
    state.crossFileOnly = !state.crossFileOnly;
    applyVisibility();
  }

  function toggleContextTethers() {
    state.showContextTethers = !state.showContextTethers;
    applyVisibility();
  }

  function togglePin() {
    state.pinSelected = !state.pinSelected;
    applyVisibility();
    return state.pinSelected;
  }

  function searchNode(query) {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return null;
    let winner = null;
    graph.forEachNode((nodeId, attrs) => {
      if (winner) return;
      const haystack = [nodeId, attrs.label, attrs.node_name, attrs.full_name, attrs.file_path]
        .filter(Boolean)
        .join("\n")
        .toLowerCase();
      if (haystack.includes(q)) winner = nodeId;
    });
    return winner;
  }

  function getState() {
    return {
      ...state,
      hiddenNodeTypes: new Set(state.hiddenNodeTypes),
      hiddenEdgeTypes: new Set(state.hiddenEdgeTypes),
    };
  }

  function getVisibilityStats() {
    return {
      ...state.visibilityStats,
    };
  }

  return {
    applyVisibility,
    selectNode,
    clearSelection,
    setFocusMode,
    toggleNodeType,
    toggleEdgeType,
    toggleCrossFileOnly,
    toggleContextTethers,
    togglePin,
    searchNode,
    getState,
    getVisibilityStats,
  };
}
