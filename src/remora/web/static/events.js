export function createEventStream({ onBatch, onConnectionChange, batchWindowMs = 75 } = {}) {
  let source = null;
  let timerId = null;
  const queue = [];

  function flush() {
    timerId = null;
    if (queue.length === 0) return;
    const batch = queue.splice(0, queue.length);
    if (typeof onBatch === "function") onBatch(batch);
  }

  function queueEvent(type, envelope) {
    queue.push({ type, envelope, payload: envelope?.payload || {} });
    if (timerId != null) return;
    timerId = setTimeout(flush, batchWindowMs);
  }

  function parseEnvelope(raw) {
    try {
      return JSON.parse(raw || "{}");
    } catch (_err) {
      return { payload: {} };
    }
  }

  function start(url = "/sse") {
    if (source) return;
    source = new EventSource(url);
    const eventTypes = [
      "node_discovered",
      "node_removed",
      "node_changed",
      "agent_start",
      "agent_complete",
      "agent_error",
      "agent_message",
      "human_input_request",
      "human_input_response",
      "rewrite_proposal",
      "rewrite_accepted",
      "rewrite_rejected",
      "cursor_focus",
      "content_changed",
    ];

    source.onopen = () => {
      if (typeof onConnectionChange === "function") onConnectionChange(true);
    };

    source.onerror = () => {
      if (typeof onConnectionChange === "function") onConnectionChange(false);
    };

    for (const eventType of eventTypes) {
      source.addEventListener(eventType, (event) => {
        queueEvent(eventType, parseEnvelope(event.data));
      });
    }

    source.addEventListener("message", (event) => {
      queueEvent("message", parseEnvelope(event.data));
    });
  }

  function stop() {
    if (timerId != null) {
      clearTimeout(timerId);
      timerId = null;
    }
    queue.length = 0;
    if (source) {
      source.close();
      source = null;
    }
  }

  return { start, stop };
}
