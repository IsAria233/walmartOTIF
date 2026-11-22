# data-gen

Truth-first generator for mock records and the golden dataset.

1. Scenario template
2. True event timeline per PO
3. Derive each system's records from the timeline (code)
4. Inject defects and noise
5. Run the OTIF rules on the defective records -> fine
6. Build the dispute (LLM writes only the supplier's wording)
7. Store the answer: rules on true facts, required evidence, handoff flag

## Generated dataset

`dataset/cases.json` contains PO, ASN, appointment, gate, receiving, weather,
fine and dispute records in the seed loader's format. `dataset/expected.json`
holds the matching labels by `case_id` and external `fine_id`. Give the Agent
only the records from `cases.json`. The existing Domain loader accepts that
file directly.

The checked-in dataset contains 24 cases under OTIF policy v0.2. It covers
C1–C5, injected instructions that are reported while the investigation
continues, and handoffs for missing receipts or a supported weather claim.
It also includes R1/R2 pre-invoice flags and reversals on both sides of the
manager-approval threshold.

From the repository root:

```sh
python3 data-gen/generate_dataset.py
python3 data-gen/check_dataset.py
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

To load the generated inputs into a local Domain database, use the same
loader as for the handwritten seed cases. From the repository root with
Compose running:

```sh
docker compose run --rm -T -v "$PWD/data-gen:/data:ro" domain-service \
  python -m scripts.load_seed_cases /data/dataset/cases.json
```
