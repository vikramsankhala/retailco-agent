"""Layer 10 - Tool connection: expose the business tools over MCP.

create_sdk_mcp_server runs the server in-process with the agent (no network hop).
The same tool functions can be served to other agents or to Claude Code itself
over stdio or HTTP with any MCP server library; see the programme's Module 10.
Tool names seen by the model are mcp__retailco__<tool>.
"""
from __future__ import annotations

import json

from claude_agent_sdk import create_sdk_mcp_server, tool

from . import tools as T


def _ok(data: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(data)}]}


def _err(e: Exception) -> dict:
    # is_error tells the model the call failed, so it can correct itself (Layer 11)
    return {"content": [{"type": "text", "text": f"ERROR: {e}"}], "is_error": True}


def build_server(conn, carrier: T.Carrier, kb, read_only: bool = False):
    @tool("get_order_details", "Get an order's total, dates, status and carrier. order_id looks like ORD-9821.",
          {"order_id": str})
    async def get_order_details(args):
        try:
            return _ok(T.get_order_details(conn, args["order_id"]))
        except T.ToolError as e:
            return _err(e)

    @tool("track_order", "Get real-time delivery status for an order from the carrier.", {"order_id": str})
    async def track_order(args):
        try:
            return _ok(carrier.track(args["order_id"]))
        except T.ToolError as e:
            return _err(e)

    @tool("check_refund_eligibility", "Apply the Late Delivery Guarantee to an order. Returns eligible, reason, amount.",
          {"order_id": str})
    async def check_refund_eligibility(args):
        try:
            return _ok(T.check_refund_eligibility(conn, args["order_id"]))
        except T.ToolError as e:
            return _err(e)

    @tool("search_knowledge_base", "Search RetailCo policy articles.", {"query": str})
    async def search_kb(args):
        return _ok(T.search_knowledge_base(kb, args["query"]))

    @tool("escalate_to_human", "Hand the conversation to a human agent with a short reason.", {"reason": str})
    async def escalate(args):
        return _ok(T.escalate_to_human(conn, args["reason"]))

    @tool("issue_refund", "Issue a refund. Only after check_refund_eligibility says eligible. "
          "idempotency_key must be refund:<order_id>.",
          {"order_id": str, "amount": float, "idempotency_key": str})
    async def issue_refund(args):
        try:
            return _ok(T.issue_refund(conn, args["order_id"], float(args["amount"]), args["idempotency_key"]))
        except T.ToolError as e:
            return _err(e)

    @tool("request_approval", "Ask a senior agent to approve an action such as a refund over £200.",
          {"action": str, "payload": dict})
    async def request_approval(args):
        return _ok(T.request_approval(conn, args["action"], args["payload"]))

    read = [get_order_details, track_order, check_refund_eligibility, search_kb, escalate]
    write = [issue_refund, request_approval]
    return create_sdk_mcp_server(name="retailco", version="1.0.0", tools=read if read_only else read + write)


def allowed_names(read_only: bool = False) -> list[str]:
    names = ["get_order_details", "track_order", "check_refund_eligibility", "search_knowledge_base",
             "escalate_to_human"] + ([] if read_only else ["issue_refund", "request_approval"])
    return [f"mcp__retailco__{n}" for n in names]
