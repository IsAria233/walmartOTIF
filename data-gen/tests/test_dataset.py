import unittest
from copy import deepcopy
from datetime import datetime, timedelta

from check_dataset import check_case, rederive
from generate_dataset import generate_dataset


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inputs, answers = generate_dataset(42, 3)
        cls.inputs = inputs
        cls.answers = answers
        cls.pairs = list(zip(inputs["cases"], answers["cases"], strict=True))

    def for_scenario(self, name):
        return [(row, label) for row, label in self.pairs if label["scenario"] == name]

    def test_generated_records_match_independently_derived_labels(self):
        for row, label in self.pairs:
            with self.subTest(case_id=row["case_id"]):
                self.assertEqual(check_case(row, label), [])
                self.assertTrue(row["case_id"].startswith("SYN2-"))

    def test_seed_is_repeatable_and_additional_rounds_preserve_rows(self):
        self.assertEqual(generate_dataset(42, 3), (self.inputs, self.answers))
        extended_inputs, extended_answers = generate_dataset(42, 4)
        self.assertEqual(extended_inputs["cases"][:24], self.inputs["cases"])
        self.assertEqual(extended_answers["cases"][:24], self.answers["cases"])

    def test_weather_claims_need_evidence_and_an_on_schedule_shipment(self):
        late_with_weather = [
            row for row, _ in self.for_scenario("late_shipment") if row["weather"]
        ]
        self.assertEqual(len(late_with_weather), 2)
        self.assertEqual({rederive(row)["cause"] for row in late_with_weather}, {"C1"})
        for row, _ in self.for_scenario("weather_review"):
            self.assertEqual(rederive(row)["handoff_reason"], "weather_claim_requires_review")
            changed = deepcopy(row)
            changed["weather"][0]["area"] = "Away from the DC"
            self.assertEqual(rederive(changed)["handoff_reason"], "unresolved_arrival")

    def test_post_dispatch_revisions_are_visible_but_not_effective(self):
        row, label = next(
            (row, label) for row, label in self.for_scenario("superseded_po")
            if len(row["po"]["versions"]) == 3
        )
        later = row["po"]["versions"][-1]
        self.assertGreater(datetime.fromisoformat(later["issued_at"]), datetime.fromisoformat(row["asn"]["ship_ts"]))
        self.assertNotIn(later["version_id"], label["expected"]["key_evidence"])
        self.assertEqual(rederive(row)["cause"], "C5")
        changed = deepcopy(row)
        # A second revision at exactly dispatch is also ineligible.
        changed["po"]["versions"][-1]["issued_at"] = row["asn"]["ship_ts"]
        self.assertEqual(rederive(changed)["cause"], "C5")
        just_before = datetime.fromisoformat(row["asn"]["ship_ts"]) - timedelta(minutes=1)
        changed["po"]["versions"][-1]["issued_at"] = just_before.isoformat()
        self.assertEqual(rederive(changed)["cause"], "C3")

    def test_r2_can_represent_a_true_shortage_or_a_late_posting(self):
        r2_causes = {
            rederive(row)["cause"] for row, _ in self.pairs if row.get("scan_rule") == "R2"
        }
        self.assertEqual(r2_causes, {"C3", "C4"})
        for row, _ in self.for_scenario("late_receipt"):
            self.assertGreater(sum(receipt["cases"] for receipt in row["receiving"]), row["fine_record"]["received_cases"])

    def test_injection_channels_have_the_same_c3_financial_outcome(self):
        seen = set()
        for row, label in self.for_scenario("reported_injection"):
            observed = rederive(row)
            seen.add(tuple(observed["injection_sources"]))
            self.assertEqual(observed["injection_sources"], label["expected"]["injection_sources"])
            self.assertEqual((observed["cause"], observed["outcome"], observed["handoff"]), ("C3", "uphold", False))
        self.assertEqual(seen, {("dispute",), ("attachment",), ("dispute", "attachment")})

    def test_golden_approvals_straddle_the_manager_threshold(self):
        for scenario in ("dc_reschedule", "late_receipt", "superseded_po"):
            expected = {row["fine_record"]["amount"]: label["expected"]["manager_approval_required"]
                        for row, label in self.for_scenario(scenario)}
            self.assertIs(expected[499.80], False)
            self.assertIs(expected[500.40], True)

    def test_checker_detects_a_fine_receipt_count_from_the_wrong_day(self):
        row, label = self.for_scenario("late_receipt")[0]
        changed = deepcopy(row)
        changed["receiving"][-1]["ts"] = changed["receiving"][0]["ts"]
        self.assertIn("fine receipt count differs from postings through arrival day", check_case(changed, label))


if __name__ == "__main__":
    unittest.main()
