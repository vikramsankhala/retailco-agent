"""Action-time guardrails (Layers 2 and 13) as Claude Agent SDK hooks.

The PreToolUse hook runs before every tool call the model proposes. It is
ordinary code, so a model that has been talked into something by a prompt
injection still cannot issue an unapproved refund or call a tool outside the
RetailCo server.
"""
from __future__ import annotations

from . import config
from .telemetry import metrics

SERVER = "retailco"
WRITE_TOOLS = {f"mcp__{SERVER}__{n}" for n in ("issue_refund", "send_email", "request_approval")}


def _deny(reason: str) -> dict:
    metrics["guard_denied"] += 1
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


async def pre_tool_guard(input_data: dict, tool_use_id: str | None, context) -> dict:
    name, args = input_data.get("tool_name", ""), input_data.get("tool_input", {}) or {}
    if not name.startswith(f"mcp__{SERVER}__"):
        return _deny(f"{name} is not available to the support agent.")
    if name in WRITE_TOOLS and config.kill_switch_on():
        return _deny("Write actions are paused by the operations team. Escalate instead.")
    if name.endswith("__issue_refund"):
        if float(args.get("amount", 0)) > config.REFUND_APPROVAL_LIMIT_GBP and not args.get("approved_by"):
            return _deny("Refunds above £200 need senior approval. Call request_approval instead.")
    return {}


async def post_tool_audit(input_data: dict, tool_use_id: str | None, context) -> dict:
    metrics[f"tool_{input_data.get('tool_name', '?').split('__')[-1]}"] += 1
    return {}


def hook_config() -> dict:
    from claude_agent_sdk import HookMatcher
    return {
        "PreToolUse": [HookMatcher(matcher=None, hooks=[pre_tool_guard])],
        "PostToolUse": [HookMatcher(matcher=None, hooks=[post_tool_audit])],
    }
