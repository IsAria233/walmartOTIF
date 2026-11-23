# data-gen

Truth-first generator for mock records and the golden dataset.

1. The scenario defines what happened on one PO line. A seeded random number
   generator chooses the order size, transit time, shipment and arrival times.
2. Generate mock PO versions, ASN, appointments, gate checks and receipt
   postings from that timeline. Some cases include extra records that the
   investigator must interpret using the policy.
3. Generate the original fine from the system snapshot. For in-full cases it
   uses the system's PO version and the receipts posted through arrival day.
4. Choose a supplier claim from shared templates. The same wording can apply
   to several causes.
5. Generate the golden answer from the scenario and its true quantities.
   The checker independently derives the answer from the visible records.

## Generated dataset

`dataset/cases.json` contains PO, ASN, appointment, gate, receiving, weather,
fine and dispute records in the seed loader's format. `dataset/expected.json`
holds the matching labels by `case_id` and external `fine_id`. Give the Agent
only the records from `cases.json`. The existing Domain loader accepts that
file directly.

The checked-in dataset contains 24 cases under OTIF policy v0.3. It covers
C1–C5, injected instructions that are reported while the investigation
continues, and handoffs for missing receipts or a supported weather claim.
It also includes R1/R2 pre-invoice flags and reversals on both sides of the
manager-approval threshold.

The second dataset revision uses `SYN2-` IDs so existing imports from the
first revision can coexist with the richer fixtures.

| What to check | Dataset variation |
| --- | --- |
| A reported storm | Qualifying weather for an on-schedule shipment and weather that fails the policy test |
| An appointment change | Later DC slots and changes that keep the original MABD date |
| An R2 flag | An overstated ASN with an observed shortage and a complete shipment with late receipt postings |
| A revised PO | A valid update before shipment and another revision after dispatch |
| Injected instructions | Supplier message only, attachment only, and both, in five different wordings (two more appear only in the holdout), with the investigation continuing |
| Supplier documents | A POD the DC receiver signed with a shortage noted, one signed with no exception, one only the driver signed, and BOLs counted by the shipper or by the carrier |
| Manager approval | Reversals of $499.80 and $500.40 for each of C2, C4 and C5 |

Generate, validate and test from the repository root.

```sh
python3 data-gen/generate_dataset.py
python3 data-gen/check_dataset.py
PYTHONPATH=data-gen python3 -m unittest discover -s data-gen/tests -v
```

The generator uses a fixed seed and three cases per scenario by default.
Increasing the case count with the same seed preserves existing case IDs and
records. For a separate synthetic batch, use a distinct seed and output directory:

```sh
python3 data-gen/generate_dataset.py --seed 43 --per-scenario 10 --output-dir /tmp/otif-dataset
python3 data-gen/check_dataset.py /tmp/otif-dataset
```

The checker re-derives the expected answers from the records and checks that
the fine snapshot, scan rule, and cited record IDs agree. The generator uses
fixed supplier claim templates and works with Python's standard library.

## Evaluation suite

The 100 evaluation cases use a separate `EVAL2-` ID prefix and seed `73`.
There are 10 scenario families. Each has eight cases under
`evaluation/standard/` and two under `evaluation/holdout/`. The holdout
uses different claim wording and includes PO revisions entered at the exact
ASN dispatch timestamp. Evaluation-only scenarios cover a supplier moving
its own appointment past MABD and an on-schedule shipment whose late arrival
has no supported cause.

Each split has a loader-ready `cases.json` and matching `expected.json`.
Use the standard split for regular evaluation and save the holdout for the
final run. Keep `expected.json` with the evaluator.

```sh
python3 data-gen/generate_dataset.py --suite evaluation
python3 data-gen/check_dataset.py data-gen/evaluation/standard
python3 data-gen/check_dataset.py data-gen/evaluation/holdout
```

To load the generated inputs into a local Domain database, use the same
loader as for the handwritten seed cases. From the repository root with
Compose running, pass the `cases.json` for the set you want to load.

```sh
docker compose run --rm -T -v "$PWD/data-gen:/data:ro" domain-service \
  python -m scripts.load_seed_cases /data/dataset/cases.json
```
