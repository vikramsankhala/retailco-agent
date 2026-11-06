"""Layer 6 - Decision gate: answer directly, plan, ask, or hand to a human.

Deterministic rules first (cheap, testable, auditable); the reasoning model is
only consulted for the cases these rules do not settle. Every decision is logged.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import config
from .memory import AgentContext
from .schemas import Route

TOOL_INTENTS = {"track_order", "request_refund", "initiate_return", "update_address"}
KB_INTENTS = {"general_enquiry", "product_query"}


@dataclass
class Decision:
    route: Route
    reason: str
    needs_human: bool = False


def decide(ctx: AgentContext) -> Decision:
    i, flags = ctx.intent, ctx.request.flags
    if "possible_prompt_injection" in flags:
        return Decision(Route.ESCALATE, "injection_flagged", needs_human=True)
    if i.intent == "escalate" or i.customer_sentiment == "furious":
        return Decision(Route.ESCALATE, "customer_needs_a_person", needs_human=True)
    if i.intent == "out_of_scope":
        return Decision(Route.DIRECT, "out_of_scope_deflection")
    if i.confidence < config.CLARIFY_BELOW_CONFIDENCE:
        return Decision(Route.CLARIFY, "low_confidence_or_missing_order_id")
    if i.intent in TOOL_INTENTS:
        if not i.order_id:
            return Decision(Route.CLARIFY, "order_id_required")
        return Decision(Route.PLAN, "tools_required")
    if i.intent in KB_INTENTS and ctx.docs:
        return Decision(Route.DIRECT, "answerable_from_knowledge_base")
    return Decision(Route.DIRECT, "general_answer")
