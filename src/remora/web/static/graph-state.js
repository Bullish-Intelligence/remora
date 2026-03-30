export function createGraphState() {
  const nodesById = new Map();
  const edgesByKey = new Map();

  function edgeKey(edge) {
    if (!edge) return "";
    if (edge.id) return String(edge.id);
    return `${String(edge.from_id)}|${String(edge.edge_type)}|${String(edge.to_id)}`;
  }

  function upsertNode(node) {
    if (!node || !node.node_id) return false;
    const nodeId = String(node.node_id);
    const previous = nodesById.get(nodeId);
    nodesById.set(nodeId, { ...(previous || {}), ...node, node_id: nodeId });
    return previous == null;
  }

  function upsertEdge(edge) {
    const key = edgeKey(edge);
    if (!key) return false;
    const previous = edgesByKey.get(key);
    edgesByKey.set(key, { ...(previous || {}), ...edge, __key: key });
    return previous == null;
  }

  function removeNode(nodeId) {
    const id = String(nodeId);
    const existed = nodesById.delete(id);
    if (!existed) return false;
    for (const [key, edge] of edgesByKey.entries()) {
      if (String(edge.from_id) === id || String(edge.to_id) === id) {
        edgesByKey.delete(key);
      }
    }
    return true;
  }

  function removeEdge(edgeOrKey) {
    const key = typeof edgeOrKey === "string" ? edgeOrKey : edgeKey(edgeOrKey);
    if (!key) return false;
    return edgesByKey.delete(key);
  }

  function applySnapshot(nodes, edges) {
    nodesById.clear();
    edgesByKey.clear();
    for (const node of nodes || []) upsertNode(node);
    for (const edge of edges || []) upsertEdge(edge);
  }

  function snapshot() {
    return {
      nodes: Array.from(nodesById.values()),
      edges: Array.from(edgesByKey.values()),
    };
  }

  return {
    nodesById,
    edgesByKey,
    edgeKey,
    upsertNode,
    upsertEdge,
    removeNode,
    removeEdge,
    applySnapshot,
    snapshot,
  };
}
