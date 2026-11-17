"""Human approval that survives restarts (Module 17).

A refund above £200 cannot finish in one request: the agent asks, a senior
colleague decides minutes or hours later, and only then is the money moved. In
between, the server may restart. So the approval is a small state machine kept
in the database, not in memory:

    pending --approve--> approved --execute--> executed
       |                                         (refund issued, customer emailed)
       +---reject---> rejected --execute--> closed   (customer told why)
       +---timeout--> expired                       (passed to the team)

Three rules make it safe:
  * a decision is a compare-and-set (UPDATE ... WHERE status='pending'), so two
    reviewers clicking at once cannot both win;
  * execution uses the same idempotency keys as the agent (refund:<order_id>),
    so running it twice cannot refund twice;
  * resume() runs at start-up and finishes anything decided but not executed,
    which is what makes a crash between "approved" and "refunded" harmless.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from . import config
from . import tools as T
from .telemetry import metrics


class ApprovalError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApprovalService:
    def __init__(self, conn):
        self.conn = conn

    def get(self, approval_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
        return dict(row) | {"payload": json.loads(row["payload"])} if row else None

    def pending(self) -> list[dict]:
        rows = self.conn.execute("SELECT approval_id FROM approvals WHERE status='pending' ORDER BY approval_id")
        return [self.get(r["approval_id"]) for r in rows.fetchall()]

    def decide(self, approval_id: int, reviewer: str, approve: bool, note: str = "",
               _crash_before_execute: bool = False) -> dict:
        if not reviewer.startswith(config.STAFF_PREFIX):
            raise ApprovalError("Only staff can decide approvals.")
        new = "approved" if approve else "rejected"
        cur = self.conn.execute(
            "UPDATE approvals SET status=?, reviewer=?, decided_at=?, result=? "
            "WHERE approval_id=? AND status='pending'",
            (new, reviewer, _now(), json.dumps({"note": note}), approval_id))
        self.conn.commit()
        if cur.rowcount == 0:                      # someone else decided first, or it expired
            current = self.get(approval_id)
            if current is None:
                raise ApprovalError(f"No approval {approval_id}.")
            metrics["approval_already_decided"] += 1
            return current
        metrics[f"approval_{new}"] += 1
        if _crash_before_execute:                  # used by the tests to simulate a crash
            raise RuntimeError("simulated crash after the decision was saved")
        return self.execute(approval_id)

    def execute(self, approval_id: int) -> dict:
        a = self.get(approval_id)
        if a["status"] not in ("approved", "rejected"):
            return a
        oid, amount = a["payload"]["order_id"], float(a["payload"]["amount"])
        token = T.current_customer.set(a["customer_id"])     # act as the customer who asked, nobody else
        try:
            if a["status"] == "approved":
                refund = T.issue_refund(self.conn, oid, amount, f"refund:{oid}", approved_by=a["reviewer"])
                T.send_email(self.conn, "refund_confirmation",
                             {"order_id": oid, "refund_id": refund["refund_id"], "amount": refund["amount"]},
                             f"notify:{oid}:approved")
                final, result = "executed", refund
            else:
                T.send_email(self.conn, "refund_declined", {"order_id": oid}, f"notify:{oid}:declined")
                final, result = "closed", {"declined": True}
        finally:
            T.current_customer.reset(token)
        self.conn.execute("UPDATE approvals SET status=?, result=? WHERE approval_id=?",
                          (final, json.dumps(result), approval_id))
        self.conn.commit()
        return self.get(approval_id)

    def resume(self) -> list[int]:
        """Finish every decision that was saved but not carried out (call at start-up)."""
        ids = [r["approval_id"] for r in self.conn.execute(
            "SELECT approval_id FROM approvals WHERE status IN ('approved','rejected')").fetchall()]
        for i in ids:
            self.execute(i)
        metrics["approvals_resumed"] += len(ids)
        return ids

    def expire_overdue(self, now: datetime | None = None) -> list[int]:
        """Pending too long: hand to the team rather than leave the customer waiting."""
        now = now or datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=config.APPROVAL_TIMEOUT_HOURS)).isoformat()
        rows = self.conn.execute("SELECT approval_id, customer_id FROM approvals "
                                 "WHERE status='pending' AND created_at < ?", (cutoff,)).fetchall()
        for r in rows:
            self.conn.execute("UPDATE approvals SET status='expired' WHERE approval_id=? AND status='pending'",
                              (r["approval_id"],))
            token = T.current_customer.set(r["customer_id"])
            try:
                T.escalate_to_human(self.conn, f"approval {r['approval_id']} not decided within "
                                               f"{config.APPROVAL_TIMEOUT_HOURS} hours")
            finally:
                T.current_customer.reset(token)
        self.conn.commit()
        return [r["approval_id"] for r in rows]
