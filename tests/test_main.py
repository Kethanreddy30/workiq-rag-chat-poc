import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class MockServerLogicTests(unittest.TestCase):
    def test_normalize_case_and_whitespace(self):
        self.assertEqual(
            main._normalize("  Hello   WORLD  "),
            "hello world",
        )

    def test_loaded_dataset_has_expected_size(self):
        self.assertEqual(len(main.QA_LOOKUP), 16)

    def test_known_query_lookup(self):
        answer = main.QA_LOOKUP[main._normalize(
            "What is the maximum operating speed of the attraction?"
        )]
        self.assertEqual(answer, "The maximum operating speed is 80 km/h.")

    def test_unknown_query_uses_fallback(self):
        key = main._normalize("Unknown question")
        self.assertEqual(main.QA_LOOKUP.get(key, main.FALLBACK_ANSWER), main.FALLBACK_ANSWER)

    def test_dataset_loader_rejects_missing_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text("id,query\nQ1,Hello\n", encoding="utf-8")
            with patch.object(main, "DATA_PATH", path):
                with self.assertRaises(ValueError):
                    main.load_dataset()


if __name__ == "__main__":
    unittest.main()
