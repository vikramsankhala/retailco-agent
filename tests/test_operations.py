"""Module 18: service levels, drift, A/B gate, shared rate limits, deployment basics."""
import json

from agent import config
from agent.drift import psi, verdict
from agent.safety import Action, RedisRateLimiter
from agent.slo import compute, error_budget, evaluate, percentile
from evals import compare
from scripts import kb_manifest


def _write(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_slis_from_request_records(tmp_path):
    rows = [{"name": "request", "trace_id": str(i), "duration_ms": 100 * (i + 1),
             "attributes": {"route": "escalate" if i == 0 else "plan", "needs_human": i == 0,
                            "intent": "track_order", "est_cost_gbp": 0.01}} for i in range(10)]
    rows += [{"name": "L11.result_check", "trace_id": "1", "attributes": {"passed": False}},
             {"name": "L11.result_check", "trace_id": "2", "attributes": {"passed": True}}]
    _write(tmp_path / "t.jsonl", rows)
    sli = compute(tmp_path / "t.jsonl")
    assert sli["requests"] == 10 and sli["containment"] == 0.9
    assert sli["p95_latency_ms"] == percentile([100 * (i + 1) for i in range(10)], 0.95)
    assert abs(sli["cost_per_contact_gbp"] - 0.01) < 1e-9 and sli["verifier_fail_rate"] == 0.5
    status = {r["sli"]: r["met"] for r in evaluate(sli)}
    assert status["containment"] and not status["verifier_fail_rate"]


def test_objectives_match_the_case_targets():
    assert config.SLO["containment"] == 0.75                 # Table A9: containment > 75%
    assert config.SLO["p95_latency_ms"] == 30_000            # first response < 30 s
    assert config.SLO["cost_per_contact_gbp"] == 0.15        # cost per contact < £0.15


def test_error_budget_burn():
    assert error_budget(0.80)["burn"] < 1 < error_budget(0.70)["burn"]


def test_psi_separates_stable_from_shifted_traffic():
    base = {"track_order": 500, "request_refund": 300, "general_enquiry": 200}
    assert verdict(psi(base, {"track_order": 510, "request_refund": 290, "general_enquiry": 200})) == "stable"
    peak = {"track_order": 300, "request_refund": 600, "general_enquiry": 100}   # December
    assert verdict(psi(base, peak)) == "shifted"


class FakeRedis:
    def __init__(self):
        self.d = {}

    def incr(self, k):
        self.d[k] = self.d.get(k, 0) + 1
        return self.d[k]

    def expire(self, k, s):
        pass


def test_rate_limit_is_shared_across_replicas():
    store = FakeRedis()
    replica_a, replica_b = RedisRateLimiter(store, limit=3, clock=lambda: 0), RedisRateLimiter(store, limit=3, clock=lambda: 0)
    results = [r.check("CUST-4821").action for r in (replica_a, replica_b, replica_a, replica_b)]
    assert results == [Action.PASS, Action.PASS, Action.PASS, Action.BLOCK]


def test_ab_gate_passes_hybrid_over_bm25(capsys):
    assert compare.main([]) == 0
    out = capsys.readouterr().out
    assert "fixed by B: ['g13', 'g14', 'g15']" in out and "broken by B: none" in out


def test_knowledge_base_is_approved():
    assert kb_manifest.main(["--check"]) == 0


def test_container_files_are_consistent():
    dockerfile = (config.ROOT / "Dockerfile").read_text()
    assert "AS build" in dockerfile and "AS runtime" in dockerfile and "USER app" in dockerfile
    assert "scripts.migrate" in dockerfile and "scripts.seed" not in dockerfile   # never wipe state on start
    compose = (config.ROOT / "docker-compose.yml").read_text()
    assert "/metrics/prometheus" in (config.ROOT / "deploy" / "prometheus.yml").read_text()
    assert "redis" in compose and "agent-state:/app/state" in compose
    json.loads((config.ROOT / "deploy" / "grafana" / "dashboards" / "retailco-agent.json").read_text())
