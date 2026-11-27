import hashlib
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import inspect

from indusense_api import catalog as db
from test_bronze import PostgresWorkflowCase


class ContractIdentityWorkflowTests(PostgresWorkflowCase):
    legacy_fixture = False

    def setUp(self):
        super().setUp()
        self.base = f'/api/model-versions/{self.version}/bronze'

    def state(self):
        return self.client.get(self.base).json()

    def stage(self, name='values.csv', content=b'id,value\n001,0.10\n002,0.20\n'):
        response = self.client.post(self.base + '/files', files=[('files', (name, content))],
                                    data={'manifest': json.dumps([{'dataset_name': Path(name).stem}])})
        self.assertEqual(response.status_code, 200, response.text)
        files = self.state()['files']
        response = self.client.post(self.base + '/contracts/editor', json={'files': [{'id': file['id']} for file in files]})
        self.assertEqual(response.status_code, 200, response.text)
        entries = []
        for file in response.json()['files']:
            configs = [editor['config'] for editor in file['editors']]
            for config in configs:
                config['target']['natural_key'] = ['id']
                for column in config['columns']:
                    column.update(type='IDENTIFIER', silver_type='TEXT') if column['source_name'] == 'id' else column.update(type='DECIMAL', silver_type='NUMERIC(6,2)')
                    column.pop('unit', None)
            original = next(item for item in files if item['id'] == file['id'])
            entries.append({'id': file['id'], 'revision': file['revision'], **(
                {'tables': [{'table': editor['table'], 'config': config} for editor, config in zip(file['editors'], configs)]}
                if original['format'] == 'sql' else {'config': configs[0]})})
        return entries

    def test_next_acceptance_generates_csv_card_with_statistics_and_persists_it(self):
        entries = self.stage()
        self.assertEqual(self.client.post(self.base + '/identities/generate').status_code, 422)
        response = self.client.post(self.base + '/contracts/save', json={'files': entries})
        self.assertEqual(response.status_code, 200, response.text)
        state = self.state()
        archive = state['archives'][0]
        self.assertIn('/1/inputs/values.csv', archive['path'])
        source_before = hashlib.sha256((self.root / archive['path']).read_bytes()).hexdigest()
        self.assertIsNone(state['files'][0]['report'])
        self.assertEqual(self.client.post(self.base + '/identities/confirm').status_code, 409)
        response = self.client.post(self.base + '/identities/generate')
        self.assertEqual(response.status_code, 200, response.text)
        state = self.state()
        path = self.root / state['archive_directory'] / 'artifacts/ingestion-values.csv.md'
        report = path.read_text()
        self.assertEqual(state['files'][0]['report'], report)
        self.assertEqual(state['files'][0]['summary']['identity_path'], '/' + str(path.relative_to(self.root)))
        self.assertIn('- Source: /' + archive['path'], report)
        self.assertIn('- Rows Number: 2', report)
        self.assertIn('| id | IDENTIFIER |', report)
        self.assertIn('| value | 0.10 | 0.20 | 0.15 | 0.15 |', report)
        self.assertEqual(hashlib.sha256((self.root / archive['path']).read_bytes()).hexdigest(), source_before)
        self.assertFalse(state['identities_reviewed'])
        self.assertEqual(self.client.post(self.base + '/identities/confirm').status_code, 200)

    def test_invalid_contract_prevents_acceptance_and_report_generation(self):
        entries = self.stage()
        entries[0]['config']['target']['natural_key'] = []
        self.assertEqual(self.client.post(self.base + '/contracts/save', json={'files': entries}).status_code, 422)
        self.assertEqual(self.client.post(self.base + '/identities/generate').status_code, 422)
        self.assertEqual(list((self.root / 'datas/ingestion').rglob('ingestion-*.md')), [])

    def test_sql_card_contains_all_tables_without_executing_ddl_or_defaults(self):
        sql = b"CREATE TABLE events (id TEXT PRIMARY KEY, amount NUMERIC(6,2), created_at TIMESTAMPTZ DEFAULT NOW()); INSERT INTO events(id,amount) VALUES ('001',0.10),('002',0.20); CREATE TABLE measures (id TEXT PRIMARY KEY, value INTEGER); INSERT INTO measures VALUES ('001',2);"
        entries = self.stage('example.sql', sql)
        self.assertEqual(self.client.post(self.base + '/contracts/save', json={'files': entries}).status_code, 200)
        response = self.client.post(self.base + '/identities/generate')
        self.assertEqual(response.status_code, 200, response.text)
        state = self.state()
        report = (self.root / state['archive_directory'] / 'artifacts/ingestion-example.sql.md').read_text()
        for value in ('- Tables Number: 2', '## Table events', '## Table measures', '### Présence des valeurs', 'défaut CURRENT_TIMESTAMP non appliqué'):
            self.assertIn(value, report)
        self.assertNotIn('events', inspect(self.engine).get_table_names())

    def test_previous_archive_layout_is_refused_instead_of_used_implicitly(self):
        entries = self.stage()
        archive = self.state()['archives'][0]
        current = self.root / archive['path']
        old = current.parent.parent / current.name
        old.write_bytes(current.read_bytes())
        current.unlink()
        with self.engine.begin() as connection:
            connection.execute(db.source_archives.update().where(db.source_archives.c.id == UUID(archive['id'])).values(path=str(old.relative_to(self.root))))
        response = self.client.post(self.base + '/contracts/save', json={'files': entries})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertFalse(current.exists())
        self.assertEqual(self.client.get(self.base + f"/files/{archive['id']}/download").status_code, 409)
