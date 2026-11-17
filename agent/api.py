"""HTTP entry points (Layer 1 adapters behind FastAPI). Run: uvicorn agent.api:app --reload

Customer routes   POST /chat, POST /chat/stream (server-sent events), GET / (demo chat page)
Integrations      POST /webhooks/email, POST /webhooks/carrier
Staff routes      GET /approvals, POST /approvals/{id}/decision, GET /staff (demo page)
Operations        GET /healthz, GET /readyz, GET /metrics, GET /metrics/prometheus, GET /traces/{id}
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from . import adapters, config, db
from .approvals import ApprovalError, ApprovalService
from .kb_integrity import check as kb_check
from .pipeline import SupportAgent
from .safety import SafetyViolation, sign_session, verify_session
from .telemetry import load_trace, metrics, progress, prometheus_text

WEB = config.ROOT / "web"


class ChatIn(BaseModel):
    text: str
    session_id: str | None = None


class DecisionIn(BaseModel):
    approve: bool
    note: str = ""


def _token(authorization: str | None) -> str | None:
    return (authorization or "").removeprefix("Bearer ").strip() or None


def _staff(authorization: str | None) -> str:
    """Approvals need a staff identity. A customer's token can never decide anything."""
    try:
        who = verify_session(_token(authorization))
    except SafetyViolation as e:
        raise HTTPException(e.status, e.reason)
    if not who.startswith(config.STAFF_PREFIX):
        raise HTTPException(403, "Staff only.")
    return who


def create_app(conn=None, agent: SupportAgent | None = None) -> FastAPI:
    app = FastAPI(title="RetailCo Support Agent")
    if conn is None:
        conn = db.connect()
        db.init_db(conn)
    agent = agent or SupportAgent(conn)
    approvals = ApprovalService(conn)
    approvals.resume()                     # finish anything decided before the last restart
    app.state.agent, app.state.approvals = agent, approvals

    # --- customers --------------------------------------------------------------
    @app.post("/chat")
    async def chat(body: ChatIn, authorization: str | None = Header(default=None)):
        token = _token(authorization)
        try:
            req = adapters.from_chat(body.model_dump(), verify_session(token))
            reply = await agent.handle(req, token)
        except SafetyViolation as e:
            raise HTTPException(e.status, e.reason)
        return reply.model_dump()

    @app.post("/chat/stream")
    async def chat_stream(body: ChatIn, authorization: str | None = Header(default=None)):
        """Server-sent events: progress while the agent works, then the verified reply.

        The reply is streamed only after the Result Check has passed. Streaming model
        tokens straight to the customer would show them text that might still fail the
        grounding check, which is the one thing Layer 11 exists to prevent.
        """
        token = _token(authorization)
        try:
            req = adapters.from_chat(body.model_dump(), verify_session(token))
        except SafetyViolation as e:
            raise HTTPException(e.status, e.reason)
        queue: asyncio.Queue = asyncio.Queue()

        async def run():
            progress.set(queue)
            try:
                reply = await agent.handle(req, token)
                await queue.put({"done": reply.model_dump()})
            except SafetyViolation as e:
                await queue.put({"error": e.reason, "status": e.status})

        async def events():
            task = asyncio.create_task(run())
            while True:
                item = await queue.get()
                if "layer" in item:
                    yield f"event: status\ndata: {json.dumps(item)}\n\n"
                elif "error" in item:
                    yield f"event: error\ndata: {json.dumps(item)}\n\n"
                    break
                else:
                    reply = item["done"]
                    for word in reply["text"].split(" "):
                        yield f"event: delta\ndata: {json.dumps({'text': word + ' '})}\n\n"
                    yield f"event: done\ndata: {json.dumps({k: reply[k] for k in ('request_id', 'route', 'needs_human')})}\n\n"
                    break
            await task

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/")
    def chat_page():
        return FileResponse(WEB / "chat.html")

    # --- integrations ------------------------------------------------------------
    @app.post("/webhooks/email")
    async def email(ticket: dict):
        return (await agent.handle(adapters.from_email(ticket))).model_dump()

    @app.post("/webhooks/carrier")
    async def carrier(event: dict):
        return (await agent.handle(adapters.from_carrier_event(event))).model_dump()

    # --- staff -----------------------------------------------------------------------
    @app.get("/approvals")
    def list_approvals(authorization: str | None = Header(default=None)):
        _staff(authorization)
        return approvals.pending()

    @app.post("/approvals/{approval_id}/decision")
    def decide(approval_id: int, body: DecisionIn, authorization: str | None = Header(default=None)):
        reviewer = _staff(authorization)
        try:
            return approvals.decide(approval_id, reviewer, body.approve, body.note)
        except ApprovalError as e:
            raise HTTPException(404, str(e))

    @app.get("/staff")
    def staff_page():
        return FileResponse(WEB / "staff.html")

    # --- demo sign-in (never enable in production) -----------------------------------
    @app.get("/demo/token/{identity}")
    def demo_token(identity: str):
        if os.getenv("RETAILCO_DEMO") != "1":
            raise HTTPException(404, "Not found")
        return {"token": sign_session(identity)}

    # --- operations --------------------------------------------------------------------
    @app.get("/healthz")
    def healthz():
        """Liveness: the process is up. Keep it trivial so a slow dependency never restarts us."""
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz():
        """Readiness: safe to send traffic here. Checks the database and the knowledge base."""
        problems = []
        try:
            conn.execute("SELECT 1").fetchone()
        except Exception as e:  # pragma: no cover
            problems.append(f"database: {e}")
        if config.KB_STRICT and kb_check(config.KB_DIR):
            problems.append("knowledge base has unapproved changes")
        if not getattr(agent.kb, "passages", getattr(agent.kb, "chunks", None)):
            problems.append("knowledge base empty")
        body = {"status": "ready" if not problems else "not ready", "problems": problems,
                "kill_switch": config.kill_switch_on()}
        if problems:
            raise HTTPException(503, body)
        return body

    @app.get("/metrics")
    def get_metrics():
        return dict(metrics)

    @app.get("/metrics/prometheus", response_class=PlainTextResponse)
    def get_prometheus():
        return prometheus_text()

    @app.get("/traces/{trace_id}")
    def trace(trace_id: str):
        return load_trace(trace_id)

    return app


app = create_app()
