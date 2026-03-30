function escHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function pretty(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch (_err) {
    return String(value);
  }
}

export function createPanels(doc = document) {
  const nodeNameEl = doc.getElementById("node-name");
  const nodeDetailsEl = doc.getElementById("node-details");
  const agentHeaderEl = doc.getElementById("agent-header");
  const agentStreamEl = doc.getElementById("agent-stream");
  const eventsEl = doc.getElementById("events");
  const timelineEl = doc.getElementById("timeline-container");
  const statusEl = doc.getElementById("connection-status");
  const selectionHelperEl = doc.getElementById("selection-helper");
  const summaryVisibleNodesEl = doc.getElementById("summary-visible-nodes");
  const summaryVisibleEdgesEl = doc.getElementById("summary-visible-edges");
  const summaryHiddenThinningEl = doc.getElementById("summary-hidden-thinning");
  const summaryFocusModeEl = doc.getElementById("summary-focus-mode");
  const quickPinEl = doc.getElementById("quick-pin-toggle");
  const quickFullEl = doc.getElementById("quick-focus-full");
  const quickHop1El = doc.getElementById("quick-focus-hop1");
  const quickHop2El = doc.getElementById("quick-focus-hop2");
  const inspectBarEl = doc.getElementById("node-inspect-bar");

  function showConnectionStatus(connected) {
    if (!statusEl) return;
    statusEl.classList.toggle("connected", connected);
    statusEl.classList.toggle("disconnected", !connected);
  }

  function setNode(node) {
    if (nodeNameEl) {
      nodeNameEl.textContent = node ? (node.full_name || node.name || node.node_id) : "Select a node";
    }
    if (!nodeDetailsEl) return;
    if (!node) {
      if (selectionHelperEl) selectionHelperEl.style.display = "";
      if (inspectBarEl) inspectBarEl.style.display = "none";
      nodeDetailsEl.innerHTML = "";
      return;
    }
    if (selectionHelperEl) selectionHelperEl.style.display = "none";
    if (inspectBarEl) inspectBarEl.style.display = "";
    const summary = [
      `id: ${node.node_id}`,
      `type: ${node.node_type}`,
      `status: ${node.status || "idle"}`,
      `file: ${node.file_path || ""}`,
      `lines: ${node.start_line ?? "?"}-${node.end_line ?? "?"}`,
    ].join("\n");
    nodeDetailsEl.innerHTML = `<pre>${escHtml(summary)}\n\n${escHtml(node.text || "")}</pre>`;
  }

  function setAgentHeader(text) {
    if (agentHeaderEl) agentHeaderEl.textContent = text;
  }

  function appendAgentItem(kind, title, body) {
    if (!agentStreamEl) return;
    const block = doc.createElement("div");
    block.className = `panel-item ${kind}`;
    const head = doc.createElement("div");
    head.className = "panel-meta";
    head.textContent = title;
    const content = doc.createElement("div");
    content.textContent = body;
    block.appendChild(head);
    block.appendChild(content);
    agentStreamEl.prepend(block);
  }

  function setConversation(messages) {
    if (!agentStreamEl) return;
    agentStreamEl.innerHTML = "";
    for (const item of messages || []) {
      const role = String(item.role || "agent");
      const kind = role === "user" ? "panel-user" : "panel-agent";
      appendAgentItem(kind, role, String(item.content || ""));
    }
  }

  function appendEventLine(line) {
    if (!eventsEl) return;
    const lines = eventsEl.textContent ? eventsEl.textContent.split("\n") : [];
    lines.push(line);
    eventsEl.textContent = lines.slice(-120).join("\n");
    eventsEl.scrollTop = eventsEl.scrollHeight;
  }

  function addTimelineEvent(type, payload) {
    if (!timelineEl) return;
    const row = doc.createElement("div");
    row.className = `timeline-event type-${type}`;
    const kind = doc.createElement("div");
    kind.className = "timeline-type";
    kind.textContent = type;
    const meta = doc.createElement("div");
    meta.className = "timeline-meta";
    meta.textContent = pretty(payload);
    row.appendChild(kind);
    row.appendChild(meta);
    timelineEl.prepend(row);
    while (timelineEl.childElementCount > 120) {
      timelineEl.removeChild(timelineEl.lastElementChild);
    }
  }

  function clearNodeSelection() {
    setNode(null);
    setAgentHeader("(select a node)");
  }

  function setGraphSummary(summary) {
    if (summaryVisibleNodesEl) summaryVisibleNodesEl.textContent = String(summary?.visibleNodes ?? 0);
    if (summaryVisibleEdgesEl) summaryVisibleEdgesEl.textContent = String(summary?.visibleEdges ?? 0);
    if (summaryHiddenThinningEl) summaryHiddenThinningEl.textContent = String(summary?.hiddenByThinning ?? 0);
    if (summaryFocusModeEl) summaryFocusModeEl.textContent = String(summary?.focusMode ?? "full");
  }

  function setQuickActionsState({ hasSelection = false, pinSelected = false, focusMode = "full" } = {}) {
    if (quickPinEl) {
      quickPinEl.disabled = !hasSelection;
      quickPinEl.textContent = pinSelected ? "Unpin selected" : "Pin selected";
      quickPinEl.classList.toggle("active", pinSelected);
    }
    if (quickHop1El) {
      quickHop1El.disabled = !hasSelection;
      quickHop1El.classList.toggle("active", focusMode === "hop1");
    }
    if (quickHop2El) {
      quickHop2El.disabled = !hasSelection;
      quickHop2El.classList.toggle("active", focusMode === "hop2");
    }
    if (quickFullEl) {
      quickFullEl.disabled = false;
      quickFullEl.classList.toggle("active", focusMode === "full");
    }
  }

  return {
    showConnectionStatus,
    setNode,
    setAgentHeader,
    appendAgentItem,
    setConversation,
    appendEventLine,
    addTimelineEvent,
    clearNodeSelection,
    setGraphSummary,
    setQuickActionsState,
  };
}
