"""HTTP entry points (Layer 1 adapters behind FastAPI). Run: uvicorn agent.api:app --reload"""
from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from . import adapters, db
from .pipeline import SupportAgent
from .safety import SafetyViolation, verify_session
from .telemetry import load_trace, metrics

app = FastAPI(title="RetailCo Support Agent")
_conn = db.connect()
db.init_db(_conn)
agent = SupportAgent(_conn)


class ChatIn(BaseModel):
    text: str
    session_id: str | None = None


@app.post("/chat")
async def chat(body: ChatIn, authorization: str | None = Header(default=None)):
    token = (authorization or "").removeprefix("Bearer ").strip() or None
    try:
        customer_id = verify_session(token)
        req = adapters.from_chat(body.model_dump(), customer_id)
        reply = await agent.handle(req, token)
    except SafetyViolation as e:
        raise HTTPException(e.status, e.reason)
    return reply.model_dump()


@app.post("/webhooks/email")
async def email(ticket: dict):
    return (await agent.handle(adapters.from_email(ticket))).model_dump()


@app.post("/webhooks/carrier")
async def carrier(event: dict):
    return (await agent.handle(adapters.from_carrier_event(event))).model_dump()


@app.get("/traces/{trace_id}")
def trace(trace_id: str):
    return load_trace(trace_id)


@app.get("/metrics")
def get_metrics():
    return dict(metrics)
