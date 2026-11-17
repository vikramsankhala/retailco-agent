"""Layer 13 - Monitoring: one trace per request, one span per layer, JSONL on disk.

The span shape (trace_id, name, start, duration_ms, attributes) maps one-to-one
onto OpenTelemetry, so exporting to Langfuse, LangSmith, Arize Phoenix or Datadog
is a change of exporter, not of instrumentation.
"""
from __future__ import annotations

import contextvars
import json
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from . import config
from .privacy import redact_obj

metrics: Counter = Counter()   # route_*, escalations, verifier_fail, tool_error_*, ...

# Request latency histogram for Prometheus (Module 18). Bucket bounds in milliseconds.
LATENCY_BUCKETS_MS = (100, 250, 500, 1000, 2500, 5000, 10000, 30000)
latency_hist: Counter = Counter()      # bucket bound -> count (cumulative counts are built on export)
latency_sum_ms = [0.0]

# Progress events for streaming (Module 17): set to an asyncio.Queue for one request,
# and every span start is announced on it, so the customer sees the agent working.
progress: contextvars.ContextVar = contextvars.ContextVar("progress", default=None)

LAYER_LABELS = {"L2.safety": "Checking your request", "L3.understanding": "Understanding your message",
                "L4.memory": "Looking up our policies", "L7.planning": "Planning the steps",
                "L8.queue": "Checking your order", "L11.result_check": "Double-checking the answer",
                "L12.output": "Writing the reply"}


def observe_latency(ms: float) -> None:
    latency_sum_ms[0] += ms
    for bound in LATENCY_BUCKETS_MS:
        if ms <= bound:
            latency_hist[bound] += 1
            return
    latency_hist["+Inf"] += 1


def prometheus_text() -> str:
    """Counters and the latency histogram in Prometheus text format, for /metrics/prometheus."""
    lines = ["# TYPE retailco_events_total counter"]
    for name, value in sorted(metrics.items()):
        lines.append(f'retailco_events_total{{event="{name}"}} {value}')
    lines.append("# TYPE retailco_request_latency_ms histogram")
    running = 0
    for bound in LATENCY_BUCKETS_MS:
        running += latency_hist[bound]
        lines.append(f'retailco_request_latency_ms_bucket{{le="{bound}"}} {running}')
    running += latency_hist["+Inf"]
    lines.append(f'retailco_request_latency_ms_bucket{{le="+Inf"}} {running}')
    lines.append(f"retailco_request_latency_ms_sum {latency_sum_ms[0]:.1f}")
    lines.append(f"retailco_request_latency_ms_count {running}")
    return "\n".join(lines) + "\n"


class Tracer:
    def __init__(self, path: Path = config.TRACE_FILE):
        self.path = path

    @contextmanager
    def span(self, trace_id: str, name: str, **attrs):
        start = time.perf_counter()
        record = {"trace_id": trace_id, "name": name, "start": time.time(), "attributes": attrs}
        if (q := progress.get()) is not None and name in LAYER_LABELS:
            q.put_nowait({"layer": name, "label": LAYER_LABELS[name]})
        try:
            yield record["attributes"]
            record["status"] = "ok"
        except Exception as e:
            record["status"], record["error"] = "error", repr(e)
            metrics[f"error_{name}"] += 1
            raise
        finally:
            record["duration_ms"] = round((time.perf_counter() - start) * 1000, 2)
            record["attributes"] = redact_obj(record["attributes"])   # no personal data in traces
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")


    def event(self, trace_id: str, name: str, duration_ms: float, **attrs) -> None:
        """One summary record per request (Module 18): the unit service levels are measured in."""
        record = {"trace_id": trace_id, "name": name, "start": time.time(), "status": "ok",
                  "duration_ms": round(duration_ms, 2), "attributes": redact_obj(attrs)}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")


def load_trace(trace_id: str, path: Path = config.TRACE_FILE) -> list[dict]:
    if not path.exists():
        return []
    return [r for line in path.read_text().splitlines() if (r := json.loads(line))["trace_id"] == trace_id]
