# RetailCo Support Agent

Customer-support agent for RetailCo (UK e-commerce). Resolves tier-1/2 requests:
order tracking, late-delivery refunds (up to £200 without approval), full-order returns,
address changes and policy questions. Architecture: 13 layers, one module per layer in `agent/`.

## Commands
- Tests: `python -m pytest -q` (must stay green; never call a model in tests)
- Golden-set evals: `python -m evals.run_evals` (offline unless ANTHROPIC_API_KEY is set)
- Run the API: `uvicorn agent.api:app --reload`
- Seed a fresh database: `python -m scripts.seed`

## Layer map
L1 adapters.py · L2 safety.py + guards.py · L3 understanding.py · L4 memory.py · L5 reasoning.py
L6 router.py · L7 planner.py · L8 taskqueue.py · L9 tools.py · L10 mcp_tools.py
L11 verifier.py · L12 output.py · L13 telemetry.py · wiring: pipeline.py

## Rules that must never break
- Ownership checks use `tools.current_customer`, never an id from model output.
- Every write tool takes an idempotency key; refunds use `refund:<order_id>`.
- Refunds above `config.REFUND_APPROVAL_LIMIT_GBP` go through `request_approval`, enforced
  in tools.py AND guards.py. Do not remove either check.
- The customer-facing agent gets `tools=[]` (no built-in tools) and only `mcp__retailco__*`.
- Every customer-visible amount or reference must pass `verifier.check_grounding`.
- Thresholds live in `config.py` only.

## How to work in this repo
- Plan first for anything touching more than one layer (Shift+Tab twice for plan mode).
- Write or update the test before the code; run the suite after every change.
- New tool: use the `add-tool` skill. Security-sensitive change: ask the `security-reviewer` subagent.
- British English in customer-facing text. Model ids come from config.py.
