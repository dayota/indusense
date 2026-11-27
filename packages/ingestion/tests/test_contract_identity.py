import hashlib
import tempfile
import unittest
from pathlib import Path

from indusense_ingestion.contract_identity import generate_contract_identity
from indusense_ingestion.bronze_sources import FilesystemSourceInspector

ROOT = Path(__file__).resolve().parents[3]


class ContractIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / 'datas/ingestion/example/1/inputs'
        self.inputs.mkdir(parents=True)
        self.inspector = FilesystemSourceInspector(self.root)

    def test_csv_uses_declared_encoding_delimiter_types_and_exact_decimal_statistics(self):
        path = self.inputs / 'values.csv'
        path.write_bytes('code;amount;label\r\n001;0.10;café\r\n002;0.20;été\r\n003;bad;note\r\n004;;vide\r\n'.encode('cp1252'))
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        config = {'source': {'path': '/datas/ingestion/example/1/inputs/values.csv', 'format': 'CSV', 'encoding': 'cp1252',
                             'field_delimiter': ';', 'row_delimiter': '\r\n'},
                  'columns': [{'source_name': 'code', 'type': 'IDENTIFIER'}, {'source_name': 'amount', 'type': 'DECIMAL'}, {'source_name': 'label', 'type': 'TEXT'}]}
        report = generate_contract_identity([config], self.inspector, ROOT / 'config/types.yaml')
        for value in ('- Source: /datas/ingestion/example/1/inputs/values.csv', '- Charset: CP1252', '- Rows Number: 4', '- Cols Number: 3',
                      '| code | IDENTIFIER |', '| amount | DECIMAL |', '| amount | 0.10 | 0.20 | 0.15 | 0.15 |', '1 valeur(s) incompatible(s)'):
            self.assertIn(value, report)
        self.assertRegex(report, r'ProcessBeginAt: \d{2}:\d{2}:\d{2}')
        self.assertRegex(report, r'ProcessEndAt: \d{2}:\d{2}:\d{2}')
        self.assertRegex(report, r'Filsize: \d+\.\d{2} (o|Ko|Mo)')
        self.assertNotIn('| code | 1 |', report)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_sql_reuses_inventory_omissions_and_statistics_without_evaluating_defaults(self):
        path = self.inputs / 'example.sql'
        path.write_text("CREATE TABLE t (id TEXT PRIMARY KEY, amount NUMERIC(6,2), at TIMESTAMPTZ DEFAULT NOW()); INSERT INTO t(id,amount) VALUES ('001',0.10),('002',0.20);")
        config = {'source': {'path': '/datas/ingestion/example/1/inputs/example.sql', 'format': 'SQL', 'encoding': 'utf-8', 'table': 't'},
                  'columns': [{'source_name': 'id', 'type': 'IDENTIFIER'}, {'source_name': 'amount', 'type': 'DECIMAL'}]}
        report = generate_contract_identity([config], self.inspector, ROOT / 'config/types.yaml')
        for value in ('# Carte d’identité SQL', '- Tables Number: 1', '## Instructions', '## Table t', '- Rows Number: 2', '- Cols Number: 3',
                      '### Présence des valeurs', '| at | 0 | 0 | 2 | 0 |', '| amount | 0.10 | 0.20 | 0.15 | 0.15 |', 'défaut CURRENT_TIMESTAMP non appliqué'):
            self.assertIn(value, report)
        self.assertIn('aucune conversion d’horloge', report)
