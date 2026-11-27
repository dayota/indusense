import hashlib
import json
from uuid import UUID, uuid4

import yaml
from sqlalchemy import select

from indusense_api import catalog as db
from test_bronze import PostgresWorkflowCase, CSV


class PreloadTests(PostgresWorkflowCase):
    def send(self, route, entries, files=None, version=None):
        return self.client.post(
            f'/api/model-versions/{version or self.version}/{route}',
            files=files or [('files', ('mesures.csv', CSV))],
            data={'manifest': json.dumps(entries)},
        )

    def generated(self, content=CSV, dataset='mesures'):
        response = self.send('preload', [{'dataset_name': dataset, 'contract_mode': 'generate'}],
                             [('files', ('mesures.csv', content))])
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['results'][0]

    def test_generated_contract_uses_existing_inference_and_preload_writes_nothing(self):
        before = {table.fullname: self.count(table) for table in db.metadata.sorted_tables}
        content = b'machine_id,value,day,comment\n001,2,2026-11-26,hello\n002,3,2026-11-27,world\n'
        result = self.generated(content)
        contract = yaml.safe_load(result['contract_yaml'])
        self.assertEqual({name: spec['type'] for name, spec in contract['columns'].items()},
                         {'machine_id': 'IDENTITY', 'value': 'INTEGER', 'day': 'DATE', 'comment': 'TEXT'})
        self.assertEqual(result['sha256'], hashlib.sha256(content).hexdigest())
        self.assertEqual(result['summary']['rows'], 2)
        self.assertEqual({table.fullname: self.count(table) for table in db.metadata.sorted_tables}, before)
        self.assertFalse((self.root / 'artifacts').exists())

    def test_existing_contract_can_be_edited_before_loading_and_raw_values_stay_preserved(self):
        response = self.send('preload', [{'dataset_name': 'mesures', 'contract': 'test'}])
        self.assertEqual(response.status_code, 200, response.text)
        proposed = response.json()['results'][0]
        edited = proposed['contract_yaml'].replace('INTEGER', 'TEXT')
        loaded = self.send('uploads', [{'dataset_name': 'mesures', 'contract': 'test', 'contract_yaml': edited, 'sha256': proposed['sha256']}])
        self.assertEqual(loaded.status_code, 200, loaded.text)
        result = loaded.json()['results'][0]
        self.assertEqual(result['summary']['tables'][0]['columns'][1]['type'], 'TEXT')
        with self.engine.connect() as connection:
            snapshot = connection.execute(select(db.dataset_versions)).mappings().one()
            rows = list(connection.scalars(select(db.rows.c.data)))
        self.assertEqual(snapshot['contract']['columns']['value']['type'], 'TEXT')
        self.assertEqual(rows, [{'id': '001', 'value': '2'}] * 2)

    def test_multiple_files_keep_independent_contracts_and_sql_has_no_csv_contract(self):
        files = [('files', ('first.csv', CSV)), ('files', ('second.csv', b'label,price\nitem,1.5\n')),
                 ('files', ('machines.sql', b'CREATE TABLE machine (id INTEGER); INSERT INTO machine VALUES (7);'))]
        entries = [{'dataset_name': 'first', 'contract': 'test'}, {'dataset_name': 'second', 'contract_mode': 'generate'},
                   {'dataset_name': 'third'}]
        response = self.send('preload', entries, files)
        self.assertEqual(response.status_code, 200, response.text)
        results = response.json()['results']
        self.assertEqual([result['filename'] for result in results], ['first.csv', 'second.csv', 'machines.sql'])
        self.assertIsNone(results[2]['contract_yaml'])
        for entry, result in zip(entries, results):
            entry.update(contract_yaml=result['contract_yaml'], sha256=result['sha256'])
        entries[1]['contract_yaml'] = entries[1]['contract_yaml'].replace('FLOAT', 'DECIMAL')
        loaded = self.send('uploads', entries, files)
        self.assertEqual(loaded.status_code, 200, loaded.text)
        self.assertEqual([result['summary']['tables'][0]['columns'][-1]['type'] for result in loaded.json()['results']],
                         ['INTEGER', 'DECIMAL', 'INTEGER'])

    def test_generated_contract_becomes_reusable_after_load(self):
        proposed = self.generated()
        self.assertFalse(any(option['value'].startswith('snapshot:') for option in self.client.get('/api/contracts/catalogue').json()))
        entry = {'dataset_name': 'mesures', 'contract_mode': 'generate', 'contract_yaml': proposed['contract_yaml']}
        loaded = self.send('uploads', [entry])
        self.assertEqual(loaded.status_code, 200, loaded.text)
        snapshot_id = loaded.json()['results'][0]['snapshot_id']
        options = self.client.get('/api/contracts/catalogue').json()
        self.assertIn('snapshot:' + snapshot_id, [option['value'] for option in options])
        reused = self.send('preload', [{'dataset_name': 'other', 'contract': 'snapshot:' + snapshot_id}])
        self.assertEqual(reused.status_code, 200, reused.text)
        self.assertEqual(yaml.safe_load(reused.json()['results'][0]['contract_yaml']), yaml.safe_load(proposed['contract_yaml']))

    def test_final_load_requires_generated_contract_and_checks_original_digest(self):
        self.assertEqual(self.send('uploads', [{'dataset_name': 'mesures', 'contract_mode': 'generate'}]).status_code, 422)
        proposed = self.generated()
        entry = {'dataset_name': 'mesures', 'contract_mode': 'generate', 'contract_yaml': proposed['contract_yaml'], 'sha256': proposed['sha256']}
        altered = self.send('uploads', [entry], [('files', ('mesures.csv', b'id,value\n001,9\n'))])
        self.assertEqual(altered.status_code, 422)
        self.assertEqual(self.count(db.rows), 0)

    def test_identical_file_and_contract_reuse_snapshot_but_changed_contract_conflicts(self):
        proposed = self.generated()
        entry = {'dataset_name': 'mesures', 'contract_mode': 'generate', 'contract_yaml': proposed['contract_yaml']}
        self.assertEqual(self.send('uploads', [entry]).json()['results'][0]['status'], 'created')
        self.assertEqual(self.send('uploads', [entry]).json()['results'][0]['status'], 'duplicate')
        entry['contract_yaml'] = entry['contract_yaml'].replace('INTEGER', 'TEXT')
        response = self.send('uploads', [entry])
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.count(db.dataset_versions), 1)
        self.assertEqual(self.count(db.rows), 2)

    def test_invalid_yaml_edited_columns_and_unsafe_tags_are_rejected_atomically(self):
        good = self.generated()['contract_yaml']
        for text in ('version: 1\ndataset: test\ncolumns: {id: {type: UNKNOWN}}',
                     good + '\nversion: 1', '!!python/object/apply:os.system [echo bad]',
                     good.replace('  value:', '  absent:'), good + '\nunknown: true'):
            with self.subTest(text=text):
                response = self.send('uploads', [{'dataset_name': 'good', 'contract_yaml': good},
                                                 {'dataset_name': 'bad', 'contract_yaml': text}],
                                     [('files', ('good.csv', CSV)), ('files', ('bad.csv', CSV))])
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(self.count(db.datasets), 0)
                self.assertEqual(self.count(db.rows), 0)

    def test_invalid_headers_unknown_version_and_manifest_are_rejected_without_data(self):
        self.assertEqual(self.send('preload', [{'dataset_name': 'x', 'contract_mode': 'generate'}],
                                   [('files', ('duplicate.csv', b'id,id\n1,2\n'))]).status_code, 422)
        self.assertEqual(self.send('preload', [], version=uuid4()).status_code, 422)
        self.assertEqual(self.send('preload', [{'dataset_name': 'x', 'contract_mode': 'generate'}], version=uuid4()).status_code, 404)
        self.assertEqual(self.count(db.datasets), 0)
        self.assertEqual(self.count(db.rows), 0)

    def test_large_edited_contract_is_not_rejected_by_old_multipart_text_limit(self):
        proposed = self.generated()
        contract = proposed['contract_yaml'] + '\n# ' + 'x' * 20000
        response = self.send('uploads', [{'dataset_name': 'mesures', 'contract_mode': 'generate', 'contract_yaml': contract}])
        self.assertEqual(response.status_code, 200, response.text)
