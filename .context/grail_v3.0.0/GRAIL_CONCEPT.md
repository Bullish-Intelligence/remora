# Grail Concepts

This document provides a high-level overview of Grail's core concepts. For detailed usage instructions, see [HOW_TO_USE_GRAIL.md](HOW_TO_USE_GRAIL.md).

## What is Grail?

Grail is a transparent wrapper around Monty, a secure Python interpreter written in Rust. It provides:

- **`.pym` files** — A dedicated file format for Monty code with full IDE support
- **`grail check`** — CLI validation against Monty's limitations before runtime
- **`.grail/` directory** — Transparent, inspectable generated artifacts
- **Minimal host API** — `grail.load()` → `script.run()`, nothing more

## The Pipeline

```
.pym file
   │
   ├─ 1. Parse ──────────── Extract @external specs, Input() specs, AST
   │
   ├─ 2. Check ──────────── Validate Monty compatibility (E001–E012)
   │                         Validate declarations (E006–E008)
   │                         Check warnings (W001–W004)
   │
   ├─ 3. Generate stubs ─── .pyi stubs for Monty's type checker
   │
   ├─ 4. Generate code ─── Strip declarations, produce clean Monty code
   │                         Build source map (.pym line ↔ Monty line)
   │
   └─ 5. Execute ─────────── Run in Monty sandbox with inputs + externals
                               Map errors back to .pym line numbers
```

## Key Design Decisions

### Why `.pym` and not just `.py`?

- Clear signal: "this file runs in Monty, not CPython"
- Enables file-type-specific linting rules
- Prevents accidental execution with `python script.pym`

### Why `from grail import external, Input`?

- It's valid Python — IDEs understand it
- `@external` decorated functions provide real type information
- `Input()` calls have a real return type for IDE support
- No custom parser needed — Grail reads it with Python's own `ast` module

### What `@external` means

- Declares that this function is provided by the host at runtime
- The signature becomes the type stub
- The `...` body is never executed — it's a declaration

### What `Input()` means

- Declares a named input variable that the host provides at runtime
- The type annotation provides type checking
- Optional `default` parameter for optional inputs

## Philosophy

**Monty is a limited Python runtime, and Grail should make those limitations visible and manageable — not hide them behind abstractions.**

Grail v3 explicitly removes:
- Complex resource policy inheritance
- Filesystem abstraction layers
- Generic observability (logging, metrics)
- God objects with many parameters

Grail v3 provides:
- Flat, simple resource limits
- Dict-based filesystem configuration
- Optional event callbacks (not forced)
- Minimal API (~15 public symbols)

## When to Use Grail

Grail is ideal for:
- **Policy evaluation:** "Given these inputs, should we approve this request?"
- **Data transformation:** "Take this data, apply these rules, return a summary."
- **Workflow orchestration:** "Fetch from A, then B, combine, decide, return."
- **Report generation logic:** "Query expenses, compare to budget, flag anomalies."
- **Configurable business rules:** "Apply discount logic that end-users can customize."

## What's Not Included

Grail is intentionally minimal. It doesn't provide:
- Generic logging or metrics (use stdlib `logging` or your preferred observability)
- Retry logic (use `tenacity` or custom code)
- Complex policy systems (flat limits are enough)
- Custom filesystem hooks (use external functions instead)

## Getting Started

1. Install: `pip install grail`
2. Initialize: `grail init`
3. Write a `.pym` file
4. Load and run from your Python code

See [HOW_TO_USE_GRAIL.md](HOW_TO_USE_GRAIL.md) for complete documentation.
