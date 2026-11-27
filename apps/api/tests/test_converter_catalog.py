import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import yaml
from fastapi.testclient import TestClient

from indusense_api.main import create_app
from indusense_ingestion.contracts import CONVERTERS

ROOT = Path(__file__).resolve().parents[3]


class ConverterCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / "config", self.root / "config")
        self.engine = MagicMock()
        self.client = TestClient(create_app(engine=self.engine, resource_root=self.root))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_api_lists_only_runtime_converters_and_their_types_without_database_access(self):
        response = self.client.get("/api/converters")
        self.assertEqual(response.status_code, 200, response.text)
        converters = response.json()["converters"]
        self.assertEqual(set(converters), set(CONVERTERS))
        self.assertEqual(set(converters["datetime"]["types"]), {"DATE", "TIME", "DATETIME", "TIMESTAMP"})
        self.assertIn('TIMESTAMPTZ', converters['datetime_utc']['types'])
        self.assertEqual(set(converters['binary']['types']), {'BINARY'})
        self.assertEqual(converters["datetime"]["types"]["TIME"]["format"], "%H:%M")
        self.engine.connect.assert_not_called()
        self.engine.begin.assert_not_called()

    def test_outdated_catalogue_does_not_expose_an_unavailable_converter(self):
        path = self.root / "config/converters.yaml"
        catalogue = yaml.safe_load(path.read_text())
        catalogue["converters"]["unavailable"] = {"function": "os.system"}
        path.write_text(yaml.safe_dump(catalogue))
        response = self.client.get("/api/converters")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("os.system", response.text)
