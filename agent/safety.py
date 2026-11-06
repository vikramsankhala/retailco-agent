"""Layer 2 - Safety and access checks. Runs before any model call, in well under 50 ms.

Each check returns PASS, FLAG (continue but mark for review) or BLOCK (stop).
Action-time controls (refund caps, ownership, kill switch) live in guards.py,
because a prompt injection that slips past this layer must still be stopped there.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from enum import Enum

from . import config
from .schemas import SupportRequest

SECRET = os.getenv("RETAILCO_SESSION_SECRET", "dev-only-secret").encode()


class Action(str, Enum):
    PASS = "pass"
    FLAG = "flag"
    BLOCK = "block"


@dataclass
class CheckResult:
    action: Action
    reason: str = ""


class SafetyViolation(Exception):
    def __init__(self, reason: str, status: int = 403):
        super().__init__(reason)
        self.reason, self.status = reason, status


# --- 1. Permission verification -------------------------------------------
def sign_session(customer_id: str) -> str:
    sig = hmac.new(SECRET, customer_id.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{customer_id}.{sig}"


def verify_session(token: str | None) -> str:
    """Return the customer_id the token proves, or raise 401."""
    if not token or "." not in token:
        raise SafetyViolation("Please sign in to continue.", 401)
    customer_id, sig = token.rsplit(".", 1)
    expected = hmac.new(SECRET, customer_id.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        raise SafetyViolation("Your session has expired. Please sign in again.", 401)
    return customer_id


# --- 2. Content filtering: prompt injection and abuse -----------------------
INJECTION_PATTERNS = [
    r"ignore (all|any|the)? ?(previous|prior|above) (instructions|rules)",
    r"you are now (?:in )?(developer|dan|god) mode",
    r"(reveal|print|show) (your|the) (system prompt|instructions)",
    r"act as (an? )?(admin|administrator|root)",
    r"refund (every|all) (order|customer)s?",
    r"</?(system|assistant)>",
]
_INJ = [re.compile(p, re.I) for p in INJECTION_PATTERNS]
ABUSE_WORDS = {"idiot", "stupid", "useless", "moron"}


def screen_content(text: str) -> CheckResult:
    if any(p.search(text) for p in _INJ):
        return CheckResult(Action.FLAG, "possible_prompt_injection")
    if set(re.findall(r"[a-z]+", text.lower())) & ABUSE_WORDS:
        return CheckResult(Action.FLAG, "abusive_language")
    return CheckResult(Action.PASS)


# --- 3. PII minimisation -----------------------------------------------------
_CARD = re.compile(r"\b(?:\d[ -]?){13,16}\b")


def redact_pii(text: str) -> str:
    """Card numbers never reach the model or the logs."""
    return _CARD.sub("[card number removed]", text)


# --- 4. Rate limiting (sliding window) ----------------------------------------
class RateLimiter:
    def __init__(self, limit: int = config.RATE_LIMIT_PER_HOUR, window_s: int = 3600,
                 clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window_s, clock
        self._hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str) -> CheckResult:
        now, q = self.clock(), self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return CheckResult(Action.BLOCK, "rate_limited")
        q.append(now)
        return CheckResult(Action.PASS)


# --- The pipeline -------------------------------------------------------------
class SafetyPipeline:
    def __init__(self, limiter: RateLimiter | None = None):
        self.limiter = limiter or RateLimiter()

    def run(self, request: SupportRequest, session_token: str | None) -> SupportRequest:
        # Webhooks are authenticated by the integration's own signature upstream.
        if request.channel.value in ("chat", "sms"):
            if verify_session(session_token) != request.customer_id:
                raise SafetyViolation("Session does not match this account.", 403)
        rl = self.limiter.check(request.customer_id)
        if rl.action is Action.BLOCK:
            raise SafetyViolation(
                "You've reached the hourly limit for the assistant. "
                "A member of our team can still help you by email.", 429)
        request.raw_text = redact_pii(request.raw_text)
        content = screen_content(request.raw_text)
        if content.action is Action.FLAG:
            request.flags.append(content.reason)
        return request
