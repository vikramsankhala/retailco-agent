"""The 13 layers wired together. One call to SupportAgent.handle() = one traced request.

  1 Input (adapters) -> 2 Safety -> 3 Understanding -> 4 Memory -> 6 Decision
     DIRECT   -> 5 Reasoning (ReAct, read-only tools)          -> 12 Output
     PLAN     -> 7 Planning -> 8 Task queue -> 9/10 Tools via MCP or direct dispatch
                 -> 11 Result check (loop back to 5 with feedback, max 3) -> 12 Output
     CLARIFY  -> 12 Output (question)
     ESCALATE -> tool: escalate_to_human -> 12 Output
  13 Monitoring wraps every step with a span; metrics count routes and failures.
"""
from __future__ import annotations

import sqlite3

from . import config, reasoning
from . import tools as T
from .memory import KnowledgeBase, MemoryModule, SessionStore
from .output import clarify_question, compose_offline, format_for_channel
from .planner import InvalidPlan, from_template, validate_plan
from .router import decide
from .safety import SafetyPipeline
from .schemas import AgentReply, Route, SupportRequest
from .taskqueue import TaskQueue
from .telemetry import Tracer, metrics
from .understanding import understand
from .verifier import verify


class SupportAgent:
    def __init__(self, conn: sqlite3.Connection, carrier: T.Carrier | None = None,
                 kb: KnowledgeBase | None = None, tracer: Tracer | None = None,
                 safety: SafetyPipeline | None = None, retry_delay: float = 0.2):
        self.conn = conn
        self.carrier = carrier or T.Carrier(conn)
        self.kb = kb or KnowledgeBase()
        self.memory = MemoryModule(SessionStore(conn), self.kb)
        self.tracer = tracer or Tracer()
        self.safety = safety or SafetyPipeline()
        self.queue = TaskQueue(self.dispatch, base_delay=retry_delay)

    # Layer 9: direct dispatch used by the task queue (same functions the MCP server exposes)
    async def dispatch(self, tool: str, args: dict) -> dict:
        c = self.conn
        table = {
            "get_order_details": lambda a: T.get_order_details(c, a["order_id"]),
            "track_order": lambda a: self.carrier.track(a["order_id"]),
            "check_refund_eligibility": lambda a: T.check_refund_eligibility(c, a["order_id"]),
            "issue_refund": lambda a: T.issue_refund(c, a["order_id"], a["amount"], a["idempotency_key"],
                                                     a.get("approved_by")),
            "request_approval": lambda a: T.request_approval(c, a["action"], a["payload"]),
            "send_email": lambda a: T.send_email(c, a["template"], a["payload"], a["idempotency_key"]),
            "escalate_to_human": lambda a: T.escalate_to_human(c, a["reason"]),
            "search_knowledge_base": lambda a: T.search_knowledge_base(self.kb, a["query"]),
        }
        return table[tool](args)

    def _name(self, customer_id: str) -> str:
        row = self.conn.execute("SELECT name FROM customers WHERE customer_id=?", (customer_id,)).fetchone()
        return row["name"] if row else "there"

    async def handle(self, req: SupportRequest, session_token: str | None = None) -> AgentReply:
        tid, span = req.request_id, self.tracer.span
        T.current_customer.set(req.customer_id)
        T.current_request.set(tid)

        with span(tid, "L2.safety", channel=req.channel.value) as a:
            req = self.safety.run(req, session_token)
            a["flags"] = req.flags
        with span(tid, "L3.understanding") as a:
            history = self.memory.sessions.history(req.session_id)
            intent = await understand(req, history)
            a.update(intent.model_dump())
        with span(tid, "L4.memory") as a:
            ctx = self.memory.assemble(req, intent)
            a.update(turns=len(ctx.history), docs=[d.source for d in ctx.docs], summarised=bool(ctx.summary))
        with span(tid, "L6.decision") as a:
            decision = decide(ctx)
            a.update(route=decision.route.value, reason=decision.reason)
        metrics[f"route_{decision.route.value}"] += 1

        name, facts, text = self._name(req.customer_id), {}, ""
        if decision.route is Route.CLARIFY:
            text = clarify_question(intent)
        elif decision.route is Route.ESCALATE:
            with span(tid, "L9.escalate"):
                facts["escalation"] = T.escalate_to_human(self.conn, decision.reason)
            metrics["escalations"] += 1
            text = (f"Hi {name}, I'm sorry for the trouble. I've passed this to a member of our team, "
                    "who will reply within 2 hours.")
        elif decision.route is Route.DIRECT:
            with span(tid, "L5.reasoning.react"):
                text = await reasoning.react_answer(ctx, self.conn, self.carrier, self.kb)
        else:
            text, facts, decision = await self._plan_and_execute(ctx, name, decision)

        if req.channel.value == "chat" and not history:
            text = f"{config.AI_DISCLOSURE}\n\n{text}"   # disclosure is code, not left to the model
        with span(tid, "L12.output") as a:
            body, subject = format_for_channel(text, req.channel)
            a["chars"] = len(body)
        if req.session_id:
            self.memory.sessions.append(req.session_id, "customer", req.raw_text)
            self.memory.sessions.append(req.session_id, "agent", body)
        return AgentReply(request_id=tid, route=decision.route, text=body, subject=subject,
                          channel=req.channel, facts=facts, needs_human=decision.needs_human)

    async def _plan_and_execute(self, ctx, name, decision):
        tid, span, intent = ctx.request.request_id, self.tracer.span, ctx.intent
        with span(tid, "L7.planning") as a:
            plan = from_template(intent.intent, intent.summary) or await reasoning.model_plan(ctx)
            try:
                if plan is None:
                    raise InvalidPlan("no template and no model plan")
                layers = validate_plan(plan)
                a.update(source=plan.source, layers=[[s.id for s in l] for l in layers])
            except InvalidPlan as e:
                a["invalid"] = str(e)
                metrics["invalid_plan"] += 1
                facts = {"escalation": T.escalate_to_human(self.conn, f"invalid plan: {e}")}
                decision.route, decision.needs_human = Route.ESCALATE, True
                return (f"Hi {name}, I've passed this to a colleague who can sort it out. "
                        "They'll reply within 2 hours."), facts, decision

        oid = intent.order_id
        scope = {"intent": intent.model_dump(),
                 "keys": {"refund": f"refund:{oid}", "notify": f"notify:{oid}:{intent.intent}"}}
        with span(tid, "L8.queue") as a:
            run = await self.queue.run(plan, scope)
            a.update({k: {"state": r.state.value, "attempts": r.attempts, "error": r.error}
                      for k, r in run.runs.items()})
        facts = run.results()
        verify_step = run.runs.get("verify")
        if verify_step and verify_step.error and "not found" in verify_step.error:
            # Not the customer's order (or a typo): ask, never reveal whether it exists.
            decision.route = Route.CLARIFY
            return (f"Hi {name}, I couldn't find {oid} on your account. Could you check the order "
                    "number in your confirmation email?"), {}, decision

        # Layer 11 + loop back to Layer 5: draft, check, correct (max MAX_LOOP_ITERATIONS)
        feedback = None
        for attempt in range(1, config.MAX_LOOP_ITERATIONS + 1):
            with span(tid, "L5.compose", attempt=attempt):
                draft = (await reasoning.compose_reply(ctx, facts, name, feedback) if config.LIVE
                         else compose_offline(intent, facts, name))
            with span(tid, "L11.result_check", attempt=attempt) as a:
                verdict = verify(draft, facts, run)
                a.update(passed=verdict.passed, problems=verdict.problems)
            if verdict.passed:
                return draft, facts, decision
            metrics["verifier_fail"] += 1
            if verdict.hard_stop or run.dead_letter:
                break
            feedback = "; ".join(verdict.problems)

        facts["escalation"] = T.escalate_to_human(self.conn, "result check failed: " + "; ".join(verdict.problems))
        decision.route, decision.needs_human = Route.ESCALATE, True
        metrics["escalations"] += 1
        return (f"Hi {name}, I couldn't complete this automatically, so I've passed it to a colleague "
                "with everything they need. They'll reply within 2 hours."), facts, decision
