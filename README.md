# RetailCo Support Agent — reference build

Companion code for the Solinexta AI programme *Build a Production AI Agent with Claude Code*.
Every lab in the programme ends at a state of this repository.

    pip install -e ".[dev]"
    python -m scripts.seed
    python -m pytest -q              # 30 tests, no API key needed
    python -m evals.run_evals        # 12 golden cases, offline
    python -m scripts.chat CUST-4821 # talk to it in the terminal

Set `ANTHROPIC_API_KEY` to switch Layers 3, 5 and 7 from the offline fallbacks to Claude
(Haiku for understanding, Sonnet for reasoning and replies, Opus for the eval judge).

## The case

The programme starts with a Harvard-style case and its analysis:

- `docs/case/RetailCo-Case-Study.pdf` — *RetailCo: Automating the Front Line* (participant brief, 18 exhibits)
- `docs/case/RetailCo-Case-Analysis.pdf` — strategy evaluation (release after the strategy session)
- `strategy/model.py` — Lab 0: reproduces every number in the analysis. Run `python -m strategy.model`.
