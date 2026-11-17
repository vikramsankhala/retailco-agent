"""Compare the intent mix of two trace files.

    python -m scripts.drift_report baseline.jsonl current.jsonl
"""
from __future__ import annotations

import sys
from pathlib import Path

from agent.drift import psi, shares, verdict
from agent.slo import compute


def main(argv: list[str]) -> int:
    base, cur = (compute(Path(p)).get("intents", {}) for p in argv[:2])
    value = psi(base, cur)
    sb, sc = shares(base), shares(cur)
    print(f"{'intent':20s}{'baseline':>10s}{'current':>10s}")
    for k in sorted(set(sb) | set(sc)):
        print(f"{k:20s}{sb.get(k, 0):>10.1%}{sc.get(k, 0):>10.1%}")
    print(f"\nPSI {value:.3f}: {verdict(value)}")
    return 0 if value < 0.25 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
