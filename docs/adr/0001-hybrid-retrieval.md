# ADR-0001: Replace BM25-only retrieval with hybrid retrieval

- Status: accepted
- Date: 2024-11-05 (lab date)
- Deciders: engineering lead, support operations lead

## Context
R11 requires policy answers only from approved articles. With ten articles, BM25 alone found the
right article first for 73% of the retrieval golden set and returned an unrelated article for
questions no policy covers (abstain rate 75%). Customers rarely use the policy's own words.

## Options considered
| Option | For | Against |
|---|---|---|
| Keep BM25 | Simple, no new parts | Misses paraphrases and typos; answers questions it should not |
| Vector search only | Handles typos | Never abstains: always returns its nearest article |
| Hybrid: BM25 + vectors (RRF) + rerank + rewrite | Best on every metric | More moving parts to test |

## Decision
Use `retrieval.HybridRetriever` by default; keep BM25 selectable (`RETAILCO_RETRIEVER=bm25`) as the
baseline for A/B comparison.

## Consequences
Retrieval golden set: hit@1 0.73 to 0.91, context recall 0.77 to 1.00, abstain 0.75 to 1.00.
The rewrite rules were tuned on the same golden set, so they are at risk of overfitting:
add new real customer questions to the set every month and watch hit@1 on those first.
Revisit if hit@1 on new questions falls below 0.85.

## Evidence
`python -m evals.run_retrieval_evals`; `python -m evals.compare` (fixes g13, g14, g15; breaks none).
