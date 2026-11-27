"""Invariants Bronze v2 sur PostgreSQL réel et isolé."""
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from fastapi.testclient import TestClient

import sqlalchemy as sa
import yaml
from psycopg import sql

from test_bronze import PostgresWorkflowCase
from indusense_api import catalog as db
from indusense_api.services import bronze_storage as storage


class BronzeV2Tests(PostgresWorkflowCase):
    legacy_fixture = False
    def setUp(self):
        super().setUp()
        self.model_name = "bronze_v2_test_" + uuid4().hex[:12]
        with self.engine.begin() as connection:
            connection.execute(db.models.update().where(db.models.c.id == UUID(self.model["id"])).values(name=self.model_name))
        self.base = f"/api/model-versions/{self.version}/bronze"
        self.target_name = storage.normalized_name(self.model_name)
        self.addCleanup(self.remove_target)

    def remove_target(self):
        assert self.target_name.startswith("bronze_v2_test_")
        with self.admin() as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(self.target_name)))

    def state(self):
        response = self.client.get(self.base)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def stage(self, content=b"id,value\n001,2\n002,abc\n003,\n001,2\n"):
        response = self.client.post(self.base + "/files", files=[("files", ("sample.csv", content))],
                                    data={"manifest": '[{"dataset_name":"mesures"}]'})
        self.assertEqual(response.status_code, 200, response.text)
        file = self.state()["files"][0]
        response = self.client.post(self.base + "/contracts/load", json={"files": [{"id": file["id"], "mode": "generate"}]})
        self.assertEqual(response.status_code, 200, response.text)
        return self.state()["files"][0]

    def save(self, ratio=1.0, approve=True, file=None):
        file = file or self.state()["files"][0]
        config = yaml.safe_load(file["loaded_yaml"])
        config["target"]["natural_key"] = ["id"]
        config["columns"] = [{"source_name": "id", "target_name": "id", "type": "IDENTIFIER", "silver_type": "TEXT"},
                              {"source_name": "value", "target_name": "value", "type": "INTEGER", "silver_type": "BIGINT", "nullable": False}]
        if ratio is None:
            config.pop("max_cast_error_ratio", None)
        else:
            config["max_cast_error_ratio"] = ratio
        config["derived_columns"] = [{"target_name": "future_value", "operation": "NORM", "operate_on_columns": ["value"], "silver_type": "DOUBLE PRECISION"}]
        response = self.client.post(self.base + "/contracts/save", json={"files": [{"id": file["id"], "yaml": yaml.safe_dump(config, sort_keys=False), "revision": file["revision"]}]})
        self.assertEqual(response.status_code, 200, response.text)
        generated = self.client.post(self.base + '/identities/generate')
        self.assertEqual(generated.status_code, 200, generated.text)
        self.assertEqual(self.client.post(self.base + "/identities/confirm").status_code, 200)
        response = self.client.post(self.base + "/migrations/generate")
        self.assertEqual(response.status_code, 200, response.text)
        if approve:
            result = self.client.post(self.base + "/migrations/approve", json={"hash": response.json()["hash"]})
            self.assertEqual(result.status_code, 200, result.text)
        return response.json()

    def create(self):
        return self.client.post(self.base + "/create", json={"files": [{"id": file["id"], "revision": file["revision"]} for file in self.state()["files"]]})

    def test_raw_cells_cast_errors_blanks_duplicates_and_explicit_validation(self):
        self.stage(); self.save()
        response = self.create()
        self.assertEqual(response.status_code, 200, response.text)
        state = response.json()
        self.assertEqual((state["status"], state["state"]), ("ingestion-bronze", "created"))
        self.assertTrue(state["can_validate"])
        self.assertEqual(state["batches"][0]["status"], "PARTIAL")
        target = storage.version_engine(self.engine, self.target_name)
        try:
            with target.connect() as connection:
                rows = connection.execute(sa.text('SELECT * FROM "1-bronze".mesures ORDER BY _row_number')).mappings().all()
                self.assertEqual(len(rows), 4)
                self.assertEqual([row["id_raw"] for row in rows], ["001", "002", "003", "001"])
                self.assertEqual([row["value_raw"] for row in rows], ["2", "abc", "", "2"])
                self.assertEqual([row["value"] for row in rows], [2, None, None, 2])
                self.assertIn("value", rows[1]["_cast_errors"])
                self.assertEqual(rows[2]["_cast_errors"], {})
                self.assertNotIn("future_value", rows[0])
                self.assertEqual(rows[0]["_row_checksum"], rows[3]["_row_checksum"])
        finally:
            target.dispose()
        again = self.create()
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["batches"][0]["status"], "SKIPPED")
        self.assertEqual(again.json()["dataset"]["valid"], 4)
        result = self.client.post(self.base + "/validate")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "ingestion-silver")
        self.assertEqual(self.create().status_code, 409)
        with self.engine.connect() as connection:
            logs = connection.execute(sa.select(db.ingestion_batches_log)).mappings().all()
        self.assertEqual(len(logs), 2)
        for log in logs:
            self.assertIn("transformations", log["report"])
            self.assertIn("transformations", log["dictionary"])
            self.assertTrue((self.root / log["artifact_path"] / "data-dictionary.json").is_file())

    def test_threshold_rolls_back_and_failure_is_durable_replay_uses_same_database(self):
        self.stage(); self.save(ratio=0)
        self.assertEqual(self.create().status_code, 200)
        state = self.state()
        self.assertEqual(state["batches"][0]["status"], "FAILED")
        self.assertEqual(state["batches"][0]["records_inserted"], 0)
        self.assertEqual(state["dataset"]["valid"], 0)
        self.assertFalse(state["can_validate"])
        self.assertEqual(self.client.post(self.base + "/validate").status_code, 409)
        response = self.create()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["batches"]), 2)
        target = storage.version_engine(self.engine, self.target_name)
        try:
            with target.connect() as connection:
                logs = connection.execute(sa.text('SELECT * FROM "1-bronze"._ingestion_errors ORDER BY row_number')).mappings().all()
                self.assertEqual(len(logs), 8)  # Four cancelled rows for each of the two attempts.
                self.assertEqual(sum(bool(row['errors']) for row in logs), 2)
                self.assertTrue(all('Seuil' in row['reason'] for row in logs))
                self.assertIn({'id': '002', 'value': 'abc'}, [json.loads(row['raw_data']) for row in logs])
        finally:
            target.dispose()

    def test_model_database_is_shared_but_version_schemas_and_metrics_are_isolated(self):
        self.stage(); self.save(); self.assertEqual(self.create().status_code, 200)
        first_version = self.version
        self.assertEqual(self.client.post(self.base + '/validate').status_code, 200)
        response = self.client.post(f'/api/models/{self.model["id"]}/versions', json={'preparation': True})
        self.assertEqual(response.status_code, 201, response.text)
        self.version = response.json()['id']; self.base = f'/api/model-versions/{self.version}/bronze'
        self.stage(); plan = self.save()
        self.assertEqual(plan['schema'], '2-bronze')
        self.assertIn('"2-bronze"', plan['sql'])
        self.assertNotIn('DROP ', plan['sql'])
        result = self.create()
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['database_name'], self.target_name)
        target = storage.version_engine(self.engine, self.target_name)
        try:
            with target.connect() as connection:
                self.assertEqual(connection.scalar(sa.text('SELECT current_schema()')), 'versionning')
                for number in (1, 2):
                    self.assertEqual(connection.scalar(sa.text(f'SELECT count(*) FROM "{number}-bronze".mesures')), 4)
                versions = connection.execute(sa.text('SELECT number, status, metrics FROM versionning.model_versions ORDER BY number')).mappings().all()
                self.assertEqual([row['status'] for row in versions], ['ingestion-silver', 'ingestion-bronze'])
                self.assertEqual([row['metrics']['records_inserted'] for row in versions], [4, 4])
                self.assertTrue(connection.scalar(sa.text("SELECT count(*) FROM versionning.version_events WHERE action='status_changed'")))
        finally:
            target.dispose()
        self.assertEqual(self.client.get(f'/api/model-versions/{first_version}/bronze').json()['dataset']['valid'], 4)

    def test_async_execution_is_durable_deduplicated_and_can_resume(self):
        from threading import Event
        from unittest.mock import patch
        from indusense_api.services import bronze_execution
        from indusense_ingestion import bronze_engine as loader
        import time
        self.stage(); self.save()
        body = {'files': [{'id': file['id'], 'revision': file['revision']} for file in self.state()['files']]}
        entered, release = Event(), Event()
        original = loader.load_configuration
        def paused(*args, **kwargs):
            entered.set()
            if not release.wait(10): raise RuntimeError('Test worker timed out')
            return original(*args, **kwargs)
        with patch.object(loader, 'load_configuration', side_effect=paused):
            try:
                response = self.client.post(self.base + '/executions', json=body)
                self.assertEqual(response.status_code, 202, response.text)
                execution_id = response.json()['id']
                self.assertTrue(entered.wait(10))
                duplicate = self.client.post(self.base + '/executions', json=body)
                self.assertEqual(duplicate.json()['id'], execution_id)
                state = self.client.get(self.base + '/executions/current').json()
                self.assertEqual(state['status'], 'RUNNING')
                self.assertIn('Ingestion', state['phase'])
            finally:
                release.set()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                state = self.client.get(self.base + '/executions/current').json()
                if state['status'] in ('SUCCESS', 'FAILED'): break
                time.sleep(.02)
            self.assertEqual(state['status'], 'SUCCESS', state)
        # A process dying after data publication can replay its durable request without duplicates.
        with self.engine.begin() as connection:
            connection.execute(sa.text('SELECT pg_advisory_xact_lock(hashtextextended(:id, 0))'), {'id': 'execution:' + execution_id})
            connection.execute(db.bronze_executions.update().where(db.bronze_executions.c.id == UUID(execution_id)).values(status='RUNNING'))
        bronze_execution.run(self.engine, self.root, UUID(execution_id))
        self.assertEqual(self.client.get(self.base + '/executions/current').json()['status'], 'SUCCESS')
        self.assertEqual(self.state()['dataset']['valid'], 4)
        target = storage.version_engine(self.engine, self.target_name)
        try:
            with target.connect() as connection:
                self.assertEqual(connection.scalar(sa.text('SELECT count(*) FROM versionning.bronze_executions')), 1)
                self.assertEqual(connection.scalar(sa.text('SELECT metrics FROM versionning.model_versions'))['records_inserted'], 4)
        finally:
            target.dispose()

    def test_schema_review_lists_data_and_technical_tables_and_only_reads_bronze(self):
        self.stage(); self.save()
        self.assertEqual(self.client.get(self.base + '/schema').status_code, 409)
        self.assertEqual(self.create().status_code, 200)
        response = self.client.get(self.base + '/schema')
        self.assertEqual(response.status_code, 200, response.text)
        definitions = {table['name']: table for table in response.json()['tables']}
        self.assertEqual(definitions['mesures']['rows'], 4)
        self.assertIn('_ingestion_receipts', definitions)
        self.assertTrue(any(column['name'] == 'value_raw' for column in definitions['mesures']['columns']))
        response = self.client.get(self.base + '/schema/rows', params={'table': 'mesures', 'offset': 1, 'limit': 1})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['rows'][0]['data']['_row_number'], 2)
        self.assertEqual(self.client.get(self.base + '/schema/rows', params={'table': '_ingestion_receipts'}).status_code, 200)
        for table in ('public.alembic_version', 'mesures; DROP SCHEMA bronze CASCADE', '../mesures'):
            self.assertEqual(self.client.get(self.base + '/schema/rows', params={'table': table}).status_code, 404)
        self.assertEqual(self.client.post(self.base + '/schema/rows', json={'table': 'mesures'}).status_code, 405)
        self.assertEqual(self.client.get(self.base + '/schema/rows', params={'table': 'mesures', 'limit': 101}).status_code, 422)

    def test_missing_cast_threshold_defaults_to_zero_and_rolls_back(self):
        self.stage(); self.save(ratio=None)
        response = self.create()
        self.assertEqual(response.status_code, 200, response.text)
        state = response.json()
        self.assertEqual(state['dataset']['valid'], 0)
        self.assertFalse(state['can_validate'])
        self.assertEqual(state['batches'][0]['status'], 'FAILED')
        self.assertEqual(state['batches'][0]['report']['max_cast_error_ratio'], 0.0)
        self.assertNotIn('max_cast_error_ratio', yaml.safe_load(state['files'][0]['saved_yaml']))

    def test_full_reference_datasets_preserve_every_raw_cell_and_replay_without_duplicates(self):
        from indusense_ingestion.cli import configuration
        from indusense_ingestion import bronze_engine as loader
        from indusense_ingestion.bronze_sources import source_spec
        root = Path(__file__).resolve().parents[3]
        configs, recipes, inspector = configuration(root, None)
        storage.create_database(self.engine, self.target_name)
        target = storage.version_engine(self.engine, self.target_name)
        expected = {'telemetry': 135626, 'releves_incidents': 1245, 'machine': 15, 'maintenance': 115}
        total_nulls = 0
        nulls_by_table = {}
        try:
            with target.begin() as connection:
                loader.apply_migration(connection, configs)
            for config, recipe in zip(configs, recipes):
                before_nulls = total_nulls
                report, dictionary = loader.load_configuration(target, inspector, config, recipe)
                self.assertEqual(report['status'], 'SUCCESS', report)
                self.assertEqual(report['records_read'], expected[config['target']['table']])
                self.assertEqual(report['records_inserted'], expected[config['target']['table']])
                self.assertEqual(report['cast_error_rows'], 0)
                table = loader.data_table(config)
                with target.connect().execution_options(stream_results=True) as connection:
                    rows = connection.execute(sa.select(table).order_by(table.c._row_number)).mappings()
                    count = 0
                    for original in inspector.rows(source_spec(config)):
                        row = next(rows)
                        count += 1
                        self.assertEqual(row['_cast_errors'], {})
                        for column in config['columns']:
                            value = original.get(column['source_name'])
                            name = column['target_name']
                            self.assertEqual(row[name + '_raw'], value)
                            self.assertEqual(row[name] is None, value in (None, ''))
                            total_nulls += row[name] is None
                    self.assertEqual(count, expected[table.name])
                    self.assertIsNone(next(rows, None))
                nulls_by_table[table.name] = total_nulls - before_nulls
                replay, _ = loader.load_configuration(target, inspector, config, recipe)
                self.assertEqual((replay['status'], replay['records_inserted']), ('SKIPPED', 0))
                with target.connect() as connection:
                    self.assertEqual(connection.scalar(sa.select(sa.func.count()).select_from(table)), expected[table.name])
            # Les 894 cellules annoncées par le processus concernent temperature_c seule.
            # Comptage indépendant : 2 847 cellules CSV vides + 90 NULL SQL explicites.
            self.assertEqual(nulls_by_table, {'machine': 0, 'maintenance': 90, 'releves_incidents': 0, 'telemetry': 2847})
            self.assertEqual(total_nulls, 2937)
        finally:
            target.dispose()

    def test_review_is_required_and_contract_change_invalidates_approval(self):
        file = self.stage()
        self.assertEqual(self.create().status_code, 422)  # aucune révision sauvegardée
        plan = self.save(approve=False)
        self.assertIn("op.create_table", plan["script"])
        self.assertEqual(self.create().status_code, 409)
        self.assertEqual(self.client.post(self.base + "/migrations/approve", json={"hash": "0" * 64}).status_code, 409)
        self.assertEqual(self.client.post(self.base + "/migrations/approve", json={"hash": plan["hash"]}).status_code, 200)
        file = self.state()["files"][0]
        response = self.client.post(self.base + "/contracts/save", json={"files": [{"id": file["id"], "yaml": file["saved_yaml"] + "\n# nouvelle revue", "revision": file["revision"]}]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(self.state()["approved_hash"])
        self.assertEqual(self.create().status_code, 409)

    def test_existing_versions_are_readonly_and_legacy_write_endpoints_cannot_bypass(self):
        with self.engine.begin() as connection:
            connection.execute(db.model_versions.update().where(db.model_versions.c.id == UUID(self.version)).values(read_only=True))
        self.assertTrue(self.state()["readonly"])
        self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(self.client.post(self.base + "/files", files=[("files", ("x.csv", b"a\n1\n"))], data={"manifest": '[{"dataset_name":"x"}]'}).status_code, 409)
        self.assertEqual(self.client.post(self.base + "/errors/" + str(uuid4()) + "/resolve", json={"action": "discard", "reason": "test"}).status_code, 409)

    def test_contract_v1_and_missing_business_key_are_rejected_before_database_creation(self):
        file = self.stage()
        for text in ("version: 1\ndataset: test\ncolumns: {}", file["loaded_yaml"]):
            response = self.client.post(self.base + "/contracts/save", json={"files": [{"id": file["id"], "yaml": text, "revision": file["revision"]}]})
            self.assertEqual(response.status_code, 422, response.text)
        with self.admin() as admin:
            self.assertIsNone(admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (self.target_name,)).fetchone())

    def test_concurrent_replays_preserve_one_copy_and_trace_each_attempt(self):
        self.stage(); self.save()
        files = self.state()['files']
        body = {'files': [{'id': file['id'], 'revision': file['revision']} for file in files]}
        barrier = Barrier(2)
        def run(_):
            client = TestClient(self.app)
            barrier.wait(timeout=10)
            return client.post(self.base + '/create', json=body)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, range(2)))
        self.assertEqual([response.status_code for response in results], [200, 200])
        state = self.state()
        self.assertEqual(state['dataset']['valid'], 4)
        self.assertEqual(sorted(batch['status'] for batch in state['batches']), ['PARTIAL', 'SKIPPED'])

    def test_sql_source_is_fully_parsed_without_inventing_ddl_defaults(self):
        content = (Path(__file__).resolve().parents[3] / 'datas/machine.sql').read_bytes()
        response = self.client.post(self.base + '/files', files=[('files', ('machine.sql', content))], data={'manifest': '[{"dataset_name":"machines"}]'})
        self.assertEqual(response.status_code, 200, response.text)
        file = self.state()['files'][0]
        self.assertEqual(self.client.post(self.base + '/contracts/load', json={'files': [{'id': file['id'], 'mode': 'generate'}]}).status_code, 200)
        file = self.state()['files'][0]
        configs = yaml.safe_load(file['loaded_yaml'])
        for config in configs:
            config['target']['natural_key'] = ['machine_code'] if config['source']['table'] == 'machine' else ['maintenance_id']
        yaml_text = yaml.safe_dump(configs, sort_keys=False)
        response = self.client.post(self.base + '/contracts/save', json={'files': [{'id': file['id'], 'revision': file['revision'], 'yaml': yaml_text}]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.state()['files'][0]['summary']['rows'], 130)
        generated = self.client.post(self.base + '/identities/generate')
        self.assertEqual(generated.status_code, 200, generated.text)
        self.assertEqual(self.client.post(self.base + '/identities/confirm').status_code, 200)
        plan = self.client.post(self.base + '/migrations/generate').json()
        self.assertEqual(self.client.post(self.base + '/migrations/approve', json={'hash': plan['hash']}).status_code, 200)
        response = self.create()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['dataset']['valid'], 130)
        self.assertTrue(response.json()['can_validate'])
        self.assertEqual({table['name']: table['rows'] for table in response.json()['dataset']['tables']}, {'machine': 15, 'maintenance': 115})
        for table in response.json()['dataset']['tables']:
            self.assertNotIn('created_at', table['columns'])

    def test_local_sql_contracts_load_both_reference_tables(self):
        content = (Path(__file__).resolve().parents[3] / 'datas/machine.sql').read_bytes()
        response = self.client.post(self.base + '/files', files=[('files', ('machine.sql', content))], data={'manifest': '[{"dataset_name":"machines"}]'})
        self.assertEqual(response.status_code, 200, response.text)
        file = self.state()['files'][0]
        self.assertEqual(self.client.get(self.base + '/contracts/catalogue').json(), [])
        directory = (self.root / self.state()['archive_directory']).parent / '_contracts'
        directory.mkdir(parents=True)
        for name in ('machine', 'maintenance'):
            (directory / (name + '.yml')).write_bytes((self.root / 'config/bronze' / (name + '.yml')).read_bytes())
        catalogue = self.client.get(self.base + '/contracts/catalogue').json()
        self.assertEqual({item['label'] for item in catalogue}, {'machine.yml', 'maintenance.yml'})
        response = self.client.post(self.base + '/contracts/load', json={'files': [{'id': file['id'], 'tables': [
            {'table': 'machine', 'mode': 'existing', 'contract': 'local'}, {'table': 'maintenance', 'mode': 'existing', 'contract': 'local'}]}]})
        self.assertEqual(response.status_code, 200, response.text)
        file = self.state()['files'][0]
        configs = yaml.safe_load(file['loaded_yaml'])
        self.assertEqual({config['target']['table'] for config in configs}, {'machine', 'maintenance'})
        response = self.client.post(self.base + '/contracts/save', json={'files': [{'id': file['id'], 'yaml': file['loaded_yaml'], 'revision': file['revision']}]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.state()['files'][0]['summary']['rows'], 130)

    def test_failed_artifact_publication_can_be_recovered_without_reinsertion(self):
        from unittest.mock import patch
        self.stage(); self.save()
        with patch('indusense_ingestion.bronze_engine.write_artifacts', side_effect=OSError('Disque indisponible')):
            # La base et le journal sont durables même si le disque des rapports échoue.
            self.assertEqual(self.create().status_code, 503)
        self.assertFalse(self.state()['can_validate'])
        response = self.create()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['dataset']['valid'], 4)
        self.assertTrue(response.json()['can_validate'])
        self.assertEqual(response.json()['batches'][0]['status'], 'SKIPPED')

    def test_export_preserves_source_bytes_exact_recipes_and_can_be_validated_offline(self):
        import io
        import tempfile
        import zipfile
        from indusense_ingestion.cli import configuration
        self.stage(); self.save()
        response = self.client.get(self.base + '/export')
        self.assertEqual(response.status_code, 200, response.text[:100])
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive, tempfile.TemporaryDirectory() as folder:
            manifest = json.loads(archive.read('manifest.json'))
            for file in manifest['files']:
                self.assertEqual(hashlib.sha256(archive.read(file['path'])).hexdigest(), file['sha256'])
                self.assertEqual(hashlib.sha256(archive.read(file['contract'])).hexdigest(), file['config_hash'])
                self.assertTrue(file['path'].startswith('datas/ingestion/'))
                recipe = yaml.safe_load(archive.read(file['contract']))
                self.assertEqual(recipe['source']['path'], '/' + file['path'])
            archive.extractall(folder)
            configs, _, _ = configuration(Path(folder), None)
            self.assertEqual(len(configs), 1)
