---
name: add-tool
description: Add a new business tool to the RetailCo agent end to end (function, registry, MCP wrapper, guard, test). Use when asked to add, expose or wire up a tool.
---
# Adding a tool

1. Write the business function in `agent/tools.py`. First line: ownership check via `_own_order`
   or `current_customer`. Writes take `idempotency_key` and respect `config.kill_switch_on()`.
2. Add it to `REGISTRY` with its risk class (read, compute, write, delegate) and required args.
3. Expose it in `agent/mcp_tools.py` with a description that says WHEN to use it, and return
   `_err(e)` on ToolError so the model can self-correct.
4. Add it to `pipeline.SupportAgent.dispatch`.
5. If it writes: add it to `guards.WRITE_TOOLS` and add any limit check to `pre_tool_guard`.
6. Tests: ownership, idempotency (for writes), guard decision, and one end-to-end case.
7. Add at least two golden cases to `evals/golden.jsonl`. Run `/eval`.
