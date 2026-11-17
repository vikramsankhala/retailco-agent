"""Service levels from traces (Module 18).

An SLI (service level indicator) is a measurement; an SLO (objective) is the
target for it; the error budget is how far below target you may run before you
stop shipping changes and fix reliability instead. The SLIs here are computed
from the one "request" record the pipeline writes per conversation, so they are
the same numbers in a lab, in CI and in production.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import config


def load_requests(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("name") == "request":
            out.append(r)
    return out


def load_spans(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def compute(path: Path) -> dict:
    reqs, spans = load_requests(path), load_spans(path)
    n = len(reqs)
    if n == 0:
        return {"requests": 0}
    human = sum(1 for r in reqs if r["attributes"].get("needs_human") or r["attributes"].get("route") == "escalate")
    lat = [r["duration_ms"] for r in reqs]
    checks = [s for s in spans if s["name"] == "L11.result_check"]
    failed_checks = sum(1 for s in checks if not s["attributes"].get("passed"))
    intents: dict[str, int] = {}
    for r in reqs:
        key = r["attributes"].get("intent") or "unknown"
        intents[key] = intents.get(key, 0) + 1
    return {
        "requests": n,
        "containment": 1 - human / n,
        "escalation_rate": human / n,
        "p50_latency_ms": percentile(lat, 0.50),
        "p95_latency_ms": percentile(lat, 0.95),
        "cost_per_contact_gbp": sum(r["attributes"].get("est_cost_gbp", 0) for r in reqs) / n,
        "verifier_fail_rate": failed_checks / max(1, len(checks)),
        "intents": intents,
    }


@dataclass
class Objective:
    sli: str
    target: float
    higher_is_better: bool

    def met(self, value: float) -> bool:
        return value >= self.target if self.higher_is_better else value <= self.target


OBJECTIVES = [
    Objective("containment", config.SLO["containment"], True),
    Objective("p95_latency_ms", config.SLO["p95_latency_ms"], False),
    Objective("cost_per_contact_gbp", config.SLO["cost_per_contact_gbp"], False),
    Objective("escalation_rate", config.SLO["escalation_rate_max"], False),
    Objective("verifier_fail_rate", config.SLO["verifier_fail_rate_max"], False),
]


def error_budget(containment: float, target: float = config.SLO["containment"]) -> dict:
    """Containment budget: with a 75% target, up to 25% of contacts may go to people.
    burn = share of that allowance used; above 1.0 the objective is missed."""
    allowed = 1 - target
    used = 1 - containment
    return {"allowed": allowed, "used": used, "burn": used / allowed if allowed else float("inf")}


def evaluate(sli: dict) -> list[dict]:
    return [{"sli": o.sli, "value": sli.get(o.sli, 0.0), "target": o.target,
             "met": o.met(sli.get(o.sli, 0.0)), "direction": ">=" if o.higher_is_better else "<="}
            for o in OBJECTIVES]
