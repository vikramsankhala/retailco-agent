"""A/B comparison with a regression gate (Module 18).

Runs the golden set once per variant, each in its own process so configuration
is read fresh, then compares pass rates, cost and latency case by case.

    python -m evals.compare                       # A = BM25 retriever, B = hybrid (default)
    python -m evals.compare A:RETAILCO_RETRIEVER=hybrid B:MODEL_MAIN=claude-opus-5-5   # live example

Exit code 1 if B fails any case that A passes (a regression), whatever the averages say.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from agent.slo import compute

DEFAULT = {"A": {"RETAILCO_RETRIEVER": "bm25"}, "B": {"RETAILCO_RETRIEVER": "hybrid"}}


def parse(argv: list[str]) -> dict[str, dict]:
    if not argv:
        return DEFAULT
    variants: dict[str, dict] = {}
    for arg in argv:
        name, _, kv = arg.partition(":")
        k, _, v = kv.partition("=")
        variants.setdefault(name, {})[k] = v
    return variants


def run_variant(env_over: dict) -> tuple[dict, dict]:
    traces = Path(tempfile.mkdtemp()) / "traces.jsonl"
    env = os.environ | env_over | {"EVAL_TRACES": str(traces)}
    out = subprocess.run([sys.executable, "-m", "evals.run_evals", "--json"], env=env,
                         capture_output=True, text=True).stdout
    line = next(l for l in out.splitlines() if l.startswith("JSON "))
    cases = {r["id"]: r["pass"] for r in json.loads(line[5:])}
    return cases, compute(traces)


def main(argv: list[str]) -> int:
    variants = parse(argv)
    (a_name, a_env), (b_name, b_env) = list(variants.items())[:2]
    a, a_sli = run_variant(a_env)
    b, b_sli = run_variant(b_env)
    print(f"A = {a_env}\nB = {b_env}\n")
    print(f"{'':22s}{'A':>12s}{'B':>12s}")
    print(f"{'golden pass rate':22s}{sum(a.values()) / len(a):>12.0%}{sum(b.values()) / len(b):>12.0%}")
    for k, label in (("containment", "containment"), ("cost_per_contact_gbp", "est. cost / contact")):
        fa, fb = a_sli.get(k, 0), b_sli.get(k, 0)
        print(f"{label:22s}{(f'£{fa:.4f}' if 'gbp' in k else f'{fa:.0%}'):>12s}{(f'£{fb:.4f}' if 'gbp' in k else f'{fb:.0%}'):>12s}")
    fixed = sorted(k for k in a if not a[k] and b.get(k))
    broken = sorted(k for k in a if a[k] and not b.get(k))
    print(f"\nfixed by B: {fixed or 'none'}\nbroken by B: {broken or 'none'}")
    print("\nREGRESSION: do not ship B" if broken else "\nno regressions: B may go to a canary")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
