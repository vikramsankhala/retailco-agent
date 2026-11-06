"""Layer 1 - Input. One adapter per channel; every adapter returns a SupportRequest."""
from __future__ import annotations

import html
import re

from .schemas import Channel, SupportRequest

_ORDER_RE = re.compile(r"\bORD-?(\d{4,6})\b|\border\s*(?:no\.?|number|#)?\s*#?(\d{4,6})\b", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_QUOTED_RE = re.compile(r"(?ms)^On .+wrote:.*$|^>.*$")


def find_order_id(text: str) -> str | None:
    """Return a canonical ORD-nnnn id if the text mentions one."""
    m = _ORDER_RE.search(text)
    if not m:
        return None
    return f"ORD-{m.group(1) or m.group(2)}"


def from_chat(payload: dict, customer_id: str) -> SupportRequest:
    """Web-chat widget message. customer_id comes from the verified session, never the payload."""
    return SupportRequest(
        channel=Channel.CHAT,
        customer_id=customer_id,
        raw_text=payload["text"].strip(),
        session_id=payload.get("session_id"),
        metadata={"locale": payload.get("locale", "en-GB")},
    )


def from_email(ticket: dict) -> SupportRequest:
    """Helpdesk webhook: strip HTML and quoted replies, keep subject for order ids."""
    body = html.unescape(_TAG_RE.sub(" ", ticket["body_html"]))
    body = _QUOTED_RE.sub("", body)
    body = re.sub(r"\s+", " ", body).strip()
    subject = ticket.get("subject", "")
    return SupportRequest(
        channel=Channel.EMAIL,
        customer_id=ticket["requester_id"],
        raw_text=f"{subject}\n{body}".strip(),
        session_id=f"ticket-{ticket['ticket_id']}",
        metadata={"ticket_id": ticket["ticket_id"], "subject": subject,
                  "order_id_hint": find_order_id(subject + " " + body)},
    )


def from_carrier_event(event: dict) -> SupportRequest:
    """Logistics webhook: describe the event in plain language so the same pipeline handles it."""
    text = (f"Carrier {event['carrier']} reports order {event['order_id']} as "
            f"{event['status'].replace('_', ' ')} (reason: {event.get('reason_code', 'n/a')}).")
    return SupportRequest(
        channel=Channel.WEBHOOK,
        customer_id=event["customer_id"],
        raw_text=text,
        metadata={"event": event, "order_id_hint": event["order_id"]},
    )
