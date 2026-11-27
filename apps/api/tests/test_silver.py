from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from indusense_api import catalog as db
from indusense_api.main import create_app
from indusense_ingestion.silver import source_hash
from test_bronze import PostgresWorkflowCase

YAML = 'version: 1\ndataset: test\nextra_columns: error\ncolumns:\n  id: {type: IDENTITY}\n  value: {type: INTEGER, nullable: false}\n'


class SilverWorkflowTests(PostgresWorkflowCase):
    def setUp(self):
        super().setUp()
        response = self.upload(b'id,value\n001,2\n002,abc\n003,\n')
        self.assertEqual(response.status_code, 200, response.text)
        self.snapshot = response.json()['results'][0]['snapshot_id']
        self.base = f'/api/model-versions/{self.version}/silver'
        validation = self.client.post(f'/api/model-versions/{self.version}/validate-stage', json={'stage': 'bronze'})
        self.assertEqual(validation.status_code, 200, validation.text)

    def save(self, text=YAML, revision=0):
        response = self.client.post(f'{self.base}/contracts/{self.snapshot}', json={'yaml': text, 'base_revision': revision})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def prepare(self, contract=None):
        contract = contract or self.save()
        response = self.client.post(f'{self.base}/prepare/{self.snapshot}', json={'contract_id': contract['id']})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def issues(self):
        return self.client.get(f'{self.base}/quarantine').json()['rows']

    def status(self, status):
        return self.client.patch(f'/api/model-versions/{self.version}/status', json={'status': status})

    def validate_silver(self):
        return self.client.post(f'/api/model-versions/{self.version}/validate-stage', json={'stage': 'silver'})

    def resolve(self, issue, action='discard', values=None, client=None):
        return (client or self.client).post(f'{self.base}/quarantine/{issue["id"]}/resolve',
                                           json={'action': action, 'values': values, 'reason': 'Décision humaine de test'})

    def test_valid_rows_quarantined_rows_and_source_hash(self):
        run = self.prepare()
        self.assertEqual(self.count(db.rows), 3)
        self.assertEqual(self.count(db.silver_rows), 1)
        self.assertEqual(len(self.issues()), 2)
        output = self.client.get(f'{self.base}/runs/{run["id"]}/rows').json()['rows'][0]['data']
        self.assertEqual(output['hash'], source_hash({'id': '001', 'value': '2'}))
        self.assertEqual(output['value__type'], 'INTEGER')
        self.assertEqual(output['value'], 2)
        self.assertEqual(self.client.get(f'/api/model-versions/{self.version}').json()['status'], 'ingestion-silver')

    def test_no_later_status_can_bypass_pending_errors_even_via_bronze(self):
        self.prepare()
        for status in ('ingestion-gold', 'training', 'challenger', 'champion'):
            self.assertEqual(self.status(status).status_code, 405)
        self.assertEqual(self.status('ingestion-bronze').status_code, 405)
        self.assertEqual(self.validate_silver().status_code, 409)
        for issue in self.issues():
            self.assertTrue(self.resolve(issue).json()['resolved'])
        self.assertTrue(self.client.get(self.base).json()['can_advance'])
        self.assertEqual(self.validate_silver().status_code, 200)

    def test_invalid_correction_remains_pending_and_valid_correction_is_revalidated(self):
        run = self.prepare()
        issue = self.issues()[0]
        invalid = self.resolve(issue, 'reintegrate', {'value': 'still-invalid'})
        self.assertFalse(invalid.json()['resolved'])
        self.assertEqual(len(self.issues()), 2)
        valid = self.resolve(issue, 'reintegrate', {'value': '17'})
        self.assertTrue(valid.json()['resolved'], valid.text)
        rows = self.client.get(f'{self.base}/runs/{run["id"]}/rows').json()['rows']
        corrected = next(row['data'] for row in rows if row['row_number'] == issue['row_number'])
        self.assertEqual(corrected['value'], 17)
        self.assertEqual(corrected['hash'], source_hash(issue['source']))
        self.assertEqual(self.resolve(issue).status_code, 409)
        with self.engine.connect() as connection:
            source = connection.scalar(select(db.rows.c.data).where(db.rows.c.dataset_version_id == UUID(self.snapshot), db.rows.c.row_number == issue['row_number']))
        self.assertEqual(source, issue['source'])

    def test_validation_revisions_and_optimistic_lock(self):
        draft = self.client.get(f'{self.base}/contracts/{self.snapshot}').json()
        self.assertIn('INTEGER', draft['yaml'])
        self.assertEqual(draft['revisions'], [])
        validation = self.client.post(f'{self.base}/contracts/{self.snapshot}/validate', json={'yaml': YAML})
        self.assertEqual(validation.status_code, 200, validation.text)
        self.assertEqual(self.count(db.silver_contracts), 0)
        first = self.save()
        stale = self.client.post(f'{self.base}/contracts/{self.snapshot}', json={'yaml': YAML + '# change\n'})
        self.assertEqual(stale.status_code, 409)
        second = self.save(YAML + '# change\n', 1)
        self.assertEqual(second['number'], 2)
        self.assertNotEqual(first['id'], second['id'])
        invalid = self.client.post(f'{self.base}/contracts/{self.snapshot}/validate', json={'yaml': YAML + 'unknown: bad'})
        self.assertEqual(invalid.status_code, 422)

    def test_other_model_version_cannot_access_or_resolve_rows(self):
        run = self.prepare()
        other = self.client.post('/api/models', json={'name': 'other'}).json()['version_id']
        base = f'/api/model-versions/{other}/silver'
        self.assertEqual(self.client.get(f'{base}/contracts/{self.snapshot}').status_code, 404)
        self.assertEqual(self.client.get(f'{base}/runs/{run["id"]}/rows').status_code, 404)
        self.assertEqual(self.client.post(f'{base}/quarantine/{self.issues()[0]["id"]}/resolve', json={'action': 'discard', 'reason': 'test'}).status_code, 404)

    def test_rerun_cannot_hide_pending_and_preserves_discard_and_correction(self):
        contract = self.save()
        self.prepare(contract)
        second = self.save(YAML + '# revision 2', 1)
        self.assertEqual(self.client.post(f'{self.base}/prepare/{self.snapshot}', json={'contract_id': second['id']}).status_code, 409)
        issues = self.issues()
        self.resolve(issues[0], 'reintegrate', {'value': '42'})
        self.resolve(issues[1])
        run = self.prepare(second)
        self.assertEqual(run['contract_id'], second['id'])
        rows = self.client.get(f'{self.base}/runs/{run["id"]}/rows').json()['rows']
        self.assertEqual(len(rows), 2)
        self.assertEqual(self.client.get(self.base).json()['pending'], 0)
        self.assertIn(42, [row['data']['value'] for row in rows])

    def test_simultaneous_resolutions_insert_one_row(self):
        self.prepare()
        issue = self.issues()[0]
        barrier = Barrier(2)
        def send(index):
            with TestClient(create_app(engine=self.engine, resource_root=self.root)) as client:
                barrier.wait(timeout=10)
                return self.resolve(issue, 'reintegrate', {'value': '7'}, client)
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(send, range(2)))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409], [r.text for r in responses])
        self.assertEqual(self.count(db.silver_rows), 2)

    def test_new_contract_blocks_progress_until_prepared_and_same_run_is_idempotent(self):
        contract = self.save()
        run = self.prepare(contract)
        self.assertEqual(self.prepare(contract)['id'], run['id'])
        for issue in self.issues():
            self.resolve(issue)
        self.save(YAML + '# new', 1)
        self.assertEqual(self.validate_silver().status_code, 409)
