# eval

Runs the agent on a generated dataset and compares the result with the
dataset's expected answers.

    # 1. load the cases (once)
    docker compose run --rm -T -v "$PWD/data-gen:/data:ro" domain-service \
      python -m scripts.load_seed_cases /data/dataset/cases.json
    # 2. investigate every pending case and score it
    EVAL_PASSWORD=<demo password> uv run --with httpx python eval/run_eval.py \
      --dataset data-gen/dataset --out eval/reports/regression

Investigating calls the model, so step 2 costs a few model calls per pending
case. A case that already has a result is scored from that result: repeating
the command costs nothing, and `--score-only` never starts an investigation.

Use `data-gen/dataset` while working, `data-gen/evaluation/standard` for a
reported number, and `data-gen/evaluation/holdout` once at the end.

## What is scored

| Measure | Meaning |
| --- | --- |
| Cause correct | The stored cause (or a handoff) equals the expected one. |
| Corrected fine correct | The rules engine's amount equals the expected amount. Wrong when the cause is wrong or the case was handed off by mistake. |
| Handoff precision / recall | Of the cases handed off, how many should have been; of those that should, how many were. |
| Injected instructions | Reported when present and not reported when absent. |
| Key evidence | Share of the dataset's key records that the finding cites, counted only when the cause is right. |

Results are reported for each expected cause as well as overall, because the
share of each cause in a generated dataset is a choice, not a fact about real
disputes.

Not scored yet: time and cost per line beyond wall-clock seconds, and
pre-invoice flag precision.

`eval/scoring.py` holds the comparison and is tested without any service:

    uv run --with pytest python -m pytest eval/tests
