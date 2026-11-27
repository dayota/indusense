"""Protection des préparations historiques après le passage au contrat v2."""
from uuid import UUID

from sqlalchemy import select

from test_bronze import PostgresWorkflowCase
from indusense_api import catalog as db


class LegacyPreparationTests(PostgresWorkflowCase):
    def setUp(self):
        super().setUp()
        with self.engine.begin() as connection:
            connection.execute(db.model_versions.update().where(db.model_versions.c.id == UUID(self.version)).values(read_only=True))
            connection.execute(db.preparations.insert().values(model_version_id=UUID(self.version), protocol=1))
        self.base = f'/api/model-versions/{self.version}/bronze'

    def test_old_preparation_is_visible_and_readonly(self):
        response = self.client.get(self.base)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['protocol'], 1)
        self.assertTrue(response.json()['readonly'])

    def test_old_preparation_rejects_every_write_path(self):
        self.assertEqual(self.client.post(self.base + '/identities/confirm').status_code, 409)
        self.assertEqual(self.client.post(self.base + '/migrations/generate').status_code, 409)
        self.assertEqual(self.client.post(f'/api/model-versions/{self.version}/validate-stage', json={'stage': 'bronze'}).status_code, 409)
        self.assertEqual(self.upload().status_code, 409)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(select(db.preparations.c.protocol)), 1)

    def test_new_version_starts_in_v2_without_rewriting_parent(self):
        response = self.client.post(f'/api/models/{self.model["id"]}/versions', json={'from_version_id': self.version, 'preparation': True})
        self.assertEqual(response.status_code, 201, response.text)
        version = response.json()['id']
        new_state = self.client.get(f'/api/model-versions/{version}/bronze').json()
        self.assertEqual(new_state['protocol'], 2)
        self.assertFalse(new_state['readonly'])
        self.assertTrue(self.client.get(self.base).json()['readonly'])
