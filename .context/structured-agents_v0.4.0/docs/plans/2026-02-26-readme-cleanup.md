# README Cleanup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove outdated README sections and align Client Reuse with current `build_client` usage.

**Architecture:** Documentation-only changes in `README.md`, with verification against `build_client` usage in the codebase to ensure the example reflects the current factory signature.

**Tech Stack:** Markdown documentation, Python references in `src/structured_agents`.

---

### Task 1: Confirm current client factory usage

**Files:**
- Review: `README.md`
- Review: `src/structured_agents/client/openai.py`
- Review: `src/structured_agents/agent.py`

**Step 1: Read the README client reuse section**

Confirm the current snippet and section placement.

**Step 2: Inspect the client factory signature**

Verify `build_client` expects a config dictionary and which keys it reads.

**Step 3: Check in-repo usage of `build_client`**

Confirm `build_client` is called with a dict in production code.

**Step 4: Decide whether to keep or update the section**

Plan to keep Client Reuse only if it can be updated to match the dict-based signature.

**Step 5: Skip commit**

No commit per request.

### Task 2: Update README sections

**Files:**
- Modify: `README.md`

**Step 1: Remove the Tool Sources section**

Delete the entire section and code sample.

**Step 2: Remove the Bundles section**

Delete the entire section and code sample.

**Step 3: Update Client Reuse snippet to match `build_client`**

```python
from structured_agents.client import build_client

client = build_client({
    "base_url": "http://localhost:8000/v1",
    "api_key": "EMPTY",
    "model": "test",
})
```

**Step 4: Check section flow and spacing**

Ensure headings flow cleanly from Quick Start into Parallel Tool Execution, then Client Reuse.

**Step 5: Skip commit**

No commit per request.
