"""Layer 9 - Action layer. Plain Python business functions, ordered by risk:
read-only lookups -> stateless computation -> state-modifying writes -> delegation.

Rules every tool follows:
  * ownership is checked in code, from the verified customer id, never from model output;
  * every write takes an idempotency key, so a retry can never refund twice;
  * every result is a plain dict, so the Result Check layer can verify it.
"""
from __future__ import annotations

import contextvars
import json
import sqlite3
from datetime import date, datetime, timezone

from . import config
from .memory import KnowledgeBase

current_customer: contextvars.ContextVar[str] = contextvars.ContextVar("current_customer")
current_request: contextvars.ContextVar[str] = contextvars.ContextVar("current_request", default="-")


class ToolError(Exception):
    """Raised for failures the agent should see and reason about."""


class TransientError(ToolError):
    """A failure worth retrying (timeouts, 503s). The task queue retries these with back-off."""


class CarrierUnavailable(TransientError):
    pass


def _own_order(conn: sqlite3.Connection, order_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    # Same message for "missing" and "someone else's": no data leaks through errors.
    if row is None or row["customer_id"] != current_customer.get():
        raise ToolError(f"Order {order_id} not found on this account. Check the format ORD-nnnn.")
    return row


# --- Read-only lookups ------------------------------------------------------------
def get_order_details(conn, order_id: str) -> dict:
    r = _own_order(conn, order_id)
    return {k: r[k] for k in ("order_id", "total", "placed_on", "expected_delivery", "status", "carrier")}


class Carrier:
    """Simulated carrier API with a cached fallback and a simple circuit breaker."""

    def __init__(self, conn, fail: bool = False, threshold: int = 3):
        self.conn, self.fail, self.threshold = conn, fail, threshold
        self.failures = 0
        self.cache: dict[str, dict] = {}

    def _live(self, order_id: str) -> dict:
        if self.fail or self.failures >= self.threshold:
            raise CarrierUnavailable("carrier API unavailable")
        r = self.conn.execute("SELECT * FROM shipments WHERE order_id=?", (order_id,)).fetchone()
        return {"carrier_status": r["carrier_status"], "last_update": r["last_update"],
                "location": r["location"], "tracking_url": r["tracking_url"]}

    def track(self, order_id: str) -> dict:
        _own_order(self.conn, order_id)
        try:
            data = self._live(order_id)
            self.failures = 0
            self.cache[order_id] = data
            return data | {"source": "live"}
        except CarrierUnavailable:
            self.failures += 1
            if order_id in self.cache:
                return self.cache[order_id] | {"source": "cache"}
            raise


# --- Stateless computation ---------------------------------------------------------
def check_refund_eligibility(conn, order_id: str, today: str = config.TODAY) -> dict:
    """Late Delivery Guarantee: >=7 days late -> full refund; 3-6 days -> £5 credit."""
    o = _own_order(conn, order_id)
    if o["status"] == "delivered":
        return {"eligible": False, "reason": "already_delivered", "refund_amount": 0.0}
    days_late = (date.fromisoformat(today) - date.fromisoformat(o["expected_delivery"])).days
    if days_late >= 7:
        return {"eligible": True, "reason": "delivery_sla_breach", "days_overdue": days_late,
                "refund_amount": round(o["total"], 2), "refund_type": "full",
                "needs_approval": o["total"] > config.REFUND_APPROVAL_LIMIT_GBP}
    if days_late >= 3:
        return {"eligible": False, "reason": "goodwill_credit_only", "days_overdue": days_late,
                "refund_amount": 0.0, "credit": 5.0}
    return {"eligible": False, "reason": "not_late_enough", "days_overdue": max(days_late, 0),
            "refund_amount": 0.0}


# --- State-modifying writes ---------------------------------------------------------
def issue_refund(conn, order_id: str, amount: float, idempotency_key: str,
                 approved_by: str | None = None) -> dict:
    if config.kill_switch_on():
        raise ToolError("Write actions are paused by the operations team.")
    o = _own_order(conn, order_id)
    existing = conn.execute("SELECT * FROM refunds WHERE idempotency_key=?", (idempotency_key,)).fetchone()
    if existing:  # a retry: return the original result, do nothing new
        return {"refund_id": existing["refund_id"], "status": existing["status"],
                "amount": existing["amount"], "replayed": True}
    if amount > o["total"] + 0.001:
        raise ToolError("Refund amount exceeds the order total.")
    if amount > config.REFUND_APPROVAL_LIMIT_GBP and not approved_by:
        raise ToolError("Refunds above £200 need senior approval. Request approval first.")
    refund_id = f"REF-{config.TODAY.replace('-', '')}-{order_id[-4:]}"
    conn.execute("INSERT INTO refunds VALUES (?,?,?,?,?,?,?)",
                 (refund_id, order_id, amount, idempotency_key, "processed", approved_by,
                  datetime.now(timezone.utc).isoformat()))
    conn.commit()
    return {"refund_id": refund_id, "status": "processed", "amount": amount, "eta_days": "3-5"}


def request_approval(conn, action: str, payload: dict) -> dict:
    cur = conn.execute("INSERT INTO approvals (request_id, action, payload) VALUES (?,?,?)",
                       (current_request.get(), action, json.dumps(payload)))
    conn.commit()
    return {"approval_id": cur.lastrowid, "status": "pending"}


def send_email(conn, template: str, payload: dict, idempotency_key: str) -> dict:
    if config.kill_switch_on():
        raise ToolError("Write actions are paused by the operations team.")
    to = conn.execute("SELECT email FROM customers WHERE customer_id=?",
                      (current_customer.get(),)).fetchone()["email"]
    conn.execute("INSERT OR IGNORE INTO outbox (idempotency_key,to_addr,template,payload) VALUES (?,?,?,?)",
                 (idempotency_key, to, template, json.dumps(payload)))
    conn.commit()
    return {"queued": True, "to": to}


def escalate_to_human(conn, reason: str) -> dict:
    cur = conn.execute("INSERT INTO escalations (request_id, customer_id, reason, created_at) VALUES (?,?,?,?)",
                       (current_request.get(), current_customer.get(), reason,
                        datetime.now(timezone.utc).isoformat()))
    conn.commit()
    return {"escalation_id": cur.lastrowid, "queue": "tier2", "expected_reply": "within 2 hours"}


def search_knowledge_base(kb: KnowledgeBase, query: str) -> dict:
    return {"results": [{"source": c.source, "text": c.text} for c in kb.search(query)]}


# Registry used by the planner to validate plans before execution.
REGISTRY = {
    "get_order_details": {"risk": "read", "args": ["order_id"]},
    "track_order": {"risk": "read", "args": ["order_id"]},
    "check_refund_eligibility": {"risk": "compute", "args": ["order_id"]},
    "issue_refund": {"risk": "write", "args": ["order_id", "amount", "idempotency_key"]},
    "request_approval": {"risk": "write", "args": ["action", "payload"]},
    "send_email": {"risk": "write", "args": ["template", "payload", "idempotency_key"]},
    "escalate_to_human": {"risk": "delegate", "args": ["reason"]},
    "search_knowledge_base": {"risk": "read", "args": ["query"]},
}
