"""Central configuration. Thresholds live here so evals and reviews can see them in one place."""
from __future__ import annotations

import os
from pathlib import Path

# RETAILCO_ROOT points at the folder holding data/ and web/ when the package is installed (e.g. in Docker).
ROOT = Path(os.getenv("RETAILCO_ROOT", Path(__file__).resolve().parent.parent))
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
REDIS_URL = os.getenv("REDIS_URL")   # set when several replicas must share one rate limit (Module 18)
CLARIFY_BELOW_CONFIDENCE = 0.70
HUMAN_REVIEW_BELOW_CONFIDENCE = 0.75
MAX_LOOP_ITERATIONS = 3
CONTEXT_SUMMARISE_AT = 0.60      # share of the context budget
CONTEXT_BUDGET_TOKENS = 16_000
AI_DISCLOSURE = ("You're chatting with RetailCo's AI assistant. "
                 "Type 'person' at any time to reach our team.")   # Okafor condition 4
TODAY = os.getenv("RETAILCO_TODAY", "2024-11-05")   # fixed date so the lab is reproducible

# Retrieval (Module 15)
RETRIEVER = os.getenv("RETAILCO_RETRIEVER", "hybrid")   # "hybrid" or "bm25" (the Module 7 baseline)
RRF_K = 60                      # reciprocal rank fusion constant (Cormack et al., 2009)
RERANK_CANDIDATES = 8           # how many fused results get the closer look
RETRIEVAL_MIN_SCORE = 0.35      # below this the retriever rewrites once, then reports "insufficient"

# Security (Module 16)
KB_STRICT = os.getenv("RETAILCO_KB_STRICT", "1") == "1"   # load only articles listed in the manifest
ALLOWED_MCP_SERVERS = {"retailco"}                          # the guard denies tools from any other server
TRUSTED_LINK_DOMAINS = ("retailco.example", "track.example")  # links anywhere else in content are flagged

# Long-running work (Module 17)
APPROVAL_TIMEOUT_HOURS = 24     # pending approvals older than this are escalated
MAX_PARALLEL_TOOLS = 4          # cap on tool calls running at once within one plan layer
STAFF_PREFIX = "STAFF-"         # reviewer identities; a customer token can never approve

# Service levels (Module 18). Targets from the case analysis, Table A9.
SLO = {
    "containment": 0.75,          # resolved without a person
    "p95_latency_ms": 30_000,     # first response, tier-1 chat (< 30 s)
    "cost_per_contact_gbp": 0.15,
    "escalation_rate_max": 0.25,
    "verifier_fail_rate_max": 0.05,
}
# Example prices for the cost estimate, in GBP per million tokens. These are placeholders:
# replace them with the prices on your own contract before using the numbers.
PRICE_GBP_PER_MTOK = {
    MODEL_FAST: {"in": 0.80, "out": 4.00},
    MODEL_MAIN: {"in": 2.40, "out": 12.00},
    MODEL_DEEP: {"in": 4.00, "out": 20.00},
}


def kill_switch_on() -> bool:
    """Operators set RETAILCO_KILL_SWITCH=1 to block every write tool at once."""
    return os.getenv("RETAILCO_KILL_SWITCH") == "1"
