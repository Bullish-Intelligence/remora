Here is a fully rewritten **AGENTS.md** optimized for fast, reliable agent execution and deterministic use of the `context_library_lookup` skill.

---

# AGENTS.md

## Scope

These rules apply to the entire repository.

They are optimized for:

* Deterministic behavior
* Minimal diff footprint
* Fast dependency introspection (vLLM + xgrammar)
* Reliable use of vendored library sources under `.context/`

---

# Execution Model

## 1. Change Philosophy

* Make the smallest correct change.
* Do not refactor unrelated code.
* Do not rename symbols unless required.
* Do not rewrite files when a surgical edit is sufficient.
* Preserve existing formatting and import order.
* Maintain full type safety and mypy compatibility.

If a change requires architectural modification, justify it explicitly in reasoning before implementation.

---

# Dependency Introspection (CRITICAL)

## vLLM and xgrammar Handling

This repository vendors the exact versions of:

```
.context/vllm/
.context/xgrammar/
```

You MUST treat these as the source of truth.

### Mandatory Rule

When a question involves:

* Grammar-constrained decoding
* Token masking / logits processing
* Sampling parameters
* Engine behavior
* KV cache / scheduler
* API server behavior
* Model execution internals
* CUDA kernel paths
* Any symbol not defined inside this repo but imported

You MUST:

1. Use the `context_library_lookup` skill.
2. Ground your answer in `.context/`.
3. Cite file paths and line ranges.
4. Prefer docs → implementation → tests.

Do NOT:

* Use upstream GitHub knowledge
* Assume latest public behavior
* Answer from memory

All dependency behavior must be verifiable from `.context/`.

### Required Dependencies

vLLM and xgrammar are required for this repo. Do not add runtime fallbacks or try/except branches for missing dependencies. Fail fast at startup with a clear install message if they are unavailable.

---

# Skill Usage Protocol

When vLLM or xgrammar behavior is involved:

1. Identify which library owns the symbol.
2. Invoke `context_library_lookup`.
3. Extract:

   * Canonical definition
   * Relevant docstring
   * Minimal implementation excerpt
4. Cite exact file path and lines.
5. Explain behavior based strictly on cited source.

If multiple versions exist, verify which one matches repo configuration.

This is mandatory, not optional.

---

# Code Standards

## Typing

* All new Python code must be fully typed.
* Avoid `Any` unless unavoidable.
* Maintain mypy cleanliness.
* Preserve strict typing patterns used in the repo.

## Structure

* Keep modules cohesive.
* Avoid cross-module coupling unless required.
* Do not introduce circular imports.
* Prefer explicit imports.
* Store Grail `.pym` scripts under `agents/` (not the repo root).

## Edits

* Use targeted edits.
* Avoid large rewrites.
* Do not change unrelated whitespace.
* Do not reorder code unnecessarily.

---

# Testing Policy

When modifying or adding functionality:

* Add or update tests in `tests/`.
* Prefer focused tests covering only changed behavior.
* Avoid broad snapshot-style tests.
* Keep tests deterministic.
* Do not modify unrelated tests.

If behavior is derived from vLLM/xgrammar internals, ensure tests align with the vendored implementation.

---

# Documentation Policy

* Update `README.md` only if explicitly requested.
* Keep docstrings concise and purpose-driven.
* Do not restate obvious behavior.
* Avoid duplicating vendored library documentation.

---

# Performance Guidelines

* Prefer local reasoning over scanning the entire repo.
* When searching `.context/`, narrow scope to the correct library.
* Use exact symbol searches.
* Avoid repeated global searches.

---

# Anti-Patterns

Never:

* Fabricate dependency behavior
* Assume public API stability
* Copy large blocks of vendored code unnecessarily
* Perform speculative refactors
* Modify formatting-only sections

---

# Decision Hierarchy

When resolving behavior questions:

1. This repository’s source
2. `.context/xgrammar/`
3. `.context/vllm/`
4. Local tests
5. Only if absent: explicitly state missing information

---

# Goal

Produce:

* Minimal diffs
* Fully typed code
* Deterministic dependency grounding
* Verifiable answers using vendored sources
* High signal, low noise modifications

The agent must prioritize correctness, traceability, and minimal change surface area at all times.
