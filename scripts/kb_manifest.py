"""Approve the knowledge base, or check it has not changed since approval.

    python -m scripts.kb_manifest --check     # CI: exit 1 if any article is unapproved
    python -m scripts.kb_manifest --write     # after a person has reviewed the diff
"""
from __future__ import annotations

import sys

from agent import config
from agent.kb_integrity import check, write_manifest


def main(argv: list[str]) -> int:
    if "--write" in argv:
        print(f"wrote {write_manifest(config.KB_DIR)}")
        return 0
    problems = check(config.KB_DIR)
    for p in problems:
        print(f"UNAPPROVED  {p}")
    print("knowledge base approved" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
