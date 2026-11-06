"""Layer 12 - Output: tone, channel formatting and action confirmation.

compose_offline() writes replies from verified facts with fixed templates; it is
what runs without an API key, and the safe fallback when a model reply fails
the Result Check twice. format_for_channel() adapts any reply to its channel.
"""
from __future__ import annotations

import re

from .schemas import Channel, ParsedIntent

TONES = {
    "neutral": ("", ""),
    "positive": ("", ""),
    "frustrated": ("I'm sorry about the wait, and I understand the frustration. ", ""),
    "furious": ("I'm truly sorry. ", ""),
}

STATUS_WORDS = {"delayed": "delayed", "out_for_delivery": "out for delivery",
                "in_transit": "in transit", "delivered": "delivered"}


def compose_offline(intent: ParsedIntent, facts: dict, name: str = "there") -> str:
    opener, _ = TONES[intent.customer_sentiment]
    o, t = facts.get("verify") or {}, facts.get("track") or {}
    oid = intent.order_id
    if intent.intent == "track_order" and t:
        stale = " (live tracking is unavailable, so this is the last known status)" if t.get("source") == "cache" else ""
        return (f"Hi {name}, {opener}here's the latest on {oid}{stale}:\n"
                f"- Status: {STATUS_WORDS.get(t['carrier_status'], t['carrier_status'])}\n"
                f"- Last location: {t['location']} ({t['last_update']})\n"
                f"- Track it: {t['tracking_url']}\n\nIs there anything else I can help with?")
    if intent.intent == "request_refund":
        ev, refund = facts.get("evaluate") or {}, facts.get("refund") or {}
        if refund.get("refund_id"):
            return (f"Hi {name}, {opener}your order {oid} is {ev.get('days_overdue')} days late, so it's covered "
                    f"by our Late Delivery Guarantee. Here's what I've done:\n"
                    f"- Full refund of £{refund['amount']:.2f} processed to your original payment method\n"
                    f"- Confirmation email on its way\n- Funds usually arrive in 3 to 5 business days\n\n"
                    f"Refund reference: {refund['refund_id']}")
        if facts.get("approval"):
            return (f"Hi {name}, {opener}your order {oid} qualifies for a full refund of "
                    f"£{ev['refund_amount']:.2f}. Refunds of this size are checked by a senior colleague "
                    f"first; I've sent it for approval and you'll hear from us within 2 hours.")
        if ev.get("reason") == "goodwill_credit_only":
            return (f"Hi {name}, {opener}{oid} is {ev['days_overdue']} days late. Our guarantee gives a full "
                    f"refund from 7 days late; until then I can add a £{ev['credit']:.2f} goodwill credit.")
        if ev:
            return f"Hi {name}, {oid} isn't eligible for a refund yet ({ev.get('reason', '').replace('_', ' ')})."
    if intent.intent == "initiate_return" and facts.get("notify"):
        return f"Hi {name}, I've started a return for {oid} and emailed you a prepaid label."
    if intent.intent == "update_address" and o:
        if o.get("status") in ("placed", "packed"):
            return f"Hi {name}, {oid} hasn't shipped yet, so its address can still be changed. What's the new address?"
        return (f"Hi {name}, {oid} is already {STATUS_WORDS.get(o['status'], o['status'])}, so I can't change "
                f"the address. You can redirect it with {o['carrier']} using the tracking link.")
    return f"Hi {name}, thanks for getting in touch. Let me pass this to a colleague who can help."


def clarify_question(intent: ParsedIntent) -> str:
    if not intent.order_id and intent.intent in ("track_order", "request_refund", "initiate_return", "update_address"):
        return "Happy to help. Could you share your order number? It looks like ORD-1234."
    return "Sorry, I want to make sure I get this right. Could you tell me a little more about what you need?"


def format_for_channel(text: str, channel: Channel) -> tuple[str, str | None]:
    """Return (body, subject)."""
    if channel is Channel.SMS:
        plain = re.sub(r"[*_`#]|^- ", "", text, flags=re.M).replace("\n", " ")
        return (plain[:157] + "...") if len(plain) > 160 else plain, None
    if channel is Channel.EMAIL:
        first = text.split("\n", 1)[0]
        subject = "Your RetailCo enquiry" + (f" - {m.group(0)}" if (m := re.search(r"ORD-\d+", text)) else "")
        return text + "\n\nKind regards,\nRetailCo Support", subject if first else None
    return text, None
