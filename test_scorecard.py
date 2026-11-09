import tempfile
import unittest
from pathlib import Path

from scorecard import evaluate, load_evidence, load_plan

ROOT = Path(__file__).resolve().parent


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.plan = load_plan(ROOT / "pilot-plan.json")

    def score(self, name):
        evidence = load_evidence(ROOT / f"evidence-{name}.csv", self.plan)
        return evaluate(self.plan, evidence)

    def test_three_decisions(self):
        for name, expected in [("initial", "NO-GO"), ("partial", "HOLD"), ("retest", "GO")]:
            with self.subTest(name=name):
                self.assertEqual(self.score(name)[0], expected)
        self.assertEqual(self.score("retest")[1][2][1], "882 ms")
        self.assertEqual(self.score("initial")[3], ["NL-4106"])
        self.assertEqual(len(self.score("partial")[2]), 3)

    def test_partial_capture_with_observed_duplicate(self):
        evidence = load_evidence(ROOT / "evidence-initial.csv", self.plan)
        del evidence["NL-4101"]
        self.assertEqual(evaluate(self.plan, evidence)[0], "NO-GO")

    def test_threshold_is_inclusive(self):
        self.plan["max_p95_ms"] = 882
        self.assertEqual(self.score("retest")[0], "GO")

    def test_invalid_or_repeated_rows(self):
        header = "order_id,result,latency_ms,fulfillment_writes\n"
        good = "NL-4101,completed,530,1\n"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "evidence.csv"
            for data in (good * 2, "unknown,completed,530,1", "NL-4101,completed,500,0",
                         "NL-4101,failed,99,0", "NL-4101,completed,,1"):
                path.write_text(header + data, encoding="utf-8")
                with self.subTest(data=data), self.assertRaises(ValueError):
                    load_evidence(path, self.plan)


if __name__ == "__main__":
    unittest.main()
