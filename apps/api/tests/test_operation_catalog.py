"""Catalogue disponible sans requête SQL, et erreurs de configuration explicites."""
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from indusense_api.main import create_app

ROOT = Path(__file__).resolve().parents[3]


class OperationCatalogTests(unittest.TestCase):
    def test_catalog_resolves_all_schema_operations_without_database(self):
        with TestClient(create_app(engine=object(), resource_root=ROOT)) as client:
            response = client.get('/api/operations')
        self.assertEqual(response.status_code, 200, response.text)
        schema = json.loads((ROOT / 'config/schema/bronze.v2.schema.json').read_text())
        self.assertEqual(set(response.json()['operations']), set(schema['properties']['derived_columns']['items']['properties']['operation']['enum']))
        self.assertEqual(response.json()['operations']['ANO']['slug'], 'pseudonymize')

    def test_missing_or_invalid_catalog_returns_service_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config/schema').mkdir(parents=True)
            (root / 'config/types.yaml').write_text('version: 1')
            (root / 'config/schema/bronze.v2.schema.json').write_bytes((ROOT / 'config/schema/bronze.v2.schema.json').read_bytes())
            with TestClient(create_app(engine=object(), resource_root=root)) as client:
                self.assertEqual(client.get('/api/operations').status_code, 503)
                (root / 'config/operations.yaml').write_text('version: 1\noperations:\n  ANO: {slug: os.system}\n')
                self.assertEqual(client.get('/api/operations').status_code, 503)
