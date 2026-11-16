# data-gen

Truth-first generator for mock records and the golden dataset.

1. Scenario template
2. True event timeline per PO
3. Derive each system's records from the timeline (code)
4. Inject defects and noise
5. Run the OTIF rules on the defective records -> fine
6. Build the dispute (LLM writes only the supplier's wording)
7. Store the answer: rules on true facts, required evidence, handoff flag
