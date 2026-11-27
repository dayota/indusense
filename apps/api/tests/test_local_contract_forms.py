"""Le seul contrat proposé est celui du fichier de la version, sinon formulaire du schéma."""
import json
from pathlib import Path

import yaml
from sqlalchemy import text
from uuid import UUID
from indusense_api import catalog as db

from test_bronze import PostgresWorkflowCase


class LocalContractFormTests(PostgresWorkflowCase):
    legacy_fixture = False

    def setUp(self):
        super().setUp()
        self.base = f'/api/model-versions/{self.version}/bronze'

    def state(self):
        response = self.client.get(self.base)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def stage(self, content=b'id,value\n001,2\n', name='measure.csv'):
        response = self.client.post(self.base + '/files', files=[('files', (name, content))], data={'manifest': '[{"dataset_name":"measure"}]'})
        self.assertEqual(response.status_code, 200, response.text)
        return self.state()['files'][0]

    def editor(self, file):
        response = self.client.post(self.base + '/contracts/editor', json={'files': [{'id': file['id']}]})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_missing_yaml_exposes_form_and_exact_schema_enums_without_global_suggestions(self):
        file = self.stage()
        response = self.editor(file)
        editor = response['files'][0]['editors'][0]
        self.assertFalse(editor['existing'])
        self.assertEqual(editor['config']['version'], '1.0.0')
        self.assertIsNone(editor['yaml'])
        self.assertTrue(editor['path'].endswith('/_contracts/measure-1.0.0.yml'))
        schema = json.loads((self.root / 'config/schema/bronze.v2.schema.json').read_text())
        self.assertEqual(response['column_types'], schema['properties']['columns']['items']['properties']['type']['enum'])
        self.assertEqual(response['timezones'], ['UTC'])
        self.assertIn('TEXT', response['silver_types']['IDENTIFIER'])
        self.assertNotIn('TIMESTAMP', response['silver_types']['TIMESTAMPTZ'])
        self.assertTrue(editor['config']['source']['has_header'])
        self.assertEqual(self.client.get(self.base + '/contracts/catalogue').json(), [])
        response = self.client.post(self.base + '/contracts/load', json={'files': [{'id': file['id'], 'mode': 'existing', 'contract': 'telemetry'}]})
        self.assertEqual(response.status_code, 422)

    def test_valid_form_publishes_matching_yaml_and_becomes_existing_on_reload(self):
        file = self.stage()
        config = self.editor(file)['files'][0]['editors'][0]['config']
        config['columns'][0].update(type='IDENTIFIER', silver_type='TEXT')
        config['target']['natural_key'] = ['id']
        expected_source = '/' + self.state()['archive_directory'] + '/inputs/measure.csv'
        self.assertEqual(config['source']['path'], expected_source)
        response = self.client.post(self.base + '/contracts/save', json={'files': [{'id': file['id'], 'revision': 0, 'config': config}]})
        self.assertEqual(response.status_code, 200, response.text)
        path = (self.root / self.state()['archive_directory']).parent / '_contracts/measure-1.0.0.yml'
        self.assertEqual(yaml.safe_load(path.read_text()), config)
        self.assertEqual(yaml.safe_load(path.read_text())['source']['path'], expected_source)
        snapshot = self.root / self.state()['archive_directory'] / '_contracts/measure-1.0.0.yml'
        self.assertEqual(yaml.safe_load(snapshot.read_text()), config)
        editor = self.editor(file)['files'][0]['editors'][0]
        self.assertTrue(editor['existing'])
        self.assertEqual(editor['config'], config)
        self.assertEqual(len(self.client.get(self.base + '/contracts/catalogue').json()), 1)

    def test_postgres_options_follow_native_schema_and_exclude_custom_types(self):
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TYPE public.form_mood AS ENUM ('ready', 'pending')"))
            connection.execute(text('CREATE DOMAIN public.form_code AS text'))
        try:
            response = self.client.get(self.base + '/contracts/schema')
            self.assertEqual(response.status_code, 200, response.text)
            options = response.json()['postgres_types']
            for name in ('JSONB', 'UUID', 'BYTEA', 'XML', 'INET', 'INT4RANGE', 'INTEGER[]',
                         'TIMESTAMP WITH TIME ZONE', 'TIMESTAMPTZ', 'SERIAL'):
                self.assertIn(name, options)
            for name in ('VOID', 'TRIGGER', 'RECORD', 'form_mood', 'form_code', 'SERIAL[]'):
                self.assertNotIn(name, options)
            file = self.stage()
            self.assertEqual(self.editor(file)['postgres_types'], options)
        finally:
            with self.engine.begin() as connection:
                connection.execute(text('DROP DOMAIN public.form_code'))
                connection.execute(text('DROP TYPE public.form_mood'))

    def test_model_recipe_is_reused_by_new_version_without_changing_frozen_snapshot(self):
        file = self.stage()
        config = self.editor(file)['files'][0]['editors'][0]['config']
        config['target']['natural_key'] = ['id']
        response = self.client.post(self.base + '/contracts/save', json={'files': [{'id': file['id'], 'revision': 0, 'config': config}]})
        self.assertEqual(response.status_code, 200, response.text)
        snapshot = self.state()['files'][0]['saved_yaml']
        with self.engine.begin() as connection:
            connection.execute(db.model_versions.update().where(db.model_versions.c.id == UUID(self.version)).values(read_only=True))
        response = self.client.post(f'/api/models/{self.model["id"]}/versions', json={'preparation': True})
        self.assertEqual(response.status_code, 201, response.text)
        child_base = f'/api/model-versions/{response.json()["id"]}/bronze'
        response = self.client.post(child_base + '/files', files=[('files', ('measure.csv', b'id,value\n002,3\n'))], data={'manifest': '[{"dataset_name":"measure"}]'})
        self.assertEqual(response.status_code, 200, response.text)
        child_file = self.client.get(child_base).json()['files'][0]
        response = self.client.post(child_base + '/contracts/editor', json={'files': [{'id': child_file['id']}]})
        self.assertEqual(response.status_code, 200, response.text)
        editor = response.json()['files'][0]['editors'][0]
        self.assertTrue(editor['existing'])
        self.assertEqual(editor['config']['source']['path'], '/' + self.client.get(child_base).json()['archive_directory'] + '/inputs/measure.csv')
        self.assertNotIn('/2/_contracts/', editor['path'])
        editor['config']['target']['table'] = 'measure_updated'
        response = self.client.post(child_base + '/contracts/save', json={'files': [{'id': child_file['id'], 'revision': 0, 'config': editor['config']}]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.state()['files'][0]['saved_yaml'], snapshot)
        archived = self.root / self.state()['archive_directory'] / '_contracts/measure-1.0.0.yml'
        self.assertEqual(yaml.safe_load(archived.read_text()), yaml.safe_load(snapshot))
        # Une recette courante invalide ne doit pas empêcher de consulter la version figée.
        (self.root / editor['path']).write_text('version: invalid')
        frozen = self.editor(file)['files'][0]['editors'][0]['config']
        self.assertEqual(frozen, yaml.safe_load(snapshot))

    def test_legacy_draft_path_is_normalized_but_foreign_sources_are_refused(self):
        file = self.stage()
        config = self.editor(file)['files'][0]['editors'][0]['config']
        config['target']['natural_key'] = ['id']
        expected = config['source']['path']
        for wrong in ('/datas/ingestion/other/1/inputs/measure.csv', expected.replace('/1/', '/2/'), '/tmp/measure.csv', expected.replace('/inputs/', '/')):
            config['source']['path'] = wrong
            response = self.client.post(self.base + '/contracts/save', json={'files': [{'id': file['id'], 'revision': 0, 'config': config}]})
            self.assertEqual(response.status_code, 422, response.text)
        config['source']['path'] = f'uploads/{file["id"]}/{file["filename"]}'
        response = self.client.post(self.base + '/contracts/save', json={'files': [{'id': file['id'], 'revision': 0, 'config': config}]})
        self.assertEqual(response.status_code, 200, response.text)
        saved = yaml.safe_load(self.state()['files'][0]['saved_yaml'])
        self.assertEqual(saved['source']['path'], expected)
        recipe = (self.root / self.state()['archive_directory']).parent / '_contracts/measure-1.0.0.yml'
        self.assertEqual(yaml.safe_load(recipe.read_text())['source']['path'], expected)

    def test_invalid_form_is_rejected_before_writing_any_yaml(self):
        file = self.stage()
        config = self.editor(file)['files'][0]['editors'][0]['config']
        config['columns'][0]['type'] = 'NOT_IN_SCHEMA'
        response = self.client.post(self.base + '/contracts/save', json={'files': [{'id': file['id'], 'revision': 0, 'config': config}]})
        self.assertEqual(response.status_code, 422)
        self.assertFalse(((self.root / self.state()['archive_directory']).parent / '_contracts/measure-1.0.0.yml').exists())

    def test_filename_uses_contract_version_and_mismatch_is_rejected(self):
        file = self.stage()
        config = self.editor(file)['files'][0]['editors'][0]['config']
        config['target']['natural_key'] = ['id']
        config['version'] = '3.2.1'
        response = self.client.post(self.base + '/contracts/save', json={'files': [{'id': file['id'], 'revision': 0, 'config': config}]})
        self.assertEqual(response.status_code, 200, response.text)
        directory = (self.root / self.state()['archive_directory']).parent / '_contracts'
        self.assertTrue((directory / 'measure-3.2.1.yml').is_file())
        self.assertFalse((directory / 'measure-1.0.0.yml').exists())
        editor = self.editor(file)['files'][0]['editors'][0]
        self.assertTrue(editor['existing'])
        self.assertTrue(editor['path'].endswith('/measure-3.2.1.yml'))
        (directory / 'measure-3.2.1.yml').rename(directory / 'measure-9.0.0.yml')
        response = self.client.post(self.base + '/contracts/editor', json={'files': [{'id': file['id']}]})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn('version', response.text)

    def test_latest_numeric_version_is_loaded_and_model_directory_never_downgrades(self):
        file = self.stage()
        config = self.editor(file)['files'][0]['editors'][0]['config']
        config['target']['natural_key'] = ['id']
        for revision, version in enumerate(('1.9.0', '1.10.0')):
            config['version'] = version
            response = self.client.post(self.base + '/contracts/save', json={'files': [{'id': file['id'], 'revision': revision, 'config': config}]})
            self.assertEqual(response.status_code, 200, response.text)
        directory = (self.root / self.state()['archive_directory']).parent / '_contracts'
        self.assertEqual({path.name for path in directory.glob('*.yml')}, {'measure-1.10.0.yml'})
        snapshots = self.root / self.state()['archive_directory'] / '_contracts'
        self.assertEqual({path.name for path in snapshots.glob('*.yml')}, {'measure-1.9.0.yml', 'measure-1.10.0.yml'})
        old_snapshot = (snapshots / 'measure-1.9.0.yml').read_bytes()
        # Simuler un ancien catalogue avec plusieurs recettes : tri numérique, pas alphabétique.
        (directory / 'measure-1.9.0.yml').write_bytes(old_snapshot)
        editor = self.editor(file)['files'][0]['editors'][0]
        self.assertEqual(editor['config']['version'], '1.10.0')
        self.assertTrue(editor['path'].endswith('/measure-1.10.0.yml'))
        catalogue = self.client.get(self.base + '/contracts/catalogue').json()
        self.assertEqual([item['version'] for item in catalogue], ['1.10.0'])
        for reference in ('measure-1.9.0', 'measure-1.9.0.yml'):
            response = self.client.post(self.base + '/contracts/load', json={'files': [{'id': file['id'], 'mode': 'existing', 'contract': reference}]})
            self.assertEqual(response.status_code, 422, response.text)
            self.assertIn('plus récente', response.text)
        response = self.client.post(self.base + '/contracts/load', json={'files': [{'id': file['id'], 'mode': 'existing', 'contract': 'measure-1.10.0'}]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(yaml.safe_load(self.state()['files'][0]['loaded_yaml'])['version'], '1.10.0')
        config['version'] = '1.2.0'
        response = self.client.post(self.base + '/contracts/save', json={'files': [{'id': file['id'], 'revision': 2, 'config': config}]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual({path.name for path in directory.glob('*.yml')}, {'measure-1.10.0.yml'})
        self.assertTrue((snapshots / 'measure-1.2.0.yml').is_file())
        self.assertEqual((snapshots / 'measure-1.9.0.yml').read_bytes(), old_snapshot)

    def test_unrelated_yaml_and_other_model_are_not_proposed(self):
        file = self.stage()
        directory = (self.root / self.state()['archive_directory']).parent / '_contracts'
        directory.mkdir(parents=True)
        (directory / 'unrelated.yml').write_text('version: invalid')
        other = self.root / 'datas/ingestion/other/_contracts'
        other.mkdir(parents=True)
        (other / 'measure.yml').write_text('version: invalid')
        self.assertFalse(self.editor(file)['files'][0]['editors'][0]['existing'])
        self.assertEqual(self.client.get(self.base + '/contracts/catalogue').json(), [])

    def test_sql_form_writes_one_yaml_per_table_and_never_a_bundle(self):
        content = (Path(__file__).resolve().parents[3] / 'datas/machine.sql').read_bytes()
        file = self.stage(content, 'machine.sql')
        editors = self.editor(file)['files'][0]['editors']
        self.assertEqual({item['table'] for item in editors}, {'machine', 'maintenance'})
        tables = []
        for editor in editors:
            config = editor['config']
            config['target']['natural_key'] = ['machine_code'] if editor['table'] == 'machine' else ['maintenance_id']
            tables.append({'table': editor['table'], 'config': config})
        response = self.client.post(self.base + '/contracts/save', json={'files': [{'id': file['id'], 'revision': 0, 'tables': tables}]})
        self.assertEqual(response.status_code, 200, response.text)
        directory = (self.root / self.state()['archive_directory']).parent / '_contracts'
        self.assertEqual({path.name for path in directory.glob('*.yml')}, {'machine-1.0.0.yml', 'maintenance-1.0.0.yml'})
        snapshots = self.root / self.state()['archive_directory'] / '_contracts'
        self.assertEqual({path.name for path in snapshots.glob('*.yml')}, {'machine-1.0.0.yml', 'maintenance-1.0.0.yml'})
        for path in directory.glob('*.yml'):
            self.assertIsInstance(yaml.safe_load(path.read_text()), dict)
        self.assertTrue(all(item['existing'] for item in self.editor(file)['files'][0]['editors']))
