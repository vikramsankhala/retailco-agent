"""Central configuration. Thresholds live here so evals and reviews can see them in one place."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("RETAILCO_DB", ROOT / "data" / "retailco.db"))
KB_DIR = ROOT / "data" / "kb"
TRACE_FILE = Path(os.getenv("RETAILCO_TRACES", ROOT / "traces.jsonl"))

# Tiered model strategy (Layer 5). Change in one place.
MODEL_FAST = os.getenv("MODEL_FAST", "claude-haiku-5-5")      # intent, screening
MODEL_MAIN = os.getenv("MODEL_MAIN", "claude-sonnet-5-5")     # reasoning, replies
MODEL_DEEP = os.getenv("MODEL_DEEP", "claude-opus-5-5")       # hard cases, LLM judge

LIVE = bool(os.getenv("ANTHROPIC_API_KEY")) and os.getenv("RETAILCO_OFFLINE") != "1"

# Business rules (Layers 2, 6, 11, 13)
REFUND_APPROVAL_LIMIT_GBP = 200.00
RATE_LIMIT_PER_HOUR = 20
CLARIFY_BELOW_CONFIDENCE = 0.70
HUMAN_REVIEW_BELOW_CONFIDENCE = 0.75
MAX_LOOP_ITERATIONS = 3
CONTEXT_SUMMARISE_AT = 0.60      # share of the context budget
CONTEXT_BUDGET_TOKENS = 16_000
AI_DISCLOSURE = ("You're chatting with RetailCo's AI assistant. "
                 "Type 'person' at any time to reach our team.")   # Okafor condition 4
TODAY = os.getenv("RETAILCO_TODAY", "2024-11-05")   # fixed date so the lab is reproducible


def kill_switch_on() -> bool:
    """Operators set RETAILCO_KILL_SWITCH=1 to block every write tool at once."""
    return os.getenv("RETAILCO_KILL_SWITCH") == "1"
