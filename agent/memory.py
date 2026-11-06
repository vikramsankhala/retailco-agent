"""Layer 4 - Memory: short-term (context assembly), episodic (session turns),
semantic (knowledge-base retrieval) and procedural (the system prompt, see reasoning.py).

Retrieval uses BM25 so the lab runs with no embedding service. In production,
swap KnowledgeBase.search for pgvector + an embedding model; the interface stays.
"""
from __future__ import annotations

import math
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .schemas import ParsedIntent, SupportRequest

_WORD = re.compile(r"[a-z0-9£]+")


_STOP = set("a an and are as at be by can do does for from has have how i if in is it its my of on or "
            "our please so that the their this to was we what when where which who will with you your".split())


def tokens(text: str) -> list[str]:
    """Lower-case words, stop words removed, naive plural stripping (refunds -> refund)."""
    out = []
    for w in _WORD.findall(text.lower()):
        if w in _STOP:
            continue
        out.append(w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w)
    return out


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)  # rough: ~4 characters per token for English


# --- Episodic memory -----------------------------------------------------------
class SessionStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def append(self, session_id: str, role: str, text: str) -> None:
        n = self.conn.execute("SELECT COUNT(*) FROM sessions WHERE session_id=?", (session_id,)).fetchone()[0]
        self.conn.execute("INSERT INTO sessions VALUES (?,?,?,?)", (session_id, n, role, text))
        self.conn.commit()

    def history(self, session_id: str | None, limit: int = 20) -> list[dict]:
        if not session_id:
            return []
        rows = self.conn.execute(
            "SELECT role, text FROM sessions WHERE session_id=? ORDER BY turn DESC LIMIT ?",
            (session_id, limit)).fetchall()
        return [{"role": r["role"], "text": r["text"]} for r in reversed(rows)]


# --- Semantic memory -----------------------------------------------------------
@dataclass
class Chunk:
    source: str
    text: str
    terms: Counter = field(repr=False, default_factory=Counter)


class KnowledgeBase:
    """BM25 over markdown articles, chunked by paragraph."""

    def __init__(self, kb_dir: Path = config.KB_DIR, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.chunks: list[Chunk] = []
        for path in sorted(Path(kb_dir).glob("*.md")):
            title = ""
            for para in re.split(r"\n\s*\n", path.read_text(encoding="utf-8")):
                para = para.strip()
                if para.startswith("#"):          # a heading labels the paragraphs below it
                    title = para.lstrip("# ")
                elif para:
                    self.chunks.append(Chunk(path.stem, para, Counter(tokens(f"{title} {para}"))))
        self.avgdl = sum(sum(c.terms.values()) for c in self.chunks) / max(1, len(self.chunks))
        df = Counter(t for c in self.chunks for t in c.terms)
        n = len(self.chunks)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def search(self, query: str, top_k: int = 3) -> list[Chunk]:
        q = tokens(query)
        scored = []
        for c in self.chunks:
            dl = sum(c.terms.values())
            s = 0.0
            for t in q:
                f = c.terms.get(t, 0)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            if s > 0:
                scored.append((s, c))
        return [c for _, c in sorted(scored, key=lambda x: -x[0])[:top_k]]


# --- Short-term memory: context assembly -----------------------------------------
@dataclass
class AgentContext:
    request: SupportRequest
    intent: ParsedIntent
    history: list[dict]
    docs: list[Chunk]
    summary: str | None = None

    def render(self) -> str:
        parts = []
        if self.summary:
            parts.append(f"Summary of earlier conversation: {self.summary}")
        parts += [f"{t['role']}: {t['text']}" for t in self.history]
        parts += [f"[policy:{d.source}] {d.text}" for d in self.docs]
        return "\n".join(parts)


class MemoryModule:
    def __init__(self, sessions: SessionStore, kb: KnowledgeBase, summarise=None):
        self.sessions, self.kb = sessions, kb
        # summarise(list[dict]) -> str; live mode passes a fast-model call
        self.summarise = summarise or (lambda turns: f"{len(turns)} earlier turns about "
                                       + ", ".join(sorted({t['text'][:30] for t in turns}))[:200])

    def assemble(self, req: SupportRequest, intent: ParsedIntent) -> AgentContext:
        history = self.sessions.history(req.session_id)
        docs = self.kb.search(f"{intent.intent.replace('_', ' ')} {req.raw_text}")
        ctx = AgentContext(req, intent, history, docs)
        budget = config.CONTEXT_BUDGET_TOKENS * config.CONTEXT_SUMMARISE_AT
        if estimate_tokens(ctx.render()) > budget and len(history) > 4:
            ctx.summary = self.summarise(history[:-4])   # compress older turns, keep last 4 verbatim
            ctx.history = history[-4:]
        return ctx
