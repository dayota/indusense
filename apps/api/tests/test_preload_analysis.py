"""Vérifier le moteur du préchargement sans dépendre de PostgreSQL."""

import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import yaml
from fastapi.testclient import TestClient

from indusense_api.main import create_app
from indusense_api.schemas import UploadEntry
from indusense_api.services.analysis import analyze, parse_csv_contract, raw_csv
from indusense_api.services.preload import preload
from indusense_ingestion.contracts import read_config

ROOT = Path(__file__).resolve().parents[3]


class PreloadAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / 'config', self.root / 'config')
        self.workspace = self.root / 'work'
        self.workspace.mkdir()
        self.engine = MagicMock()
        self.connection = self.engine.connect.return_value.__enter__.return_value
        self.connection.scalar.return_value = uuid4()

    def source(self, content, filename='measure.csv', index=0):
        path = self.root / f'source-{index}{Path(filename).suffix}'
        path.write_bytes(content)
        return {'path': path, 'filename': filename, 'format': path.suffix[1:],
                'sha256': hashlib.sha256(content).hexdigest(), 'size_bytes': len(content)}

    def test_generated_and_existing_contracts_keep_per_file_mapping_without_writes(self):
        sources = [self.source(b'machine_id,value\n001,2\n'), self.source(b'name,amount\nitem,1.25\n', 'amounts.csv', 1)]
        (self.root / 'config/contracts/amounts.yaml').write_text('version: 1\ndataset: amounts\ncolumns:\n  name: {type: TEXT}\n  amount: {type: DECIMAL}\n')
        entries = [UploadEntry(dataset_name='generated', contract_mode='generate'), UploadEntry(dataset_name='existing', contract='amounts')]
        result = preload(self.engine, uuid4(), sources, entries, self.root, self.workspace)['results']
        self.assertEqual([item['filename'] for item in result], ['measure.csv', 'amounts.csv'])
        self.assertEqual(yaml.safe_load(result[0]['contract_yaml'])['columns']['machine_id']['type'], 'IDENTITY')
        self.assertEqual(yaml.safe_load(result[1]['contract_yaml'])['columns']['amount']['type'], 'DECIMAL')
        self.engine.begin.assert_not_called()
        self.connection.execute.assert_not_called()
        self.assertFalse((self.root / 'artifacts').exists())

    def test_edited_contract_is_the_contract_used_by_the_final_analyzer(self):
        source = self.source(b'code,value\n001,2\n')
        text = 'version: 1\ndataset: edited\nextra_columns: error\ncolumns:\n  code: {type: IDENTITY}\n  value: {type: TEXT}\n'
        result = analyze(source, UploadEntry(dataset_name='edited', contract_mode='generate', contract_yaml=text), self.root, self.workspace)
        self.assertEqual(result['summary']['tables'][0]['columns'], [{'name': 'code', 'type': 'IDENTITY'}, {'name': 'value', 'type': 'TEXT'}])
        self.assertEqual(result['tables']['data'], [{'code': '001', 'value': '2'}])
        self.assertEqual(result['contract']['columns']['value']['type'], 'TEXT')

    def test_selected_incidents_contract_is_returned_unchanged_without_generation(self):
        source = self.source((ROOT / 'datas/releves_incidents.csv').read_bytes())
        entry = UploadEntry(dataset_name='incidents', contract_mode='existing', contract='incidents')
        with patch('indusense_api.services.preload.propose_contract', side_effect=AssertionError('Ne pas générer un contrat existant')):
            result = preload(self.engine, uuid4(), [source], [entry], self.root, self.workspace)['results'][0]
        self.assertEqual(result['contract_yaml'], (self.root / 'config/contracts/incidents.yaml').read_text())

    def test_existing_rules_are_preserved_and_applied_without_expanding_the_yaml(self):
        (self.root / 'config/contracts/rules.yaml').write_text('version: 1\ndataset: flags\ncolumns: {}\ncolumn_rules:\n  - {pattern: "^type_", type: INTEGER, allowed: [0, 1]}\n')
        source = self.source(b'type_fault,label\n1,hello\n')
        result = preload(self.engine, uuid4(), [source], [UploadEntry(dataset_name='flags', contract='rules')], self.root, self.workspace)['results'][0]
        self.assertEqual(result['contract_yaml'], (self.root / 'config/contracts/rules.yaml').read_text())
        self.assertEqual(result['summary']['tables'][0]['columns'], [{'name': 'type_fault', 'type': 'INTEGER'}, {'name': 'label', 'type': 'TEXT'}])
        self.assertEqual(result['contract_mode'], 'existing')
        self.assertEqual(result['contract_name'], 'rules')

    def test_unsafe_duplicate_unknown_and_non_json_yaml_are_rejected(self):
        types = read_config(self.root / 'config/types.yaml')['types']
        for text in ('!!python/object/apply:os.system [echo bad]', 'version: 1\nversion: 1',
                     'version: 1\ndataset: test\ncolumns: {x: {type: UNKNOWN}}',
                     'version: 1\ndataset: test\ncolumns: {x: {type: TEXT, allowed: [2026-11-26]}}'):
            with self.subTest(text=text), self.assertRaises((ValueError, yaml.YAMLError)):
                parse_csv_contract(text, types)
        with self.assertRaises(ValueError):
            raw_csv(self.source(b'id,id\n1,2\n')['path'])

    def test_http_preload_route_accepts_generated_contract_mode_without_opening_write_transaction(self):
        with TestClient(create_app(engine=self.engine, resource_root=self.root)) as client:
            response = client.post(f'/api/model-versions/{uuid4()}/preload',
                                   files=[('files', ('file.csv', b'code,value\nA,2\n'))],
                                   data={'manifest': '[{"dataset_name":"new","contract_mode":"generate"}]'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('INTEGER', response.json()['results'][0]['contract_yaml'])
        self.engine.begin.assert_not_called()
        self.connection.execute.assert_not_called()
