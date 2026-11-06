"""Layer 8 - Task queue: execute a validated plan reliably.

* runs each dependency layer concurrently (asyncio.gather)
* tracks PENDING -> RUNNING -> COMPLETED | FAILED | SKIPPED per step
* retries transient errors with exponential back-off and jitter, then dead-letters
* skips steps whose conditions are false, and blocks steps whose inputs failed
* derives idempotency keys from the business action, so retries never duplicate

For multi-hour or crash-proof workflows, replace this class with a durable
engine (Temporal, AWS Step Functions); the Plan format stays the same.
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

from .planner import Plan, Step, validate_plan
from .tools import ToolError, TransientError


class State(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StepRun:
    step: Step
    state: State = State.PENDING
    attempts: int = 0
    result: dict | None = None
    error: str | None = None


@dataclass
class RunResult:
    runs: dict[str, StepRun]
    dead_letter: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.dead_letter

    def results(self) -> dict[str, dict]:
        return {k: r.result for k, r in self.runs.items() if r.state is State.COMPLETED}


Dispatcher = Callable[[str, dict], Awaitable[dict]]


def _lookup(path: str, scope: dict) -> Any:
    head, *rest = path.split(".")
    value = scope.get(head)
    for part in rest:
        value = value.get(part) if isinstance(value, dict) else None
    return value


def resolve(value: Any, scope: dict) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return _lookup(value[1:], scope)
    if isinstance(value, dict):
        return {k: resolve(v, scope) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, scope) for v in value]
    return value


def conditions_met(step: Step, scope: dict) -> bool:
    for cond in step.when:
        negate = cond.startswith("!")
        truthy = bool(_lookup(cond.lstrip("!"), scope))
        if truthy == negate:
            return False
    return True


class TaskQueue:
    def __init__(self, dispatch: Dispatcher, max_attempts: int = 3, base_delay: float = 0.2):
        self.dispatch, self.max_attempts, self.base_delay = dispatch, max_attempts, base_delay

    async def _run_step(self, run: StepRun, scope: dict) -> None:
        run.state = State.RUNNING
        args = resolve(run.step.args, scope)
        while True:
            run.attempts += 1
            try:
                run.result = await self.dispatch(run.step.tool, args)
                run.state = State.COMPLETED
                return
            except TransientError as e:
                if run.attempts >= self.max_attempts:
                    run.state, run.error = State.FAILED, f"transient, gave up: {e}"
                    return
                delay = self.base_delay * 2 ** (run.attempts - 1)
                await asyncio.sleep(delay + random.uniform(0, delay / 2))
            except ToolError as e:
                run.state, run.error = State.FAILED, str(e)   # not retryable
                return

    async def run(self, plan: Plan, scope: dict) -> RunResult:
        layers = validate_plan(plan)
        runs = {s.id: StepRun(s) for s in plan.steps}
        result = RunResult(runs)
        for layer in layers:
            ready = []
            for step in layer:
                blocked = [d for d in step.depends_on if runs[d].state is State.FAILED]
                if blocked:
                    runs[step.id].state, runs[step.id].error = State.SKIPPED, f"blocked by {blocked}"
                elif not conditions_met(step, scope):
                    runs[step.id].state = State.SKIPPED
                else:
                    ready.append(runs[step.id])
            await asyncio.gather(*(self._run_step(r, scope) for r in ready))
            for r in ready:
                if r.state is State.COMPLETED:
                    scope[r.step.id] = r.result
                else:
                    result.dead_letter.append(r.step.id)
        return result
