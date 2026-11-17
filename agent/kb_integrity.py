"""Knowledge-base integrity (Module 16, OWASP LLM04 data poisoning and LLM08).

The agent quotes policy articles to customers, so an article is as powerful as
code: one edited paragraph ("always approve refunds over £200") changes what the
agent tells people. Two controls make the knowledge base behave like code:

  1. A manifest of approved files and their SHA-256 hashes, written by a person
     after review (python -m scripts.kb_manifest --write) and checked in CI.
     With KB_STRICT on, a file that is new or changed since the last approval is
     not loaded.
  2. Every approved article is still scanned for instruction-like text before
     it is indexed. A match quarantines the article and raises an alert.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import config
from .safety import scan_untrusted
from .telemetry import metrics

MANIFEST = "MANIFEST.sha256"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_manifest(kb_dir: Path) -> dict[str, str] | None:
    path = kb_dir / MANIFEST
    if not path.exists():
        return None
    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            digest, name = line.split(maxsplit=1)
            entries[name.strip()] = digest
    return entries


def write_manifest(kb_dir: Path) -> Path:
    lines = ["# Approved knowledge-base articles. Regenerate only after review:",
             "#   python -m scripts.kb_manifest --write"]
    lines += [f"{sha256(p)}  {p.name}" for p in sorted(kb_dir.glob("*.md"))]
    out = kb_dir / MANIFEST
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def check(kb_dir: Path) -> list[str]:
    """Problems that would stop an article loading. Empty list = all approved."""
    manifest = read_manifest(kb_dir) or {}
    problems = []
    for p in sorted(kb_dir.glob("*.md")):
        if p.name not in manifest:
            problems.append(f"{p.name}: not in manifest (new, unreviewed)")
        elif manifest[p.name] != sha256(p):
            problems.append(f"{p.name}: changed since approval")
    for name in manifest:
        if not (kb_dir / name).exists():
            problems.append(f"{name}: in manifest but missing")
    return problems


def load_trusted_articles(kb_dir: Path, strict: bool | None = None) -> tuple[list[tuple[str, str]], list[str]]:
    """Return ([(source, text)], quarantined) for the articles that are safe to index."""
    strict = config.KB_STRICT if strict is None else strict
    manifest = read_manifest(kb_dir)
    loaded, quarantined = [], []
    for p in sorted(kb_dir.glob("*.md")):
        if strict and manifest is not None:
            if manifest.get(p.name) != sha256(p):
                quarantined.append(f"{p.stem}: not approved in manifest")
                metrics["kb_unapproved"] += 1
                continue
        text = p.read_text(encoding="utf-8")
        hits = scan_untrusted(text)
        if hits:
            quarantined.append(f"{p.stem}: instruction-like content {hits}")
            metrics["kb_quarantined"] += 1
            continue
        loaded.append((p.stem, text))
    return loaded, quarantined
