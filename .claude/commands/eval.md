---
description: Run tests and the golden-set evals, then explain any failure
---
Run `python -m pytest -q` and then `python -m evals.run_evals`.
For every failing case, open the trace for its request id in eval_traces.jsonl, name the
layer where it went wrong (L1-L13), and propose the smallest fix. Do not change thresholds
in config.py to make a case pass. $ARGUMENTS
