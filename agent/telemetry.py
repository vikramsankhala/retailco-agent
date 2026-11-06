"""Layer 13 - Monitoring: one trace per request, one span per layer, JSONL on disk.

The span shape (trace_id, name, start, duration_ms, attributes) maps one-to-one
onto OpenTelemetry, so exporting to Langfuse, LangSmith, Arize Phoenix or Datadog
is a change of exporter, not of instrumentation.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from . import config

metrics: Counter = Counter()   # route_*, escalations, verifier_fail, tool_error_*, ...


class Tracer:
    def __init__(self, path: Path = config.TRACE_FILE):
        self.path = path

    @contextmanager
    def span(self, trace_id: str, name: str, **attrs):
        start = time.perf_counter()
        record = {"trace_id": trace_id, "name": name, "start": time.time(), "attributes": attrs}
        try:
            yield record["attributes"]
            record["status"] = "ok"
        except Exception as e:
            record["status"], record["error"] = "error", repr(e)
            metrics[f"error_{name}"] += 1
            raise
        finally:
            record["duration_ms"] = round((time.perf_counter() - start) * 1000, 2)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")


def load_trace(trace_id: str, path: Path = config.TRACE_FILE) -> list[dict]:
    if not path.exists():
        return []
    return [r for line in path.read_text().splitlines() if (r := json.loads(line))["trace_id"] == trace_id]
