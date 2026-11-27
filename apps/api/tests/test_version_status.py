from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
from unittest.mock import patch
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from indusense_api import catalog as db
from indusense_api.main import create_app
from indusense_api.version_status import ModelVersionStatus
from test_bronze import PostgresWorkflowCase, ROOT


class VersionStatusTests(PostgresWorkflowCase):
    def validate(self, stage, version=None, client=None):
        return (client or self.client).post(f'/api/model-versions/{version or self.version}/validate-stage', json={'stage': stage})

    def write_status(self, version, status):
        # Préparer des fixtures ; l’application ne fournit aucun changement manuel de statut.
        with self.engine.begin() as connection:
            connection.execute(db.model_versions.update().where(db.model_versions.c.id == UUID(version)).values(status=status))

    def test_creation_and_fork_start_in_bronze_even_from_a_champion(self):
        self.assertEqual(self.model['status'], 'ingestion-bronze')
        self.write_status(self.version, 'champion')
        fork = self.client.post(f'/api/models/{self.model["id"]}/versions', json={'from_version_id': self.version}).json()
        self.assertEqual(fork['status'], 'ingestion-bronze')

    def test_no_status_can_be_changed_manually(self):
        before = self.count(db.history)
        for status in ModelVersionStatus:
            response = self.client.patch(f'/api/model-versions/{self.version}/status', json={'status': status.value})
            self.assertEqual(response.status_code, 405, response.text)
        self.assertEqual(self.count(db.history), before)
        self.assertEqual(self.client.get(f'/api/model-versions/{self.version}').json()['status'], 'ingestion-bronze')

    def test_empty_bronze_invalid_stage_and_missing_version_are_rejected(self):
        self.assertEqual(self.validate('bronze').status_code, 409)
        self.assertEqual(self.validate('silver').status_code, 409)
        self.assertEqual(self.validate('gold').status_code, 422)
        self.assertEqual(self.validate('bronze', uuid4()).status_code, 404)
        response = self.client.post(f'/api/model-versions/{self.version}/validate-stage', json={'stage': 'bronze', 'status': 'champion'})
        self.assertEqual(response.status_code, 422)

    def test_bronze_validation_changes_status_and_records_the_step_once(self):
        self.upload()
        response = self.validate('bronze')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'ingestion-silver')
        self.assertEqual(self.validate('bronze').status_code, 409)
        events = self.client.get(f'/api/model-versions/{self.version}').json()['history']
        self.assertEqual(sum(event['action'] == 'stage_validated' for event in events), 1)
        self.assertEqual(events[0]['details'], {'from_status': 'ingestion-bronze', 'to_status': 'ingestion-silver'})

    def test_silver_preparation_requires_validated_bronze(self):
        snapshot = self.upload().json()['results'][0]['snapshot_id']
        base = f'/api/model-versions/{self.version}/silver'
        draft = self.client.get(f'{base}/contracts/{snapshot}').json()['yaml']
        contract = self.client.post(f'{base}/contracts/{snapshot}', json={'yaml': draft}).json()
        response = self.client.post(f'{base}/prepare/{snapshot}', json={'contract_id': contract['id']})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.count(db.silver_runs), 0)
        self.assertEqual(self.validate('bronze').status_code, 200)
        self.assertEqual(self.validate('silver').status_code, 409)

    def test_validated_bronze_sources_are_frozen_and_a_new_version_can_reuse_them(self):
        first = self.upload().json()['results'][0]
        self.assertEqual(self.validate('bronze').status_code, 200)
        self.assertEqual(self.upload(b'id,value\n002,9\n').status_code, 409)
        self.assertEqual(self.count(db.dataset_versions), 1)
        fork = self.client.post(f'/api/models/{self.model["id"]}/versions', json={}).json()
        reused = self.upload(version=fork['id'])
        self.assertEqual(reused.status_code, 409, reused.text)
        detail = self.client.get(f'/api/model-versions/{fork["id"]}').json()
        self.assertEqual(detail['preparation']['state'], 'draft')

    def test_silver_validation_requires_all_current_tables_and_freezes_preparation(self):
        first = self.upload().json()['results'][0]
        second = self.upload(b'id,value\n002,3\n', dataset='second').json()['results'][0]
        self.assertEqual(self.validate('bronze').status_code, 200)
        self.assertEqual(self.validate('silver').status_code, 409)
        base = f'/api/model-versions/{self.version}/silver'
        for result in (first, second):
            snapshot = result['snapshot_id']
            draft = self.client.get(f'{base}/contracts/{snapshot}').json()['yaml']
            contract = self.client.post(f'{base}/contracts/{snapshot}', json={'yaml': draft}).json()
            run = self.client.post(f'{base}/prepare/{snapshot}', json={'contract_id': contract['id']})
            self.assertEqual(run.status_code, 200, run.text)
            self.assertEqual(self.client.get(f'/api/model-versions/{self.version}').json()['status'], 'ingestion-silver')
            if result == first:
                self.assertEqual(self.validate('silver').status_code, 409)
        response = self.validate('silver')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'ingestion-gold')
        self.assertEqual(self.client.post(f'{base}/contracts/{snapshot}', json={'yaml': draft + '# edit', 'base_revision': 1}).status_code, 409)
        self.assertEqual(self.client.post(f'{base}/prepare/{snapshot}', json={'contract_id': contract['id']}).status_code, 409)
        self.assertEqual(self.validate('silver').status_code, 409)

    def test_simultaneous_step_validations_cannot_skip_a_stage(self):
        self.upload()
        barrier = Barrier(2)
        def send(index):
            with TestClient(create_app(engine=self.engine, resource_root=self.root)) as client:
                barrier.wait(timeout=10)
                return self.validate('bronze', client=client)
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(send, range(2)))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409], [response.text for response in responses])
        self.assertEqual(self.client.get(f'/api/model-versions/{self.version}').json()['status'], 'ingestion-silver')

    def test_database_constraints_keep_champion_and_challenger_exclusive_per_model(self):
        second = self.client.post(f'/api/models/{self.model["id"]}/versions', json={}).json()['id']
        other = self.client.post('/api/models', json={'name': 'other model'}).json()['version_id']
        for status in ('champion', 'challenger'):
            self.write_status(self.version, status)
            self.write_status(other, status)
            with self.assertRaises(IntegrityError) as error:
                self.write_status(second, status)
            self.assertEqual(error.exception.orig.diag.constraint_name, f'uq_model_versions_{status}')
        with self.assertRaises(IntegrityError):
            self.write_status(second, 'unknown')

    def test_initial_migration_matches_current_schema_and_replay_preserves_data(self):
        # Tester l'installation consolidée sur une base vide, puis son rejeu sans réécriture.
        from psycopg import sql
        from sqlalchemy import create_engine
        name = 'indusense_test_upgrade_' + uuid4().hex[:10]
        with self.admin() as admin:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        engine = create_engine(self.url.set(database=name))
        try:
            config = Config(str(ROOT / 'apps/api/alembic.ini'))
            with patch.dict(os.environ, {'DB_NAME': name}):
                command.upgrade(config, 'head')
                with engine.begin() as connection:
                    model_id, version_id = uuid4(), uuid4()
                    connection.execute(text("INSERT INTO bronze.models (id, name, description) VALUES (:id, 'historique', '')"), {'id': model_id})
                    connection.execute(text('INSERT INTO bronze.model_versions (id, model_id, number) VALUES (:id, :model, 1)'), {'id': version_id, 'model': model_id})
                command.upgrade(config, 'head')
            with engine.connect() as connection:
                from alembic.autogenerate import compare_metadata
                from alembic.migration import MigrationContext
                differences = compare_metadata(MigrationContext.configure(connection, opts={
                    'include_schemas': True, 'version_table_schema': 'bronze', 'compare_server_default': True,
                }), db.metadata)
                self.assertEqual(differences, [])
                row = connection.execute(select(db.model_versions)).mappings().one()
                self.assertEqual(row['id'], version_id)
                self.assertEqual(row['status'], 'ingestion-bronze')
                self.assertFalse(row['read_only'])
                self.assertEqual(connection.scalar(text('SELECT version_num FROM bronze.alembic_version')), '0001_initial')
        finally:
            engine.dispose()
            with self.admin() as admin:
                admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
