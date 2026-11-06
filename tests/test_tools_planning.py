import asyncio

import pytest

from agent import tools as T
from agent.planner import InvalidPlan, Plan, Step, from_template, validate_plan
from agent.taskqueue import State, TaskQueue


def test_ownership_enforced_in_code(conn):
    T.current_customer.set("CUST-1002")
    with pytest.raises(T.ToolError, match="not found"):
        T.get_order_details(conn, "ORD-9821")      # belongs to CUST-4821


def test_eligibility_rules(conn):
    T.current_customer.set("CUST-4821")
    r = T.check_refund_eligibility(conn, "ORD-9821", today="2024-11-05")
    assert r["eligible"] and r["days_overdue"] == 10 and r["refund_amount"] == 47.99
    assert T.check_refund_eligibility(conn, "ORD-9821", today="2024-10-30")["reason"] == "goodwill_credit_only"


def test_refund_is_idempotent_and_capped(conn):
    T.current_customer.set("CUST-4821")
    a = T.issue_refund(conn, "ORD-9821", 47.99, "refund:ORD-9821")
    b = T.issue_refund(conn, "ORD-9821", 47.99, "refund:ORD-9821")
    assert b["replayed"] and a["refund_id"] == b["refund_id"]
    assert conn.execute("SELECT COUNT(*) FROM refunds").fetchone()[0] == 1
    with pytest.raises(T.ToolError, match="approval"):
        T.issue_refund(conn, "ORD-9822", 349.00, "refund:ORD-9822")


def test_kill_switch_blocks_writes(conn, monkeypatch):
    T.current_customer.set("CUST-4821")
    monkeypatch.setenv("RETAILCO_KILL_SWITCH", "1")
    with pytest.raises(T.ToolError, match="paused"):
        T.issue_refund(conn, "ORD-9821", 47.99, "k")


def test_plan_validation_layers_and_errors():
    layers = validate_plan(from_template("request_refund", "refund"))
    assert [sorted(s.id for s in layer) for layer in layers] == [
        ["track", "verify"], ["evaluate"], ["approval", "refund"], ["notify"]]
    with pytest.raises(InvalidPlan, match="unknown tool"):
        validate_plan(Plan("x", [Step("a", "delete_everything", {})]))
    with pytest.raises(InvalidPlan, match="cycle"):
        validate_plan(Plan("x", [Step("a", "track_order", {"order_id": "1"}, ["b"]),
                                 Step("b", "track_order", {"order_id": "1"}, ["a"])]))


def test_queue_retries_transient_then_succeeds():
    calls = {"n": 0}

    async def flaky(tool, args):
        calls["n"] += 1
        if calls["n"] < 3:
            raise T.TransientError("503")
        return {"ok": True}

    q = TaskQueue(flaky, base_delay=0)
    run = asyncio.run(q.run(Plan("g", [Step("s", "track_order", {"order_id": "ORD-1"})]), {}))
    assert run.ok and run.runs["s"].attempts == 3


def test_queue_dead_letters_and_blocks_dependants():
    async def broken(tool, args):
        raise T.TransientError("down")

    q = TaskQueue(broken, base_delay=0)
    plan = Plan("g", [Step("a", "track_order", {"order_id": "1"}),
                      Step("b", "check_refund_eligibility", {"order_id": "1"}, ["a"])])
    run = asyncio.run(q.run(plan, {}))
    assert run.dead_letter == ["a"] and run.runs["b"].state is State.SKIPPED


def test_carrier_falls_back_to_cache(conn):
    T.current_customer.set("CUST-4821")
    c = T.Carrier(conn)
    assert c.track("ORD-9821")["source"] == "live"
    c.fail = True
    assert c.track("ORD-9821")["source"] == "cache"
