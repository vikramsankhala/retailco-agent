"""Module 15: retrieval that holds up."""
import json

from agent import adapters
from agent.retrieval import HashingEmbedder, HybridRetriever, chunk_markdown, cosine
from agent.safety import sign_session
from evals import run_retrieval_evals


def test_chunks_never_cross_a_heading_and_carry_it():
    md = "# A\n\none two.\n\n# B\n\nthree four."
    chunks = chunk_markdown(md, "doc")
    assert [(c.title, c.text) for c in chunks] == [("A", "one two."), ("B", "three four.")]
    assert chunks[1].indexed_text.startswith("B.")


def test_long_paragraph_splits_by_sentence_with_overlap():
    para = " ".join(f"Sentence {i} has five words." for i in range(10))
    chunks = chunk_markdown(f"# T\n\n{para}", "doc", max_words=12)
    assert len(chunks) > 2
    assert all(len(c.text.split()) <= 12 for c in chunks)
    first_end = chunks[0].text.split(". ")[-1]
    assert first_end.rstrip(".") in chunks[1].text      # one sentence repeated across the boundary


def test_embedding_is_deterministic_and_tolerates_typos():
    e = HashingEmbedder()
    assert e.embed("refund") == e.embed("refund")
    assert cosine(e.embed("refund"), e.embed("refnd")) > cosine(e.embed("refund"), e.embed("garden"))


def test_reciprocal_rank_fusion_rewards_agreement():
    a = [(1, 9.0), (2, 5.0), (3, 1.0)]
    b = [(2, 0.9), (3, 0.8), (1, 0.1)]
    fused = [i for i, _ in HybridRetriever.rrf(a, b)]
    assert fused[0] == 2          # ranked well by both lists beats first in only one


def test_customer_words_and_typos_find_the_right_policy():
    r = HybridRetriever()
    assert r.retrieve("my parcel turned up smashed").passages[0].source == "faulty-items"
    assert r.retrieve("how long dose a refnud take").passages[0].source == "refunds"


def test_retriever_abstains_when_no_policy_covers_the_question():
    res = HybridRetriever().retrieve("who won the football last night")
    assert res.status == "insufficient" and res.passages == []


def test_retrieval_eval_meets_targets():
    assert run_retrieval_evals.main() == 0


def test_trace_records_how_policy_was_found(agent, tmp_path):
    req = adapters.from_chat({"text": "What is your policy on how long refunds take?"}, "CUST-4821")
    import asyncio
    asyncio.run(agent.handle(req, sign_session("CUST-4821")))
    spans = [json.loads(l) for l in agent.tracer.path.read_text().splitlines()]
    mem = next(s for s in spans if s["name"] == "L4.memory")
    assert mem["attributes"]["retrieval"]["status"] in ("ok", "rewritten")
    assert mem["attributes"]["docs"][0] == "refunds"
