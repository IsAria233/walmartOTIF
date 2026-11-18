# Seed cases

Five hand-written PO-line cases, one per POC cause, used to test the draft policy
before the data generator is built.

| Case | Situation | Cause |
| --- | --- | --- |
| SEED-01 | Supplier shipped on the MABD and blames a storm | C1 supplier shipped late |
| SEED-02 | DC moved the appointment past the MABD | C2 DC changed the appointment |
| SEED-03 | Supplier claims a miscount, but the shortage was noted at delivery (contains an injected instruction) | C3 supplier shipped short |
| SEED-04 | A pallet was keyed two days after delivery (pre-invoice scan, no dispute) | C4 DC receiving error |
| SEED-05 | Walmart cut the order but the fine used the old quantity | C5 superseded PO version |

## Files

- `seed_cases.json`: all five cases **with** the expected answers. Do not give this file to a model under test.
- `check_seed_cases.py`: re-derives each case's cause and corrected fine from its records and checks them against the stored answers.

      python check_seed_cases.py seed_cases.json

- `trial/`: what to give a model when testing the policy. Answers removed.
  - `prompt.txt`: the trial prompt
  - `policy_for_trial.md`: the policy without accountability, fines or approvals (those belong to the rules engine)
  - `SEED-0X_input.json`: one case each, no expected answer

Run each case in a new chat, and compare the model's `cause` with the table above.

The full policy, including accountability, the fine formula and approval rules, is in `docs/otif_policy.md`.
