import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from indusense_ingestion.paths import project_root, types_catalog


class ResourcePathTests(unittest.TestCase):
    def test_explicit_paths_work_without_a_repository_next_to_the_package(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.dict(os.environ, {"INDUSENSE_PROJECT_ROOT": folder}):
                self.assertEqual(project_root(), root.resolve())
                self.assertEqual(types_catalog(), root.resolve() / "config/types.yaml")
                self.assertEqual(project_root(root / "outputs"), root / "outputs")
                self.assertEqual(types_catalog(root / "custom.yaml"), root / "custom.yaml")
