"""Essais du lanceur du skill dans des projets temporaires isolés."""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "skills/dataset-identity/scripts/run_identity.py"


class DatasetIdentitySkillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.git("init", "-b", "skill-test")
        for folder in ("config", "scripts"):
            shutil.copytree(ROOT / folder, self.project / folder, ignore=shutil.ignore_patterns("__pycache__"))
        (self.project / "docs").mkdir()
        shutil.copy2(ROOT / "docs/ingestion-contracts.md", self.project / "docs/ingestion-contracts.md")
        (self.project / "datas").mkdir()
        self.source = self.project / "datas/example.csv"
        self.source.write_text("code;jour;amount\n0007;20/11/2026;12.5\n0008;21/11/2026;bad\n", encoding="utf-8")
        self.contract = self.project / "config/contracts/example.yaml"
        self.contract.write_text(
            'version: 1\ndataset: example\nextra_columns: error\ncolumns:\n'
            '  code: {type: IDENTITY}\n'
            '  jour: {type: DATE, format: "%d/%m/%Y", pattern: "[0-9]{2}/[0-9]{2}/[0-9]{4}"}\n'
            '  amount: {type: FLOAT}\n', encoding="utf-8",
        )

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.project), *args], capture_output=True, text=True, check=True)

    def run_skill(self, source="datas/example.csv", contract="config/contracts/example.yaml", extra=()):
        # Le lancement hors racine vérifie la résolution des chemins du projet.
        return subprocess.run([
            sys.executable, "-B", str(RUNNER), "--project", str(self.project),
            "--source", source, *(["--contract", contract] if contract is not None else []), *extra,
        ], cwd=self.project / "datas", capture_output=True, text=True)

    def snapshot(self):
        return {
            str(path.relative_to(self.project)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.project.rglob("*") if path.is_file()
        }

    def test_french_dates_identifiers_and_invalid_values(self):
        before = self.source.read_bytes()
        result = self.run_skill()
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual((summary["rows"], summary["cols"]), (2, 3))
        self.assertEqual(len(summary["notes"]), 1)
        report = Path(summary["path"]).read_text()
        self.assertIn("20/11/2026", report)
        self.assertIn("| code | IDENTITY |", report)
        self.assertIn("| amount | 12.5 | 12.5 | 12.5 | 12.5 |", report)
        self.assertEqual(self.source.read_bytes(), before)

    def test_existing_dataset_matches_reference(self):
        shutil.copy2(ROOT / "datas/releves_incidents.csv", self.project / "datas/releves_incidents.csv")
        result = self.run_skill("datas/releves_incidents.csv", "config/contracts/incidents.yaml")
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual((summary["rows"], summary["cols"]), (1245, 18))
        report = Path(summary["path"]).read_text()
        reference = (ROOT / "artifacts/ingestion/identities/20261120/releves_incidents_143453.md").read_text()
        self.assertEqual(report.split("## Column list")[1], reference.split("## Column list")[1])

    def test_main_stops_before_any_write(self):
        (self.project / "datas/example.sql").write_text("CREATE TABLE t (id INTEGER);")
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        before = self.snapshot()
        for source, contract in (("datas/example.csv", "config/contracts/example.yaml"), ("datas/example.sql", None)):
            result = self.run_skill(source, contract)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("choix explicite", result.stderr)
            self.assertEqual(self.snapshot(), before)

    def test_detached_head_stops_before_any_write(self):
        (self.project / "datas/example.sql").write_text("CREATE TABLE t (id INTEGER);")
        self.git("-c", "user.name=Skill Test", "-c", "user.email=skill-test@example.invalid", "commit", "--allow-empty", "-m", "fixture")
        self.git("checkout", "--detach")
        before = self.snapshot()
        for source, contract in (("datas/example.csv", "config/contracts/example.yaml"), ("datas/example.sql", None)):
            result = self.run_skill(source, contract)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("HEAD détachée", result.stderr)
            self.assertEqual(self.snapshot(), before)

    def test_invalid_contract_produces_no_report(self):
        self.contract.write_text(self.contract.read_text().replace("type: FLOAT", "type: UNKNOWN"))
        result = self.run_skill()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Type inconnu", result.stderr)
        self.assertFalse((self.project / "artifacts").exists())

    def test_other_formats_refused_without_writes(self):
        (self.project / "datas/example.json").write_text("{}")
        before = self.snapshot()
        result = self.run_skill("datas/example.json", None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Format non pris en charge", result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_sql_reference_report_matches_module(self):
        source = self.project / "datas/machine.sql"
        shutil.copy2(ROOT / "datas/machine.sql", source)
        before = source.read_bytes()
        result = self.run_skill("datas/machine.sql", None)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["format"], "sql")
        self.assertEqual(summary["tables"], {"machine": {"rows": 15, "cols": 11}, "maintenance": {"rows": 115, "cols": 11}})
        self.assertEqual(sum(summary["inventory"].values()), 10)
        report = Path(summary["path"]).read_text()
        reference = (ROOT / "artifacts/ingestion/identities/20261120/machine_155624.md").read_text()
        self.assertEqual(report.split("## Instructions")[1], reference.split("## Instructions")[1])
        self.assertEqual(source.read_bytes(), before)

    def test_sql_contract_refused_and_csv_contract_required(self):
        (self.project / "datas/example.sql").write_text("CREATE TABLE t (id INTEGER);")
        before = self.snapshot()
        result = self.run_skill("datas/example.sql")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CREATE TABLE fait autorité", result.stderr)
        result = self.run_skill(contract=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("obligatoire pour un CSV", result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_sql_parser_error_and_unsupported_statement_no_report(self):
        source = self.project / "datas/example.sql"
        for text in ("CREATE TABLE t (n INTEGER", "CREATE TABLE t (n INTEGER); UPDATE t SET n = 1;"):
            source.write_text(text)
            before = self.snapshot()
            result = self.run_skill("datas/example.sql", None)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Traceback", result.stderr)
            self.assertTrue("impossible" in result.stderr or "hors périmètre" in result.stderr)
            self.assertEqual(self.snapshot(), before)

    def test_sql_uppercase_extension_output_options_and_observations(self):
        (self.project / "datas/example.SQL").write_text("""
            CREATE TABLE t (id INTEGER PRIMARY KEY, at TIMESTAMPTZ DEFAULT NOW(), amount NUMERIC);
            INSERT INTO t (id, amount) VALUES (1, 0.1), (2, 0.2);
        """)
        result = self.run_skill("datas/example.SQL", None, extra=("--output-root", "output", "--stem", "custom", "--types", "config/types.yaml"))
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        path = Path(summary["path"])
        self.assertTrue(path.is_relative_to(self.project / "output"))
        self.assertTrue(path.name.startswith("custom_"))
        self.assertIn("| amount | 0.1 | 0.2 | 0.15 | 0.15 |", path.read_text())
        self.assertTrue(any("omise" in note for note in summary["notes"]))
        self.assertFalse((self.project / "artifacts").exists())


if __name__ == "__main__":
    unittest.main()
