import unittest

from fastapi.testclient import TestClient
from indusense_api.main import create_app


class HealthTests(unittest.TestCase):
    def test_health_and_openapi_have_the_public_prefix(self):
        with TestClient(create_app()) as client:
            self.assertEqual(client.get("/api/health").json()["status"], "ok")
            self.assertIn(
                "/api/health", client.get("/api/openapi.json").json()["paths"]
            )
            self.assertEqual(client.get("/api/docs").status_code, 200)
            self.assertEqual(client.get("/health").status_code, 404)
