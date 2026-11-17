"""Service-level report from a trace file. Exits 1 if any objective is missed,
so it can gate a canary promotion or a release.

    python -m scripts.slo_report                 # uses traces.jsonl
    python -m scripts.slo_report eval_traces.jsonl
"""
from __future__ import annotations

import sys
from pathlib import Path

from agent import config
from agent.slo import compute, error_budget, evaluate


def fmt(name: str, v: float) -> str:
    if "latency" in name:
        return f"{v:,.0f} ms"
    if "gbp" in name:
        return f"£{v:.4f}"
    return f"{v:.1%}"


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else config.TRACE_FILE
    sli = compute(path)
    if not sli["requests"]:
        print(f"no requests in {path}")
        return 1
    print(f"{sli['requests']} requests from {path}\n")
    print(f"{'SLI':24s}{'value':>14s}{'objective':>16s}  status")
    rows = evaluate(sli)
    for r in rows:
        print(f"{r['sli']:24s}{fmt(r['sli'], r['value']):>14s}{r['direction'] + ' ' + fmt(r['sli'], r['target']):>16s}  "
              f"{'met' if r['met'] else 'MISSED'}")
    b = error_budget(sli["containment"])
    print(f"\ncontainment error budget: {b['used']:.1%} of contacts went to people; allowance {b['allowed']:.0%}; "
          f"burn {b['burn']:.2f}")
    print("cost is an estimate from the example prices in config.py")
    return 0 if all(r["met"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
