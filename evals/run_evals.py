"""Golden-set evaluation. Offline by default; with ANTHROPIC_API_KEY set it runs the
live models and adds an LLM-as-judge score from the deep model.

    python -m evals.run_evals            # prints a table, exits 1 if below threshold
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from agent import adapters, config, db
from agent.pipeline import SupportAgent
from agent.safety import sign_session
from agent.telemetry import Tracer

THRESHOLD = 0.90
JUDGE_PROMPT = """Score this customer-support reply from 1 to 5 on each of: helpful, accurate
(against the facts), tone, safe. Reply as JSON {"helpful":n,"accurate":n,"tone":n,"safe":n}."""


async def judge(text: str, reply: str, facts: dict) -> dict:
    from anthropic import AsyncAnthropic
    msg = await AsyncAnthropic().messages.create(
        model=config.MODEL_DEEP, max_tokens=200, system=JUDGE_PROMPT,
        messages=[{"role": "user", "content": f"Customer: {text}\nFacts: {json.dumps(facts)}\nReply: {reply}"}])
    return json.loads(msg.content[0].text)


async def run_case(case: dict) -> dict:
    conn = db.connect(":memory:")
    db.init_db(conn)
    agent = SupportAgent(conn, tracer=Tracer(Path("eval_traces.jsonl")), retry_delay=0)
    req = adapters.from_chat({"text": case["text"], "session_id": case["id"]}, case["customer"])
    reply = await agent.handle(req, sign_session(case["customer"]))
    checks = {"route": reply.route.value == case["route"]}
    checks["contains"] = all(s in reply.text for s in case.get("must_contain", []))
    checks["excludes"] = not any(s in reply.text for s in case.get("must_not_contain", []))
    out = {"id": case["id"], "pass": all(checks.values()), **checks, "route_got": reply.route.value}
    if config.LIVE:
        out["judge"] = await judge(case["text"], reply.text, reply.facts)
    return out


def main(path: str = "evals/golden.jsonl") -> int:
    cases = [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
    results = [asyncio.run(run_case(c)) for c in cases]
    for r in results:
        print(f"{r['id']}  {'PASS' if r['pass'] else 'FAIL'}  route={r['route_got']:<9} "
              f"contains={r['contains']} excludes={r['excludes']} {r.get('judge', '')}")
    score = sum(r["pass"] for r in results) / len(results)
    print(f"\npass rate {score:.0%} (threshold {THRESHOLD:.0%}, mode={'live' if config.LIVE else 'offline'})")
    return 0 if score >= THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
