"""Layer 3 - Understanding: intent, entities, sentiment as a validated ParsedIntent.

Live mode uses the fast model with a forced tool call, so the output is always
JSON that matches the schema. Offline mode (no API key, or in tests) uses a
transparent keyword classifier so the whole pipeline still runs end to end.
"""
from __future__ import annotations

import re

from . import config
from .adapters import find_order_id
from .schemas import ParsedIntent, SupportRequest

INTENT_TOOL = {
    "name": "record_intent",
    "description": "Record the customer's intent, entities and sentiment.",
    "input_schema": ParsedIntent.model_json_schema(),
}

UNDERSTAND_PROMPT = """You classify messages sent to RetailCo customer support.
Choose exactly one intent. Use out_of_scope for anything that is not about the
customer's own orders, deliveries, refunds, returns, address or our products.
Partial returns (only some items) are out_of_scope in Phase 1.
Set confidence below 0.7 if the message is ambiguous.
Only extract an order_id that literally appears in the message, as ORD-nnnn."""


async def understand(req: SupportRequest, history: list[dict] | None = None) -> ParsedIntent:
    if not config.LIVE:
        return heuristic_intent(req.raw_text)
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic()
    context = "\n".join(f"{t['role']}: {t['text']}" for t in (history or [])[-4:])
    msg = await client.messages.create(
        model=config.MODEL_FAST,
        max_tokens=400,
        system=UNDERSTAND_PROMPT,
        tools=[INTENT_TOOL],
        tool_choice={"type": "tool", "name": "record_intent"},
        messages=[{"role": "user", "content":
                   f"Earlier turns:\n{context or '(none)'}\n\nNew message:\n{req.raw_text}"}],
    )
    block = next(b for b in msg.content if b.type == "tool_use")
    parsed = ParsedIntent.model_validate(block.input)
    # Business-rule validation: never trust an id the text does not contain.
    if parsed.order_id and parsed.order_id != find_order_id(req.raw_text):
        parsed.order_id = find_order_id(req.raw_text)
    return parsed


_RULES: list[tuple[str, str]] = [
    (r"\b(part of|some of|one of the items|only one item)\b.*\breturn|\breturn\b.*\b(part of|some of)", "out_of_scope"),
    (r"\b(change|update|wrong) (my |the )?(delivery )?address", "update_address"),
    (r"\brefund|money back|reimburse", "request_refund"),
    (r"\breturn|send (it|this) back", "initiate_return"),
    (r"\b(where|track|tracking|status|arrive|deliver|parcel|package|haven'?t (got|received))", "track_order"),
    (r"\b(size|colour|color|material|in stock|dimensions|warranty)\b", "product_query"),
    (r"\b(policy|opening hours|how long|do you)\b", "general_enquiry"),
    (r"\b(manager|human|person|complain|lawyer|legal action|ombudsman)\b", "escalate"),
]
_POLICY_Q = re.compile(r"\b(what is|what's|how long|how do|do you|can i)\b.*\b(policy|take|work|allowed)\b")
_FURIOUS = re.compile(r"\b(furious|disgusting|worst|outrageous|scam|legal action)\b|!!!", re.I)
_FRUSTRATED = re.compile(r"\b(still|again|days|weeks|ridiculous|annoyed|frustrat\w*)\b", re.I)


def heuristic_intent(text: str) -> ParsedIntent:
    t = text.lower()
    intent, conf = "general_enquiry", 0.55
    order_id = find_order_id(text)
    rules = _RULES if order_id or not _POLICY_Q.search(t) else [(_POLICY_Q.pattern, "general_enquiry")]
    for pattern, name in rules:
        if re.search(pattern, t):
            intent, conf = name, 0.85
            break
    if intent in ("track_order", "request_refund", "initiate_return") and not order_id:
        conf = min(conf, 0.65)  # we will need to ask for the order number
    sentiment = "furious" if _FURIOUS.search(text) else "frustrated" if _FRUSTRATED.search(text) else "neutral"
    return ParsedIntent(
        intent=intent, confidence=conf, order_id=order_id,
        customer_sentiment=sentiment,
        urgency="high" if sentiment != "neutral" else "medium",
        summary=f"Customer {intent.replace('_', ' ')}" + (f" for {order_id}" if order_id else ""),
    )
