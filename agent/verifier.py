"""Layer 11 - Result check: did we finish, is every claim grounded, is it within policy?

The grounding check is deliberately mechanical: every money amount and every
reference id in the reply must appear in the tool results. A reply that says
£47.99 when the refund tool returned 47.99 passes; one that invents £50 fails.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import config
from .taskqueue import RunResult, State

_MONEY = re.compile(r"£\s?(\d+(?:\.\d{1,2})?)")
_IDS = re.compile(r"\b(?:REF|ORD|ZD)-[A-Z0-9-]*\d\b")
_CLAIMS_REFUND = re.compile(r"\brefund (has been|was|is) (processed|issued)|\bI'?ve (processed|issued) .{0,20}refund", re.I)


@dataclass
class Verdict:
    passed: bool
    problems: list[str] = field(default_factory=list)
    confidence: float = 1.0
    hard_stop: bool = False   # policy violation: never retry, escalate


def check_run(run: RunResult) -> list[str]:
    return [f"step {k} {r.state.value}: {r.error}" for k, r in run.runs.items()
            if r.state is State.FAILED]


def check_policy(facts: dict) -> list[str]:
    problems = []
    refund = facts.get("refund") or {}
    if refund.get("amount", 0) > config.REFUND_APPROVAL_LIMIT_GBP and not refund.get("approved_by") \
            and not refund.get("replayed"):
        problems.append("refund above approval limit issued without approval")
    return problems


def check_grounding(reply: str, facts: dict) -> list[str]:
    haystack = json.dumps(facts)
    numbers = {f"{float(v):.2f}" for v in re.findall(r"\d+\.\d+|\d+", haystack)}
    problems = []
    for amount in _MONEY.findall(reply):
        if f"{float(amount):.2f}" not in numbers:
            problems.append(f"amount £{amount} not supported by tool results")
    for ref in _IDS.findall(reply):
        if ref not in haystack:
            problems.append(f"reference {ref} not supported by tool results")
    if _CLAIMS_REFUND.search(reply) and not (facts.get("refund") or {}).get("refund_id"):
        problems.append("reply claims a refund that no tool issued")
    return problems


def verify(reply: str, facts: dict, run: RunResult | None = None) -> Verdict:
    policy = check_policy(facts)
    if policy:
        return Verdict(False, policy, 0.0, hard_stop=True)
    problems = (check_run(run) if run else []) + check_grounding(reply, facts)
    return Verdict(not problems, problems, 1.0 if not problems else 0.4)
