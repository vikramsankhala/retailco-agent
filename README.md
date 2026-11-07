# RetailCo Support Agent

Reference build for the Solinexta AI programme **Build a Production AI Agent with Claude Code**.

The programme starts with a business case, *RetailCo: Automating the Front Line*, and a strategy evaluation of five options. It then builds the option the analysis recommends: a customer-support agent with thirteen architectural layers, written and tested with Claude Code. Every lab in the programme ends at a state of this repository.

- Programme (web edition): https://claude.ai/artifact/VX3emZwS8hyJr6z1bLtx1e
- Case study: [`docs/case/RetailCo-Case-Study.pdf`](docs/case/RetailCo-Case-Study.pdf)
- Case analysis: [`docs/case/RetailCo-Case-Analysis.pdf`](docs/case/RetailCo-Case-Analysis.pdf) (read after the strategy session)

## Quick start

```bash
git clone https://github.com/vikramsankhala/retailco-agent.git
cd retailco-agent
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"

python -m scripts.seed               # create the sample database
python -m pytest -q                  # 30 tests, no API key needed
python -m evals.run_evals            # 12 golden-set cases, offline
python -m strategy.model             # Lab 0: the case's strategy evaluation
python -m scripts.chat CUST-4821     # talk to the agent in your terminal
```

Set `ANTHROPIC_API_KEY` to switch understanding, reasoning and model-generated plans from the offline fallbacks to Claude (Haiku for classification, Sonnet for reasoning and replies, Opus as the evaluation judge). Run the HTTP API with `uvicorn agent.api:app --reload` and open http://127.0.0.1:8000/docs.

## Where each lab lands

| Lab | Programme module | Layer | Files |
|---|---|---|---|
| 0 | 1 · Evaluate the strategy | Case | `strategy/model.py`, `tests/test_strategy_model.py` |
| 1 | 1 · Define success | 0 | `docs/problem-brief.md`, `evals/golden.jsonl` |
| 2 | 2 · Claude Code workshop | — | `CLAUDE.md`, `.claude/` (settings, commands, subagents, skill) |
| 3 | 4 · Input | L1 | `agent/schemas.py`, `agent/adapters.py` |
| 4 | 5 · Safety and access | L2 | `agent/safety.py`, `agent/guards.py` |
| 5 | 6 · Understanding | L3 | `agent/understanding.py` |
| 6 | 7 · Memory | L4 | `agent/memory.py`, `data/kb/` |
| 7 | 8 · Reasoning and decision gate | L5, L6 | `agent/reasoning.py`, `agent/router.py` |
| 8 | 9 · Planning and task queue | L7, L8 | `agent/planner.py`, `agent/taskqueue.py` |
| 9 | 10 · Tools and MCP | L9, L10 | `agent/tools.py`, `agent/mcp_tools.py` |
| 10 | 11 · Result check and output | L11, L12 | `agent/verifier.py`, `agent/output.py` |
| 11 | 12 · Monitoring and wiring | L13 | `agent/telemetry.py`, `agent/pipeline.py`, `agent/api.py` |
| — | 13 · Evaluate and red-team | — | `evals/run_evals.py`, `.github/workflows/agent-ci.yml` |
| — | 14 · Deploy | — | `Dockerfile` |

## Rules that never break

These come from the risk conditions in the case (Exhibit 17) and are enforced in code, not in the prompt:

1. Customer identity comes from the verified session; every tool checks ownership.
2. Refunds above £200 need a person: enforced in the refund tool and again in a pre-action guard.
3. Every write action carries an idempotency key, so a retry never refunds twice.
4. Every reply is checked: each amount and reference must appear in tool results.
5. Customers are told on the first reply that they are talking to an AI assistant, and can type "person" to reach the team.
6. `RETAILCO_KILL_SWITCH=1` stops every write action at once.

## Sample data

| Order | Customer | Total | Situation on the lab date (5 Nov 2024) |
|---|---|---|---|
| ORD-9821 | Sarah (CUST-4821) | £47.99 | 10 days late: automatic full refund |
| ORD-9822 | Sarah (CUST-4821) | £349.00 | Eligible, above £200: goes to approval |
| ORD-7001 | Arjun (CUST-1002) | £22.50 | Out for delivery; used to test data separation |

RetailCo and all people in the case are fictional. Author: Vikram Singh Sankhala, Solinexta AI · [linkedin.com/in/vikramsankhalaai](https://www.linkedin.com/in/vikramsankhalaai)
