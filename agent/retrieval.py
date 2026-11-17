"""Layer 4 in depth: retrieval that holds up (Module 15).

The Module 7 knowledge base ranks paragraphs with BM25 alone. That works when
customers use the policy's own words and fails when they do not ("my parcel
turned up smashed" shares no words with "Damaged or faulty items"). This module
adds the pieces a production retriever needs, each one small and testable:

  1. chunk_markdown()  heading-aware chunks; each chunk carries its heading, so
                       "Refunds usually take 3 to 5 business days" is indexed
                       as part of "Late Delivery Guarantee and refunds"
  2. HashingEmbedder   an offline, deterministic embedding (word and character
                       n-grams hashed into a sparse vector). It catches spelling
                       variants and typos. Swap in a hosted embedding model by
                       implementing the same embed() method.
  3. HybridRetriever   BM25 and vector search run side by side and are merged
                       with reciprocal rank fusion (RRF)
  4. rerank()          a second, closer look at the top candidates
  5. rewrite()         when the best match is weak, rewrite the question and try
                       again once; if it is still weak, say so ("insufficient")
                       instead of passing a poor match to the model

Every stage is visible in RetrievalResult, so the trace shows why a passage won.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Protocol

from . import config
from .memory import tokens

_SENT = re.compile(r"(?<=[.!?])\s+")


# --- 1. Chunking ------------------------------------------------------------------
@dataclass
class Passage:
    source: str            # article file stem, e.g. "refunds"
    chunk_id: str          # "refunds#2"
    title: str             # nearest heading
    text: str

    @property
    def indexed_text(self) -> str:
        """What the retriever sees: heading + text (a cheap form of contextual chunking)."""
        return f"{self.title}. {self.text}"


def chunk_markdown(markdown: str, source: str, max_words: int = 80, overlap: int = 1) -> list[Passage]:
    """Split an article into passages of at most max_words, never across headings.

    Short paragraphs under one heading are kept together; a long paragraph is
    split by sentence with `overlap` sentences repeated, so a rule that spans a
    boundary still appears whole in one passage.
    """
    passages: list[Passage] = []
    title, buf = source, []

    def flush():
        if buf:
            passages.append(Passage(source, f"{source}#{len(passages)}", title, " ".join(buf)))
            buf.clear()

    for block in re.split(r"\n\s*\n", markdown):
        block = block.strip()
        if not block:
            continue
        if block.startswith("#"):
            flush()
            title = block.lstrip("# ").strip()
            continue
        words = len(block.split())
        if words > max_words:
            flush()
            sents = _SENT.split(block)
            i = 0
            while i < len(sents):
                take, n = [], 0
                while i < len(sents) and (n + len(sents[i].split()) <= max_words or not take):
                    take.append(sents[i]); n += len(sents[i].split()); i += 1
                passages.append(Passage(source, f"{source}#{len(passages)}", title, " ".join(take)))
                if i < len(sents):
                    i = max(i - overlap, i - len(take) + 1)
            continue
        if sum(len(b.split()) for b in buf) + words > max_words:
            flush()
        buf.append(block)
    flush()
    return passages


# --- 2. Embeddings ----------------------------------------------------------------
class Embedder(Protocol):
    def embed(self, text: str) -> dict[int, float]: ...


class HashingEmbedder:
    """Offline embedding: hashed word unigrams, word bigrams and character 4-grams.

    Not a semantic model, but it needs no service, never changes between runs,
    and matches 'refnd' to 'refund' and 'collecting' to 'collect'. Production
    systems use a trained embedding model behind the same interface.
    """

    def __init__(self, dim: int = 2048):
        self.dim = dim

    def _features(self, text: str) -> Counter:
        words = tokens(text)
        feats: Counter = Counter()
        for w in words:
            feats[f"w:{w}"] += 1.0
            padded = f"<{w}>"
            for i in range(max(1, len(padded) - 3)):
                feats[f"c:{padded[i:i + 4]}"] += 0.5
        for a, b in zip(words, words[1:]):
            feats[f"b:{a}_{b}"] += 0.7
        return feats

    def embed(self, text: str) -> dict[int, float]:
        vec: dict[int, float] = {}
        for feat, weight in self._features(text).items():
            h = int.from_bytes(hashlib.blake2b(feat.encode(), digest_size=8).digest(), "big")
            idx, sign = h % self.dim, (1.0 if (h >> 63) & 1 else -1.0)
            vec[idx] = vec.get(idx, 0.0) + sign * (1 + math.log(weight + 1))
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {k: v / norm for k, v in vec.items()}


def cosine(a: dict[int, float], b: dict[int, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


# --- 5. Query rewriting (offline rules; live mode can use the fast model) ---------
REWRITES = {
    r"\b(parcel|package)\b": "order delivery",
    r"\bmoney back\b|\bcash back\b|\breimburse\w*": "refund",
    r"\b(broken|smashed|cracked|damaged|faulty|doesn'?t work|not working)\b": "damaged faulty item",
    r"\b(missing|didn'?t (come|arrive)|not everything)\b": "item missing second parcel",
    r"\bmoved (house|home)\b|\bnew (address|place)\b|\bwrong address\b": "change delivery address",
    r"\b(send|take)\b.{0,25}\bback\b": "return order",
    r"\bpick (it |them )?up\b|\bcollect(ion)?\b|\b(shop|store)\b": "click and collect store",
    r"\b(christmas|xmas|festive)\b": "christmas peak season",
    r"\b(wipe|erase|delete|remove)\b.{0,30}\b(data|account|details)\b|\bgdpr\b": "personal data account privacy",
    r"\b(complain\w*|manager|supervisor|human|real person)\b": "complaint talk to a person",
    r"\b(declined|bank said no|payment failed)\b": "payment declined",
}


def rewrite_offline(query: str) -> str:
    """Add the policy's own vocabulary to the customer's words. Returns the query unchanged if no rule fires."""
    extra = [repl for pat, repl in REWRITES.items() if re.search(pat, query, re.I)]
    return f"{query} {' '.join(extra)}" if extra else query


# Conversational filler: common in chat, carries no policy meaning.
FILLER = set("want need like get got just really still thing things stuff lot whole one half bit "
             "hi hello hey thanks thank please ok okay im ive dont didn didnt doesnt cant".split())
UNKNOWN_WEIGHT = 0.6     # weight of an unseen word, as a share of the rarest known word's IDF


# --- 3 and 4. The retriever ----------------------------------------------------------
@dataclass
class Scored:
    passage: Passage
    score: float                                  # rerank score in [0, 1]
    ranks: dict[str, int] = field(default_factory=dict)   # rank in each list, for the trace
    via: str = "original"                                 # which query found it


@dataclass
class RetrievalResult:
    query: str
    queries_tried: list[str]
    hits: list[Scored]
    status: str                                   # "ok" | "rewritten" | "insufficient"
    quarantined: list[str] = field(default_factory=list)

    @property
    def passages(self) -> list[Passage]:
        return [h.passage for h in self.hits]

    def trace(self) -> dict:
        return {"status": self.status, "queries": self.queries_tried,
                "hits": [{"id": h.passage.chunk_id, "score": round(h.score, 3), "ranks": h.ranks, "via": h.via}
                         for h in self.hits]}


Reranker = Callable[[str, list[Passage]], list[float]]


class HybridRetriever:
    """BM25 + vector search, fused with RRF, reranked, with one corrective retry."""

    def __init__(self, kb_dir: Path = config.KB_DIR, embedder: Embedder | None = None,
                 reranker: Reranker | None = None, rewriter: Callable[[str], str] | None = None,
                 use_vector: bool = True, use_rerank: bool = True, use_rewrite: bool = True,
                 k1: float = 1.5, b: float = 0.75):
        from .kb_integrity import load_trusted_articles   # Module 16: only approved, clean articles
        self.embedder = embedder or HashingEmbedder()
        self.reranker = reranker or self._rerank_offline
        self.rewriter = rewriter or rewrite_offline
        self.use_vector, self.use_rerank, self.use_rewrite = use_vector, use_rerank, use_rewrite
        self.k1, self.b = k1, b
        articles, self.quarantined = load_trusted_articles(Path(kb_dir))
        self.passages: list[Passage] = []
        for source, text in articles:
            self.passages += chunk_markdown(text, source)
        self._terms = [Counter(tokens(p.indexed_text)) for p in self.passages]
        self._vecs = [self.embedder.embed(p.indexed_text) for p in self.passages]
        n = len(self.passages)
        self.avgdl = sum(sum(t.values()) for t in self._terms) / max(1, n)
        df = Counter(t for terms in self._terms for t in terms)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    # individual rankers ---------------------------------------------------------
    def bm25(self, query: str) -> list[tuple[int, float]]:
        q, out = tokens(query), []
        for i, terms in enumerate(self._terms):
            dl, s = sum(terms.values()), 0.0
            for t in q:
                f = terms.get(t, 0)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            if s > 0:
                out.append((i, s))
        return sorted(out, key=lambda x: -x[1])

    def vector(self, query: str) -> list[tuple[int, float]]:
        qv = self.embedder.embed(query)
        out = [(i, cosine(qv, v)) for i, v in enumerate(self._vecs)]
        return sorted([x for x in out if x[1] > 0], key=lambda x: -x[1])

    @staticmethod
    def rrf(*rankings: list[tuple[int, float]], k: int = config.RRF_K) -> list[tuple[int, float]]:
        """Reciprocal rank fusion: score = sum of 1 / (k + rank). Uses ranks only, so the
        very different score scales of BM25 and cosine similarity never need calibrating."""
        fused: dict[int, float] = {}
        for ranking in rankings:
            for rank, (i, _) in enumerate(ranking, start=1):
                fused[i] = fused.get(i, 0.0) + 1.0 / (k + rank)
        return sorted(fused.items(), key=lambda x: -x[1])

    @staticmethod
    def _close(a: str, b: str) -> bool:
        """Same word, a shared stem (talk / talking) or a likely typo (refnd / refund)."""
        if a == b:
            return True
        if min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)):
            return True
        return min(len(a), len(b)) >= 4 and SequenceMatcher(None, a, b).ratio() >= 0.8

    def _rerank_offline(self, query: str, cands: list[Passage]) -> list[float]:
        """Closer look at a short list, scored in [0, 1]:

        coverage   how much of the query's meaningful vocabulary the passage contains,
                   each term weighted by how rare it is in the knowledge base (IDF),
                   tolerant of word endings and typos;
                   Words the knowledge base has never seen count against the match
                   (a question about football is mostly words we have no policy on);
                   conversational filler ("stuff", "thing") is ignored;
        similarity cosine similarity of the embeddings.
        A live system can swap in a model-based reranker with the same signature.
        """
        q = [t for t in dict.fromkeys(tokens(query)) if t not in FILLER]
        vocab = list(self.idf)
        top_idf = max(self.idf.values()) if self.idf else 1.0
        weight, known = {}, set()
        for t in q:
            matches = [v for v in vocab if self._close(t, v)]
            if matches:
                weight[t] = max(self.idf[v] for v in matches)
                known.add(t)
            else:
                weight[t] = top_idf * UNKNOWN_WEIGHT   # a word we have never seen is informative
        qv = self.embedder.embed(query)
        scores = []
        for p in cands:
            words = set(tokens(p.indexed_text))
            covered = sum(w for t, w in weight.items() if t in known and any(self._close(t, x) for x in words))
            coverage = covered / sum(weight.values()) if weight else 0.0
            sim = max(0.0, cosine(qv, self.embedder.embed(p.indexed_text)))
            scores.append(0.6 * coverage + 0.4 * sim)
        return scores

    def _rank(self, query: str, top_k: int) -> list[Scored]:
        lists = {"bm25": self.bm25(query)}
        if self.use_vector:
            lists["vector"] = self.vector(query)
        fused = self.rrf(*lists.values()) if len(lists) > 1 else lists["bm25"]
        cands = [i for i, _ in fused[:config.RERANK_CANDIDATES]]
        if not cands:
            return []
        position = {name: {i: r for r, (i, _) in enumerate(lst, start=1)} for name, lst in lists.items()}
        if self.use_rerank:
            scores = self.reranker(query, [self.passages[i] for i in cands])
        else:   # no reranker: normalise the fused score so thresholds still mean something
            top = fused[0][1]
            scores = [s / top for _, s in fused[:len(cands)]]
        hits = [Scored(self.passages[i], s, {n: position[n].get(i, 0) for n in lists})
                for i, s in zip(cands, scores)]
        return sorted(hits, key=lambda h: -h.score)[:top_k]

    # public API ------------------------------------------------------------------
    def retrieve(self, query: str, top_k: int = 3) -> RetrievalResult:
        """Rank, rewrite, check. The offline rewriter costs nothing, so it always runs and the
        two result lists are merged (each passage keeps its better score). A model-based
        rewriter costs a call, so it runs only when the first result is weak: corrective retrieval."""
        tried = [query]
        hits = self._rank(query, top_k + 2)
        best = hits[0].score if hits else 0.0
        if self.use_rewrite and (self.rewriter is rewrite_offline or best < config.RETRIEVAL_MIN_SCORE):
            better = self.rewriter(query)
            if better != query:
                tried.append(better)
                merged = {h.passage.chunk_id: h for h in hits}
                for h in self._rank(better, top_k + 2):
                    cur = merged.get(h.passage.chunk_id)
                    if cur is None or h.score > cur.score:
                        h.via = "rewritten"
                        merged[h.passage.chunk_id] = h
                hits = sorted(merged.values(), key=lambda h: -h.score)
        hits = hits[:top_k]
        best = hits[0].score if hits else 0.0
        if best < config.RETRIEVAL_MIN_SCORE:
            return RetrievalResult(query, tried, [], "insufficient", self.quarantined)
        status = "rewritten" if hits[0].via == "rewritten" else "ok"
        hits = [h for h in hits if h.score >= best * 0.5]   # drop passages far below the best
        return RetrievalResult(query, tried, hits, status, self.quarantined)

    def search(self, query: str, top_k: int = 3) -> list[Passage]:
        """Same signature as KnowledgeBase.search, so the rest of the agent is unchanged."""
        return self.retrieve(query, top_k).passages
