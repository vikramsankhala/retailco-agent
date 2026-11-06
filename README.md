# RetailCo Support Agent — reference build

Companion code for the Solinexta AI programme *Build a Production AI Agent with Claude Code*.
Every lab in the programme ends at a state of this repository.

    pip install -e ".[dev]"
    python -m scripts.seed
    python -m pytest -q              # 27 tests, no API key needed
    python -m evals.run_evals        # 12 golden cases, offline
    python -m scripts.chat CUST-4821 # talk to it in the terminal

Set `ANTHROPIC_API_KEY` to switch Layers 3, 5 and 7 from the offline fallbacks to Claude
(Haiku for understanding, Sonnet for reasoning and replies, Opus for the eval judge).
