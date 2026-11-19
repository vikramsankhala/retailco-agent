"""Retrieval evaluation (Module 15). Compares the Module 7 baseline with each upgrade.

    python -m evals.run_retrieval_evals          # table; exits 1 if the full retriever is below target

Metrics, per configuration:
  hit@1           the expected article is the top result
  recall@3        the expected article is in the top three
  MRR             mean reciprocal rank of the expected article
  context recall  the fact needed for the answer (must_have) is in the passages returned
  abstain         for questions no policy covers, the retriever returns nothing
                  (a retriever that always returns something invites the model to improvise)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from agent.memory import KnowledgeBase
from agent.retrieval import HybridRetriever

CASES = [json.loads(l) for l in (Path(__file__).parent / "retrieval_golden.jsonl").read_text().splitlines() if l.strip()]
TARGETS = {"hit@1": 0.85, "context recall": 0.85, "abstain": 1.0}

CONFIGS = {
    "BM25 (Module 7 baseline)": lambda: KnowledgeBase(),
    "+ chunking and vectors (RRF)": lambda: HybridRetriever(use_rerank=False, use_rewrite=False),
    "+ reranking": lambda: HybridRetriever(use_rewrite=False),
    "+ query rewriting (full)": lambda: HybridRetriever(),
}


def run(retriever) -> dict:
    answerable = [c for c in CASES if c["expect"]]
    unanswerable = [c for c in CASES if not c["expect"]]
    hit1 = rec3 = mrr = ctx = 0.0
    per_kind: dict[str, list[int]] = {}
    for c in answerable:
        docs = retriever.search(c["q"], top_k=3)
        sources = [d.source for d in docs]
        rank = sources.index(c["expect"]) + 1 if c["expect"] in sources else 0
        hit1 += rank == 1
        rec3 += rank > 0
        mrr += 1 / rank if rank else 0
        ctx += any(c["must_have"].lower() in d.text.lower() for d in docs)
        per_kind.setdefault(c["kind"], []).append(int(rank == 1))
    abstain = sum(not retriever.search(c["q"], top_k=3) for c in unanswerable)
    n = len(answerable)
    out = {"hit@1": hit1 / n, "recall@3": rec3 / n, "MRR": mrr / n, "context recall": ctx / n,
           "abstain": abstain / len(unanswerable)}
    out.update({f"hit@1 {k}": sum(v) / len(v) for k, v in per_kind.items()})
    return out


def main() -> int:
    results = {name: run(make()) for name, make in CONFIGS.items()}
    main_cols = ["hit@1", "recall@3", "MRR", "context recall", "abstain"]
    print(f"{'configuration':30s}" + "".join(f"{c.replace('context ', 'ctx '):>11s}" for c in main_cols))
    for name, r in results.items():
        print(f"{name:30s}" + "".join(f"{r[c]:11.2f}" for c in main_cols))
    kinds = [k for k in next(iter(results.values())) if k.startswith("hit@1 ")]
    print(f"\n{'hit@1 by kind of question':30s}" + "".join(f"{k[6:][:14]:>16s}" for k in kinds))
    for name, r in results.items():
        print(f"{name:30s}" + "".join(f"{r[k]:16.2f}" for k in kinds))
    full = results["+ query rewriting (full)"]
    misses = [k for k, target in TARGETS.items() if full[k] < target]
    print("\ntargets met" if not misses else f"\nbelow target: {misses}")
    if "--json" in sys.argv:
        print(json.dumps(results))
    return 1 if misses else 0


if __name__ == "__main__":
    sys.exit(main())
