import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from indusense_api.main import create_app


class MonitoringTests(unittest.TestCase):
    def test_readiness_checks_the_database_and_hides_connection_errors(self):
        engine = MagicMock()
        with TestClient(create_app(engine=engine)) as client:
            self.assertEqual(client.get("/api/ready").json()["database"], "ok")
            engine.connect.return_value.__enter__.return_value.execute.assert_called_once()
            engine.connect.side_effect = OperationalError(
                "secret connection string", {}, Exception()
            )
            response = client.get("/api/ready")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("secret", response.text)
            self.assertEqual(client.get("/api/health").status_code, 200)

    def test_metrics_use_route_templates_and_isolated_registries(self):
        for _ in range(2):
            with TestClient(create_app(engine=MagicMock())) as client:
                client.get("/api/health")
                client.get("/api/unknown-123")
                metrics = client.get("/api/metrics")
                self.assertIn('route="/api/health",status="200"', metrics.text)
                self.assertIn('route="unmatched",status="404"', metrics.text)
                self.assertNotIn("unknown-123", metrics.text)
                self.assertIn("indusense_http_request_duration_seconds", metrics.text)
