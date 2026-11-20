import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import yaml

from scripts.contracts import load_configuration
from scripts.ingestion import (
    ROOT, compute_statistics, generate_identity, infer_columns,
)
from scripts.sql_ingestion import generate_sql_identity


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.types_path = self.root / "types.yaml"
        self.types_path.write_text((ROOT / "config/types.yaml").read_text())

    def load(self, columns, **options):
        contract = {"version": 1, "dataset": "example", "columns": columns, **options}
        path = self.root / "contract.yaml"
        path.write_text(yaml.safe_dump(contract))
        return load_configuration(path, self.types_path)

    def test_new_dataset_formats_constraints_and_identifiers(self):
        contract, types = self.load({
            "code": {"type": "IDENTITY", "nullable": False},
            "day": {"type": "DATE", "format": "%d/%m/%Y"},
            "amount": {"type": "FLOAT", "min": 0, "max": 100},
            "count": {"type": "INTEGER"},
        })
        frame = pd.DataFrame({
            "code": ["0007", None, "0009"],
            "day": ["20/11/2026", "bad", "21/11/2026"],
            "amount": ["12.5", "-1", "inf"],
            "count": ["2", "3.5", "bad"],
        }, dtype="string")
        columns, issues = infer_columns(frame, contract, types)
        self.assertEqual(columns["code"]["values"].iloc[0], "0007")
        self.assertEqual(columns["day"]["values"].notna().sum(), 2)
        self.assertEqual(columns["amount"]["values"].notna().sum(), 1)
        self.assertEqual(columns["count"]["values"].notna().sum(), 1)
        self.assertEqual(len(issues), 4)
        self.assertNotIn("code", [r["name"] for r in compute_statistics(columns)])

    def test_rules_and_column_precedence(self):
        contract, types = self.load(
            {"type_name": {"type": "TEXT"}},
            column_rules=[{"pattern": "^type_", "type": "INTEGER", "allowed": [0, 1]}],
        )
        columns, issues = infer_columns(pd.DataFrame({"type_name": ["label"], "type_fault": ["2"]}, dtype="string"), contract, types)
        self.assertEqual(columns["type_name"]["type"], "TEXT")
        self.assertTrue(columns["type_fault"]["values"].isna().all())
        self.assertEqual(len(issues), 1)

    def test_missing_extra_and_optional_columns(self):
        contract, types = self.load({"needed": {"type": "TEXT"}})
        with self.assertRaisesRegex(ValueError, "absentes"):
            infer_columns(pd.DataFrame(), contract, types)
        contract, types = self.load({"optional": {"type": "TEXT", "required": False}}, extra_columns="error")
        with self.assertRaisesRegex(ValueError, "supplémentaire"):
            infer_columns(pd.DataFrame({"other": ["x"]}, dtype="string"), contract, types)
        self.assertEqual(infer_columns(pd.DataFrame(), contract, types), ({}, []))

    def test_extra_columns_inference_and_empty_statistics(self):
        contract, types = self.load({"missing": {"type": "FLOAT"}})
        columns, _ = infer_columns(pd.DataFrame({"missing": [None], "other_id": ["001"], "value": ["2.5"]}, dtype="string"), contract, types)
        self.assertEqual(columns["other_id"]["type"], "IDENTITY")
        self.assertEqual(columns["value"]["type"], "FLOAT")
        self.assertIsNone(compute_statistics(columns)[0]["mean"])

    def test_unknown_type_converter_and_invalid_options(self):
        with self.assertRaisesRegex(ValueError, "Type inconnu"):
            self.load({"x": {"type": "TYPO"}})
        for bad in ({"nullable": "false"}, {"min": 3, "max": 1}, {"typo": True}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.load({"x": {"type": "INTEGER", **bad}})
        catalog = yaml.safe_load(self.types_path.read_text())
        catalog["types"]["FLOAT"]["converter"] = "os.system"
        self.types_path.write_text(yaml.safe_dump(catalog))
        with self.assertRaisesRegex(ValueError, "Convertisseur inconnu"):
            self.load({})

    def test_duplicate_keys_and_unsafe_tags_rejected(self):
        self.types_path.write_text("version: 1\nversion: 1\ntypes: {}\n")
        with self.assertRaisesRegex(ValueError, "dupliquée"):
            self.load({})
        self.types_path.write_text("!!python/object:builtins.object {}")
        with self.assertRaises(yaml.YAMLError):
            self.load({})

    def test_custom_type_and_statistics_selection(self):
        catalog = yaml.safe_load(self.types_path.read_text())
        catalog["types"]["PRICE"] = {"converter": "number", "statistics": ["min", "max"]}
        self.types_path.write_text(yaml.safe_dump(catalog))
        contract, types = self.load({"price": {"type": "PRICE"}})
        columns, _ = infer_columns(pd.DataFrame({"price": ["12.5", "20"]}, dtype="string"), contract, types)
        row = compute_statistics(columns)[0]
        self.assertEqual(row["max"], 20)
        self.assertIsNone(row["mean"])

    def test_report_for_new_dataset_and_collision(self):
        self.load({"code": {"type": "IDENTITY"}, "day": {"type": "DATE", "format": "%d/%m/%Y"}})
        source = self.root / "example.csv"
        source.write_text("code;day\n0007;20/11/2026\n0008;21/11/2026\n")
        result = generate_identity(source, "example", contract_path=self.root / "contract.yaml", types_path=self.types_path, root=self.root)
        self.assertEqual((result["rows"], result["cols"]), (2, 2))
        report = result["path"].read_text()
        self.assertIn("20/11/2026", report)
        self.assertIn("| code | IDENTITY |", report)
        # Rejouer avec la même heure doit préserver le rapport existant.
        with patch("scripts.ingestion.datetime") as clock:
            clock.now.return_value = result["begin"]
            with self.assertRaises(FileExistsError):
                generate_identity(source, "example", contract_path=self.root / "contract.yaml", types_path=self.types_path, root=self.root)
        self.assertEqual(result["path"].read_text(), report)

    def test_existing_csv_reports_unchanged(self):
        for stem, contract, rows, cols in (("releves_incidents", "incidents", 1245, 18), ("telemetry", "telemetry", 135626, 7)):
            with self.subTest(dataset=stem):
                result = generate_identity(ROOT / "datas" / f"{stem}.csv", stem, contract_path=ROOT / "config/contracts" / f"{contract}.yaml", root=self.root)
                self.assertEqual((result["rows"], result["cols"]), (rows, cols))
                reference = (ROOT / "artifacts/ingestion/identities/20261120" / f"{stem}_143453.md").read_text()
                self.assertEqual(result["path"].read_text().split("## Column list")[1], reference.split("## Column list")[1])

    def test_notebook_from_root_and_notebooks(self):
        notebook = json.loads((ROOT / "notebooks/sprint1.ipynb").read_text())
        original_cwd = Path.cwd()
        self.addCleanup(os.chdir, original_cwd)
        for folder in (ROOT, ROOT / "notebooks"):
            def isolated_sql(*args, **kwargs):
                kwargs["root"] = Path(output)
                return generate_sql_identity(*args, **kwargs)
            with self.subTest(folder=folder), tempfile.TemporaryDirectory() as output, patch("scripts.sql_ingestion.generate_sql_identity", side_effect=isolated_sql):
                os.chdir(folder)
                namespace = {}
                for cell in notebook["cells"]:
                    if cell["cell_type"] != "code":
                        continue
                    exec(compile("".join(cell["source"]), "sprint1.ipynb", "exec"), namespace)
                    if "reports" not in namespace:
                        def isolated(*args, **kwargs):
                            return generate_identity(*args, **kwargs, root=Path(output))
                        namespace["generate_identity"] = isolated
                self.assertEqual([r["rows"] for r in namespace["reports"]], [1245, 135626])
                self.assertEqual(len(namespace["sql_report"]["tables"]["maintenance"]["rows"]), 115)


if __name__ == "__main__":
    unittest.main()
