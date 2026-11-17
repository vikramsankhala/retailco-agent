"""Module 17: approvals that survive restarts, bounded parallelism, streaming."""
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from agent import adapters, db
from agent.api import create_app
from agent.approvals import ApprovalError, ApprovalService
from agent.pipeline import SupportAgent
from agent.planner import Plan, Step
from agent.safety import sign_session
from agent.taskqueue import TaskQueue
from agent.telemetry import Tracer


def _ask(agent, text, customer="CUST-4821"):
    return asyncio.run(agent.handle(adapters.from_chat({"text": text}, customer), sign_session(customer)))


def _refunds(conn):
    return conn.execute("SELECT COUNT(*) FROM refunds").fetchone()[0]


def test_approval_survives_a_restart_and_refunds_exactly_once(tmp_path):
    path = tmp_path / "retailco.db"
    conn = db.connect(path); db.init_db(conn)
    agent = SupportAgent(conn, tracer=Tracer(tmp_path / "t.jsonl"), retry_delay=0)
    _ask(agent, "Refund ORD-9822 please, it never arrived")
    (pending,) = ApprovalService(conn).pending()
    assert pending["payload"] == {"order_id": "ORD-9822", "amount": 349.0}

    # The reviewer approves; the process dies before the refund runs.
    with pytest.raises(RuntimeError):
        ApprovalService(conn).decide(pending["approval_id"], "STAFF-tom", True, _crash_before_execute=True)
    conn.close()
    assert _refunds(db.connect(path)) == 0

    # A new process starts: resume() finishes the job.
    conn2 = db.connect(path); db.init_db(conn2)
    svc = ApprovalService(conn2)
    assert svc.resume() == [pending["approval_id"]]
    assert svc.resume() == []                                  # nothing left to do
    row = conn2.execute("SELECT * FROM refunds").fetchone()
    assert _refunds(conn2) == 1 and row["approved_by"] == "STAFF-tom" and row["amount"] == 349.0
    assert svc.get(pending["approval_id"])["status"] == "executed"
    outbox = [r["template"] for r in conn2.execute("SELECT template FROM outbox")]
    assert outbox == ["refund_confirmation"]


def test_two_reviewers_cannot_both_decide(conn, agent):
    _ask(agent, "Refund ORD-9822 please, it never arrived")
    svc = ApprovalService(conn)
    aid = svc.pending()[0]["approval_id"]
    first = svc.decide(aid, "STAFF-tom", True)
    second = svc.decide(aid, "STAFF-priya", False)          # arrives a moment later
    assert first["status"] == second["status"] == "executed" and second["reviewer"] == "STAFF-tom"
    assert _refunds(conn) == 1


def test_asking_twice_does_not_create_two_approvals(conn, agent):
    _ask(agent, "Refund ORD-9822 please, it never arrived")
    _ask(agent, "Hello? Refund ORD-9822 please, it never arrived")
    assert len(ApprovalService(conn).pending()) == 1


def test_customers_cannot_approve_and_declines_are_told(conn, agent):
    _ask(agent, "Refund ORD-9822 please, it never arrived")
    svc = ApprovalService(conn)
    aid = svc.pending()[0]["approval_id"]
    with pytest.raises(ApprovalError):
        svc.decide(aid, "CUST-4821", True)
    assert svc.decide(aid, "STAFF-tom", False)["status"] == "closed"
    assert _refunds(conn) == 0
    assert [r["template"] for r in conn.execute("SELECT template FROM outbox")] == ["refund_declined"]


def test_overdue_approvals_go_to_the_team(conn, agent):
    _ask(agent, "Refund ORD-9822 please, it never arrived")
    svc = ApprovalService(conn)
    later = datetime.now(timezone.utc) + timedelta(hours=25)
    assert len(svc.expire_overdue(now=later)) == 1
    assert svc.pending() == []
    assert conn.execute("SELECT COUNT(*) FROM escalations WHERE reason LIKE 'approval%'").fetchone()[0] == 1


def test_parallel_steps_are_capped():
    running, peak = 0, 0

    async def slow(tool, args):
        nonlocal running, peak
        running += 1; peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        return {"ok": True}

    plan = Plan("six lookups", [Step(f"s{i}", "get_order_details", {"order_id": "ORD-9821"}) for i in range(6)])
    started = time.perf_counter()
    result = asyncio.run(TaskQueue(slow, max_parallel=3).run(plan, {}))
    elapsed = time.perf_counter() - started
    assert result.ok and peak == 3
    assert elapsed < 6 * 0.05            # parallel: about two rounds, not six


@pytest.fixture
def client(conn, agent):
    return TestClient(create_app(conn, agent))


def test_stream_sends_progress_then_the_verified_reply(client):
    token = sign_session("CUST-4821")
    with client.stream("POST", "/chat/stream", json={"text": "Where is my order ORD-9821?"},
                       headers={"Authorization": f"Bearer {token}"}) as r:
        body = "".join(r.iter_text())
    events = [b.split("\n")[0].removeprefix("event: ") for b in body.strip().split("\n\n")]
    assert events[0] == "status" and events[-1] == "done"
    assert events.index("delta") > max(i for i, e in enumerate(events) if e == "status")  # text only after checks
    text = "".join(json.loads(b.split("data: ", 1)[1])["text"] for b in body.split("\n\n") if b.startswith("event: delta"))
    assert "Leeds depot" in text


def test_staff_routes_need_a_staff_identity(client):
    customer = {"Authorization": f"Bearer {sign_session('CUST-4821')}"}
    staff = {"Authorization": f"Bearer {sign_session('STAFF-tom')}"}
    assert client.get("/approvals", headers=customer).status_code == 403
    assert client.get("/approvals", headers=staff).json() == []


def test_health_and_readiness(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    ready = client.get("/readyz")
    assert ready.status_code == 200 and ready.json()["status"] == "ready"
    assert "retailco_request_latency_ms_bucket" in client.get("/metrics/prometheus").text
