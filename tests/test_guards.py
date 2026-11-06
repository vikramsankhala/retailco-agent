import asyncio

from agent.guards import pre_tool_guard


def decision(tool, args=None):
    out = asyncio.run(pre_tool_guard({"tool_name": tool, "tool_input": args or {}}, "t1", None))
    return out.get("hookSpecificOutput", {}).get("permissionDecision", "allow")


def test_only_retailco_tools_allowed():
    assert decision("Bash", {"command": "rm -rf /"}) == "deny"
    assert decision("mcp__retailco__track_order", {"order_id": "ORD-9821"}) == "allow"


def test_refund_cap_enforced_even_if_model_is_persuaded():
    assert decision("mcp__retailco__issue_refund", {"amount": 349.0}) == "deny"
    assert decision("mcp__retailco__issue_refund", {"amount": 47.99}) == "allow"


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("RETAILCO_KILL_SWITCH", "1")
    assert decision("mcp__retailco__issue_refund", {"amount": 10}) == "deny"
    assert decision("mcp__retailco__track_order", {"order_id": "ORD-9821"}) == "allow"
