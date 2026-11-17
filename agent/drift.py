"""Drift: is today's traffic still the traffic we tested on? (Module 18)

The population stability index (PSI) compares two distributions, here the share
of each intent in a baseline window and a current window:
    PSI = sum over categories of (current - baseline) * ln(current / baseline)
Common reading: below 0.1 little change; 0.1 to 0.25 worth a look; above 0.25 a
real shift (re-run the evals on fresh examples before trusting the old numbers).
"""
from __future__ import annotations

import math


def shares(counts: dict[str, int]) -> dict[str, float]:
    total = sum(counts.values()) or 1
    return {k: v / total for k, v in counts.items()}


def psi(baseline: dict[str, int], current: dict[str, int], floor: float = 1e-4) -> float:
    b, c = shares(baseline), shares(current)
    return sum((max(c.get(k, 0), floor) - max(b.get(k, 0), floor)) *
               math.log(max(c.get(k, 0), floor) / max(b.get(k, 0), floor)) for k in set(b) | set(c))


def verdict(value: float) -> str:
    return "stable" if value < 0.1 else "watch" if value < 0.25 else "shifted"
