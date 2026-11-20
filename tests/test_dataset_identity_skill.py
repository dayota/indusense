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
        for folder in ("config", "indusense"):
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

    def run_skill(self, source="datas/example.csv", contract="config/contracts/example.yaml"):
        # Le lancement hors racine vérifie la résolution des chemins du projet.
        return subprocess.run([
            sys.executable, "-B", str(RUNNER), "--project", str(self.project),
            "--source", source, "--contract", contract,
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
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        before = self.snapshot()
        result = self.run_skill()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("choix explicite", result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_detached_head_stops_before_any_write(self):
        self.git("-c", "user.name=Skill Test", "-c", "user.email=skill-test@example.invalid", "commit", "--allow-empty", "-m", "fixture")
        self.git("checkout", "--detach")
        before = self.snapshot()
        result = self.run_skill()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HEAD détachée", result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_contract_produces_no_report(self):
        self.contract.write_text(self.contract.read_text().replace("type: FLOAT", "type: UNKNOWN"))
        result = self.run_skill()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Type inconnu", result.stderr)
        self.assertFalse((self.project / "artifacts").exists())

    def test_sql_refused_without_writes(self):
        (self.project / "datas/example.sql").write_text("CREATE TABLE example (id INTEGER);")
        before = self.snapshot()
        result = self.run_skill("datas/example.sql")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SQL est hors périmètre", result.stderr)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
