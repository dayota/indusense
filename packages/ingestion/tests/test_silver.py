import unittest
from pathlib import Path

from indusense_ingestion.contracts import load_type_catalog
from indusense_ingestion.silver import parse_contract, source_hash, transform

TYPES = load_type_catalog(Path(__file__).resolve().parents[3] / "config/types.yaml")


class SilverTests(unittest.TestCase):
    def test_hash_is_stable_and_distinguishes_source_values_and_omissions(self):
        self.assertEqual(source_hash({"b": "2", "a": "1"}), source_hash({"a": "1", "b": "2"}))
        values = [{"a": "01"}, {"a": "1"}, {"a": 1}, {"a": None}, {}]
        self.assertEqual(len({source_hash(value) for value in values}), len(values))

    def test_contractual_types_and_exact_integer_conversion(self):
        specs = {"id": {"type": "IDENTITY"}, "value": {"type": "INTEGER"}}
        records = [{"id": "001", "value": "9007199254740993"}, {"id": "002", "value": "abc"}]
        output, errors = transform(records, specs, TYPES)
        self.assertEqual(output[0]["value"], 9007199254740993)
        self.assertEqual(output[0]["id"], "001")
        self.assertEqual(output[1]["value__type"], "INTEGER")
        self.assertEqual(list(output[0]), ["id", "id__type", "value", "value__type", "hash"])
        self.assertEqual(errors[0], [])
        self.assertEqual(errors[1][0]["column"], "value")

    def test_missing_nonnullable_invalid_constraints_and_expressions_are_errors(self):
        specs = {"value": {"type": "INTEGER", "nullable": False, "min": 0, "max": 4}}
        _, errors = transform([{"value": value} for value in (None, " ", "1.5", "-1", "5", {"sql_expression": "NOW()"}, "2")], specs, TYPES)
        self.assertTrue(all(errors[index] for index in range(6)))
        self.assertEqual(errors[-1], [])

    def test_contract_cannot_infer_type_or_collide_with_generated_names(self):
        for text, columns in (
            ("version: 1\ndataset: test\ncolumns: {}", ["a"]),
            ("version: 1\ndataset: test\ncolumns: {hash: {type: TEXT}}", ["hash"]),
            ("version: 1\ndataset: test\ncolumns: {a: {type: TEXT}, a__type: {type: TEXT}}", ["a", "a__type"]),
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_contract(text, TYPES, columns)
