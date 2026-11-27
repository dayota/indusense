"""Inspection statique du SQL et contrats indépendants par table."""
from pathlib import Path
from uuid import uuid4

import yaml

from test_bronze import PostgresWorkflowCase
from indusense_api import catalog as db


class SqlTableContractTests(PostgresWorkflowCase):
    legacy_fixture = False

    def setUp(self):
        super().setUp()
        self.base = f'/api/model-versions/{self.version}/bronze'
        content = (Path(__file__).resolve().parents[3] / 'datas/machine.sql').read_bytes()
        response = self.client.post(self.base + '/files', files=[('files', ('machine.sql', content))], data={'manifest': '[{"dataset_name":"machines"}]'})
        self.assertEqual(response.status_code, 200, response.text)
        self.file = self.state()['files'][0]
        directory = (self.root / self.state()['archive_directory']).parent / '_contracts'
        directory.mkdir(parents=True)
        for name in ('machine', 'maintenance'):
            (directory / (name + '.yml')).write_bytes((self.root / 'config/bronze' / (name + '.yml')).read_bytes())

    def state(self):
        response = self.client.get(self.base)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def load(self, tables):
        return self.client.post(self.base + '/contracts/load', json={'files': [{'id': self.file['id'], 'tables': tables}]})

    def test_inspection_counts_all_tables_and_rows_without_loading_data(self):
        response = self.client.post(self.base + f'/files/{self.file["id"]}/inspect-sql', json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual({table['name']: table['rows'] for table in response.json()['tables']}, {'machine': 15, 'maintenance': 115})
        self.assertIsNone(self.state()['files'][0]['loaded_yaml'])
        self.assertIsNone(self.state()['database_name'])
        self.assertEqual(self.count(db.dataset_versions), 0)

    def test_mixed_existing_and_generated_contracts_are_editable_and_saved_per_table(self):
        choices = [{'table': 'machine', 'mode': 'existing', 'contract': 'machine'}, {'table': 'maintenance', 'mode': 'generate'}]
        response = self.load(choices)
        self.assertEqual(response.status_code, 200, response.text)
        file = self.state()['files'][0]
        self.assertEqual([choice['mode'] for choice in file['sql_choices']], ['existing', 'generate'])
        self.assertEqual(len(file['sql_contracts']), 2)
        editors = []
        for item in file['sql_contracts']:
            config = yaml.safe_load(item['yaml'])
            if item['table'] == 'maintenance': config['target']['natural_key'] = ['maintenance_id']
            editors.append({'table': item['table'], 'yaml': yaml.safe_dump(config, sort_keys=False)})
        response = self.client.post(self.base + '/contracts/save', json={'files': [{'id': file['id'], 'revision': file['revision'], 'tables': editors}]})
        self.assertEqual(response.status_code, 200, response.text)
        file = self.state()['files'][0]
        self.assertEqual(file['summary']['rows'], 130)
        self.assertEqual(len(file['sql_contracts']), 2)
        self.assertEqual(file['revision'], 1)

    def test_missing_duplicate_or_foreign_table_choices_are_rejected(self):
        for names in (['machine'], ['machine', 'machine'], ['machine', 'ghost']):
            response = self.load([{'table': name, 'mode': 'generate'} for name in names])
            self.assertEqual(response.status_code, 422, response.text)
        self.assertIsNone(self.state()['files'][0]['loaded_yaml'])

    def test_wrong_existing_contract_and_partial_editor_save_are_rejected(self):
        response = self.load([{'table': 'machine', 'mode': 'existing', 'contract': 'maintenance'}, {'table': 'maintenance', 'mode': 'generate'}])
        self.assertEqual(response.status_code, 422, response.text)
        response = self.load([{'table': 'machine', 'mode': 'existing', 'contract': 'machine'}, {'table': 'maintenance', 'mode': 'existing', 'contract': 'maintenance'}])
        self.assertEqual(response.status_code, 200, response.text)
        file = self.state()['files'][0]
        editor = file['sql_contracts'][0]
        response = self.client.post(self.base + '/contracts/save', json={'files': [{'id': file['id'], 'revision': file['revision'], 'tables': [{'table': editor['table'], 'yaml': editor['yaml']}]}]})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIsNone(self.state()['files'][0]['saved_yaml'])

    def test_inspection_is_scoped_to_version_and_respects_explicit_encoding(self):
        response = self.client.post(f'/api/model-versions/{uuid4()}/bronze/files/{self.file["id"]}/inspect-sql', json={})
        self.assertEqual(response.status_code, 404)
        response = self.client.post(self.base + f'/files/{self.file["id"]}/inspect-sql', json={'encoding': 'ascii'})
        self.assertEqual(response.status_code, 422)
