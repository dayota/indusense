"""Contrôles HTTP optionnels de la stack locale déjà démarrée."""

import json
import os
import unittest
from urllib.request import urlopen


@unittest.skipUnless(os.environ.get("INDUSENSE_TEST_URL"), "Définir INDUSENSE_TEST_URL pour tester Docker/Traefik")
class LocalStackTests(unittest.TestCase):
    def get(self, path):
        with urlopen(os.environ["INDUSENSE_TEST_URL"].rstrip("/") + path, timeout=15) as response:
            self.assertEqual(response.status, 200)
            return response.read().decode()

    def test_ui_uses_the_api_during_server_rendering(self):
        self.assertIn("API : disponible", self.get("/"))

    def test_api_database_docs_and_metrics_are_routed(self):
        self.assertEqual(json.loads(self.get("/api/health"))["status"], "ok")
        self.assertEqual(json.loads(self.get("/api/ready"))["database"], "ok")
        self.assertIn("/api/ready", json.loads(self.get("/api/openapi.json"))["paths"])
        self.assertIn("/api/openapi.json", self.get("/api/docs"))
        self.assertIn("indusense_http_requests_total", self.get("/api/metrics"))
