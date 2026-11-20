import hashlib
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from sqlglot.errors import ParseError

from indusense.contracts import load_type_catalog
from indusense.ingestion import DEFAULT_TYPES, ROOT
from indusense.sql_ingestion import analyze_table, generate_sql_identity, parse_sql_source


class SQLIngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "example.sql"
        self.types = load_type_catalog(DEFAULT_TYPES)

    def analyze(self, text):
        tables, _ = parse_sql_source(text)
        return {name: analyze_table(table, self.types) for name, table in tables.items()}

    def generate(self, text):
        self.source.write_text(text, encoding="utf-8")
        return generate_sql_identity(self.source, root=self.root)

    def test_provided_script_and_independent_expected_statistics(self):
        source = ROOT / "datas/machine.sql"
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        self.assertEqual(before, "9eb877ae806515e852df46dd9f97f31aabfa8420a8f07dc50a5be4cefced8fcb")
        result = generate_sql_identity(source, root=self.root)
        self.assertEqual(sum(result["inventory"].values()), 10)
        machine = result["tables"]["machine"]
        maintenance = result["tables"]["maintenance"]
        self.assertEqual((len(machine["rows"]), len(machine["schema"])), (15, 11))
        self.assertEqual((len(maintenance["rows"]), len(maintenance["schema"])), (115, 11))
        self.assertEqual([len(names) for names in machine["insert_columns"]], [8])
        self.assertEqual([len(names) for names in maintenance["insert_columns"]], [9])
        stats = {row["name"]: row for row in machine["statistics"]}
        self.assertEqual(str(stats["commissioning_date"]["min"].date()), "2019-07-23")
        self.assertEqual(str(stats["commissioning_date"]["max"].date()), "2025-05-25")
        capacity = stats["max_daily_capacity"]
        self.assertEqual((capacity["min"], capacity["max"], capacity["median"]), (750, 1428, 1027))
        self.assertAlmostEqual(capacity["mean"], 15823 / 15)
        stats = {row["name"]: row for row in maintenance["statistics"]}
        duration = stats["duration_hours"]
        self.assertEqual((duration["min"], duration["max"], duration["median"]), (Decimal("1.0"), Decimal("8.0"), Decimal("2.64")))
        self.assertEqual(duration["mean"], Decimal("338.45") / 115)
        self.assertEqual(stats["maintenance_at"]["max"], pd.Timestamp("2026-05-30 22:00:00Z"))
        self.assertNotIn("maintenance_id", stats)
        self.assertEqual(machine["counts"]["created_at"]["omitted"], 15)
        self.assertEqual(maintenance["counts"]["related_incident_id"]["null"], 90)
        report = result["path"].read_text()
        self.assertIn("ON CONFLICT", report)
        self.assertIn("CURRENT_TIMESTAMP", report)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

    def test_reordered_columns_escaped_text_null_omission_and_duplicates(self):
        table = self.analyze("""
            CREATE TABLE example (code VARCHAR(8) PRIMARY KEY, description TEXT, amount NUMERIC(6,2), created_at TIMESTAMPTZ DEFAULT NOW());
            INSERT INTO example (description, amount, code) VALUES ('l''été, bleu; vert', 0.10, '0007'), (NULL, 0.20, '0008');
            INSERT INTO example (code, amount) VALUES ('0007', 0.10);
        """)["example"]
        self.assertEqual(len(table["rows"]), 3)
        self.assertEqual(table["rows"][0]["description"], "l'été, bleu; vert")
        self.assertEqual(table["columns"]["code"]["values"].tolist(), ["0007", "0008", "0007"])
        self.assertEqual(table["counts"]["description"], {"valid": 1, "null": 1, "omitted": 1, "unevaluated": 0})
        self.assertEqual(table["counts"]["created_at"]["omitted"], 3)

    def test_exact_decimal_statistics(self):
        table = self.analyze("CREATE TABLE t (v NUMERIC(50,2)); INSERT INTO t VALUES (123456789012345678901234567890.10), (123456789012345678901234567890.20);")["t"]
        row = table["statistics"][0]
        self.assertEqual(row["mean"], Decimal("123456789012345678901234567890.15"))
        self.assertEqual(row["median"], Decimal("123456789012345678901234567890.15"))

    def test_timezone_conversion_boolean_and_naive_rejection(self):
        table = self.analyze("""CREATE TABLE t (at TIMESTAMPTZ, active BOOLEAN);
            INSERT INTO t VALUES ('2026-01-01 12:00:00+02', TRUE),
            ('2026-01-01 09:00:00Z', FALSE), ('2026-01-01 12:00:00', NULL);
        """)["t"]
        self.assertEqual(table["columns"]["at"]["values"].notna().sum(), 2)
        row = table["statistics"][0]
        self.assertEqual(row["max"], pd.Timestamp("2026-01-01 10:00:00Z"))
        self.assertEqual(table["counts"]["active"]["valid"], 2)
        self.assertEqual(len(table["statistics"]), 1)
        self.assertTrue(any("incompatible" in note for note in table["notes"]))

    def test_unevaluated_expressions_and_invalid_values(self):
        result = self.generate("""CREATE TABLE t (id INTEGER PRIMARY KEY, at TIMESTAMPTZ DEFAULT NOW(), n NUMERIC);
            INSERT INTO t VALUES (1, NOW(), 1 + 2), (NULL, NULL, 'bad');
        """)
        table = result["tables"]["t"]
        self.assertEqual(table["counts"]["at"]["unevaluated"], 1)
        self.assertEqual(table["counts"]["at"]["null"], 1)
        self.assertEqual(table["counts"]["n"]["valid"], 0)
        self.assertTrue(all(row["min"] is None for row in table["statistics"]))
        report = result["path"].read_text()
        self.assertIn("non évaluées", report)
        self.assertIn("NULL explicite incompatible", report)

    def test_table_constraints_and_case_normalization(self):
        table = self.analyze("""CREATE TABLE T (ID INTEGER, parent INTEGER, n INTEGER, PRIMARY KEY (ID), FOREIGN KEY (parent) REFERENCES other (id));
            INSERT INTO t (id, parent, n) VALUES (1, 2, 3);
        """)["t"]
        self.assertEqual(table["schema"]["id"]["type"], "IDENTITY")
        self.assertEqual(table["schema"]["parent"]["type"], "IDENTITY")
        self.assertEqual([s["name"] for s in table["statistics"]], ["n"])

    def test_schema_only_empty_statistics(self):
        result = self.generate("CREATE TABLE t (n NUMERIC, created_at TIMESTAMPTZ DEFAULT NOW());")
        self.assertEqual(len(result["tables"]["t"]["rows"]), 0)
        self.assertIn("| n | N/A | N/A | N/A | N/A |", result["path"].read_text())

    def test_unsupported_and_malformed_scripts_produce_no_report(self):
        cases = [
            "CREATE TABLE t (n INTEGER",  # syntax error
            "CREATE TABLE t (n INTEGER); UPDATE t SET n = 1;",
            "CREATE TABLE t (n INTEGER); INSERT INTO t SELECT 1;",
            "CREATE TABLE t (n INTEGER); INSERT INTO t VALUES (1,2);",
            "CREATE TABLE t (n INTEGER); INSERT INTO t (unknown) VALUES (1);",
            "CREATE TABLE t (n INTEGER); INSERT INTO t (n,n) VALUES (1,2);",
            "INSERT INTO t VALUES (1);",
            "CREATE TABLE t (n JSONB);",
        ]
        for text in cases:
            with self.subTest(text=text), self.assertRaises((ValueError, ParseError)):
                self.generate(text)
            self.assertFalse((self.root / "artifacts").exists())

    def test_collision_does_not_overwrite_report(self):
        result = self.generate("CREATE TABLE t (n INTEGER); INSERT INTO t VALUES (-2), (4);")
        before = result["path"].read_bytes()
        with patch("indusense.sql_ingestion.datetime") as clock:
            clock.now.return_value = result["begin"]
            with self.assertRaises(FileExistsError):
                generate_sql_identity(self.source, root=self.root)
        self.assertEqual(result["path"].read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
