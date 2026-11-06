"""Layer 1 and Layer 3 data contracts.

Every channel is normalised into a SupportRequest (Layer 1). The Understanding
layer turns raw text into a ParsedIntent (Layer 3). Nothing downstream ever
sees channel-specific payloads or free text without a schema around it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class Channel(str, Enum):
    CHAT = "chat"
    EMAIL = "email"
    API = "api"
    WEBHOOK = "webhook"
    SMS = "sms"


class SupportRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))  # trace id
    channel: Channel
    customer_id: str
    raw_text: str = Field(min_length=1, max_length=4000)
    metadata: dict = Field(default_factory=dict)
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    session_id: Optional[str] = None
    flags: list[str] = Field(default_factory=list)  # set by the safety layer


Intent = Literal[
    "track_order",
    "request_refund",
    "update_address",
    "product_query",
    "initiate_return",
    "general_enquiry",
    "out_of_scope",
    "escalate",
]

Sentiment = Literal["positive", "neutral", "frustrated", "furious"]


class ParsedIntent(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    order_id: Optional[str] = None
    customer_sentiment: Sentiment = "neutral"
    urgency: Literal["low", "medium", "high"] = "medium"
    summary: str = Field(description="One-sentence summary of what the customer wants")


class Route(str, Enum):
    DIRECT = "direct"      # answer from context / read-only lookups
    PLAN = "plan"          # multi-step workflow with tools
    CLARIFY = "clarify"    # ask a question before acting
    ESCALATE = "escalate"  # hand to a human


class AgentReply(BaseModel):
    request_id: str
    route: Route
    text: str
    channel: Channel
    subject: Optional[str] = None
    facts: dict = Field(default_factory=dict)
    needs_human: bool = False
