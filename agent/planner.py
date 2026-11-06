"""Layer 7 - Planning module: turn a goal into a validated DAG of tool steps.

Hybrid strategy: known intents load a programmatic template (deterministic,
auditable); novel requests ask the model for a plan in the same JSON shape,
which must pass validate_plan() before a single tool runs.

Argument values starting with "$" are references resolved at run time:
  $intent.order_id      -> the parsed intent
  $evaluate.refund_amount -> the result of step "evaluate"
`when` lists conditions on earlier results; "!" negates.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .tools import REGISTRY


@dataclass
class Step:
    id: str
    tool: str
    args: dict
    depends_on: list[str] = field(default_factory=list)
    when: list[str] = field(default_factory=list)


@dataclass
class Plan:
    goal: str
    steps: list[Step]
    source: str = "template"   # or "model"


TEMPLATES: dict[str, list[Step]] = {
    "track_order": [
        Step("verify", "get_order_details", {"order_id": "$intent.order_id"}),
        Step("track", "track_order", {"order_id": "$intent.order_id"}),
    ],
    "request_refund": [
        Step("verify", "get_order_details", {"order_id": "$intent.order_id"}),
        Step("track", "track_order", {"order_id": "$intent.order_id"}),          # runs in parallel
        Step("evaluate", "check_refund_eligibility", {"order_id": "$intent.order_id"},
             depends_on=["verify", "track"]),
        Step("approval", "request_approval",
             {"action": "issue_refund",
              "payload": {"order_id": "$intent.order_id", "amount": "$evaluate.refund_amount"}},
             depends_on=["evaluate"], when=["evaluate.eligible", "evaluate.needs_approval"]),
        Step("refund", "issue_refund",
             {"order_id": "$intent.order_id", "amount": "$evaluate.refund_amount",
              "idempotency_key": "$keys.refund"},
             depends_on=["evaluate"], when=["evaluate.eligible", "!evaluate.needs_approval"]),
        Step("notify", "send_email",
             {"template": "refund_confirmation",
              "payload": {"order_id": "$intent.order_id", "refund_id": "$refund.refund_id",
                          "amount": "$refund.amount"},
              "idempotency_key": "$keys.notify"},
             depends_on=["refund"], when=["refund.refund_id"]),
    ],
    "initiate_return": [
        Step("verify", "get_order_details", {"order_id": "$intent.order_id"}),
        Step("notify", "send_email",
             {"template": "return_label", "payload": {"order_id": "$intent.order_id"},
              "idempotency_key": "$keys.notify"}, depends_on=["verify"]),
    ],
    "update_address": [
        Step("verify", "get_order_details", {"order_id": "$intent.order_id"}),
    ],
}


class InvalidPlan(ValueError):
    pass


def from_template(intent: str, goal: str) -> Plan | None:
    steps = TEMPLATES.get(intent)
    if steps is None:
        return None
    return Plan(goal, [Step(s.id, s.tool, dict(s.args), list(s.depends_on), list(s.when)) for s in steps])


def validate_plan(plan: Plan, max_steps: int = 8) -> list[list[Step]]:
    """Check tools, arguments and dependencies; return steps grouped into parallel layers."""
    if not plan.steps or len(plan.steps) > max_steps:
        raise InvalidPlan(f"plan must have 1..{max_steps} steps")
    ids = [s.id for s in plan.steps]
    if len(set(ids)) != len(ids):
        raise InvalidPlan("duplicate step ids")
    for s in plan.steps:
        if s.tool not in REGISTRY:
            raise InvalidPlan(f"unknown tool {s.tool!r}")
        missing = [a for a in REGISTRY[s.tool]["args"] if a not in s.args]
        if missing:
            raise InvalidPlan(f"step {s.id}: missing args {missing}")
        for d in s.depends_on:
            if d not in ids:
                raise InvalidPlan(f"step {s.id}: unknown dependency {d!r}")
    # Kahn's algorithm: layers of steps whose dependencies are all earlier.
    remaining, done, layers = {s.id: s for s in plan.steps}, set(), []
    while remaining:
        layer = [s for s in remaining.values() if set(s.depends_on) <= done]
        if not layer:
            raise InvalidPlan("dependency cycle")
        layers.append(layer)
        for s in layer:
            done.add(s.id)
            del remaining[s.id]
    return layers


def plan_from_model_json(data: dict) -> Plan:
    """Parse a model-proposed plan. Validation happens separately, always."""
    steps = [Step(s["id"], s["tool"], s.get("args", {}), s.get("depends_on", []), s.get("when", []))
             for s in data.get("steps", [])]
    return Plan(data.get("goal", ""), steps, source="model")


PLAN_TOOL = {
    "name": "submit_plan",
    "description": "Submit an execution plan as a list of tool steps.",
    "input_schema": {
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "steps": {"type": "array", "maxItems": 8, "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "tool": {"type": "string", "enum": sorted(REGISTRY)},
                    "args": {"type": "object"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "when": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "tool", "args"]}},
        },
        "required": ["goal", "steps"],
    },
}
