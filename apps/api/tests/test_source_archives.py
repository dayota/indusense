"""Historique sur disque : octets inchangés, accès par version et absence d'écrasement."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from sqlalchemy import select

from test_bronze import PostgresWorkflowCase
from indusense_api import catalog as db
from indusense_api.services.bronze_storage import normalized_name


class SourceArchiveTests(PostgresWorkflowCase):
    legacy_fixture = False

    def setUp(self):
        super().setUp()
        self.base = f'/api/model-versions/{self.version}/bronze'
        self.content = b'\xef\xbb\xbfid,value\r\n001,"caf\xc3\xa9\nligne suivante"\r\n'

    def state(self):
        response = self.client.get(self.base)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def stage(self, content=None, filename='source.csv', dataset='source'):
        return self.client.post(self.base + '/files', files=[('files', (filename, self.content if content is None else content))],
            data={'manifest': json.dumps([{'dataset_name': dataset}])})

    def test_upload_archives_exact_bytes_in_model_version_directory_and_can_be_read(self):
        response = self.stage()
        self.assertEqual(response.status_code, 200, response.text)
        state = self.state()
        self.assertEqual(state['archive_directory'], 'datas/ingestion/' + normalized_name('Modèle de test') + '/1')
        archive = state['archives'][0]
        self.assertEqual((self.root / archive['path']).read_bytes(), self.content)
        self.assertEqual(archive['sha256'], hashlib.sha256(self.content).hexdigest())
        self.assertTrue(archive['active'])
        self.assertEqual(self.client.get(self.base + f"/files/{archive['id']}/download").content, self.content)
        preview = self.client.get(self.base + f"/files/{archive['id']}/preview")
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()['content'], self.content.decode('utf-8'))
        self.assertEqual(self.count(db.dataset_versions), 0)

    def test_removal_preserves_history_and_identical_reupload_restores_the_same_archive(self):
        self.assertEqual(self.stage().status_code, 200)
        archive = self.state()['archives'][0]
        self.assertEqual(self.client.delete(self.base + '/files/' + archive['id']).status_code, 200)
        self.assertEqual(self.state()['files'], [])
        self.assertFalse(self.state()['archives'][0]['active'])
        self.assertEqual(self.client.get(self.base + f"/files/{archive['id']}/download").content, self.content)
        self.assertEqual(self.stage(filename='renamed.csv').status_code, 200)
        state = self.state()
        self.assertEqual(len(state['archives']), 1)
        self.assertEqual(state['files'][0]['id'], archive['id'])
        self.assertTrue(state['archives'][0]['active'])
        self.assertEqual(self.count(db.source_archives), 1)

    def test_same_filename_with_new_content_never_overwrites_original(self):
        self.assertEqual(self.stage().status_code, 200)
        archive = self.state()['archives'][0]
        self.client.delete(self.base + '/files/' + archive['id'])
        response = self.stage(content=b'id,value\nchanged,9\n')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual((self.root / archive['path']).read_bytes(), self.content)
        self.assertEqual(self.count(db.preparation_files), 0)

    def test_disk_failure_is_reported_and_does_not_publish_a_successful_upload(self):
        with patch('indusense_api.services.source_archive.version_directory', side_effect=PermissionError('read-only')):
            response = self.stage()
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(self.count(db.preparation_files), 0)
        self.assertEqual(self.count(db.source_archives), 0)

    def test_archive_is_scoped_to_its_version_and_tampering_is_detected(self):
        self.stage()
        archive = self.state()['archives'][0]
        other = self.client.post(f'/api/models/{self.model["id"]}/versions', json={}).json()['id']
        self.assertEqual(self.client.get(f'/api/model-versions/{other}/bronze/files/{archive["id"]}/download').status_code, 404)
        (self.root / archive['path']).write_bytes(b'tampered')
        self.assertEqual(self.client.get(self.base + f"/files/{archive['id']}/preview").status_code, 409)

    def test_symlink_is_refused_and_preview_is_bounded(self):
        self.stage(content=b'x' * (128 * 1024) + b'\xe2\x82\xacend')
        archive = self.state()['archives'][0]
        response = self.client.get(self.base + f"/files/{archive['id']}/preview")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['truncated'])
        path = self.root / archive['path']
        path.unlink()
        path.symlink_to(self.root / 'config/types.yaml')
        self.assertEqual(self.client.get(self.base + f"/files/{archive['id']}/download").status_code, 409)

    def test_inherited_files_are_archived_in_the_new_version_on_next(self):
        self.stage()
        parent_archive = self.state()['archives'][0]
        child = self.client.post(f'/api/models/{self.model["id"]}/versions', json={'from_version_id': self.version, 'preparation': True}).json()['id']
        child_base = f'/api/model-versions/{child}/bronze'
        response = self.client.post(child_base + '/files/archive')
        self.assertEqual(response.status_code, 200, response.text)
        child_archive = self.client.get(child_base).json()['archives'][0]
        self.assertNotEqual(child_archive['path'], parent_archive['path'])
        self.assertIn('modele_de_test/2/', child_archive['path'])
        self.assertEqual((self.root / child_archive['path']).read_bytes(), self.content)
