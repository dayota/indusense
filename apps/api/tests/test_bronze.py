"""Tests transactionnels sur une base PostgreSQL temporaire, sans toucher aux datasets locaux."""

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select

from indusense_api import catalog as db
from indusense_api.database import database_url
from indusense_api.main import create_app

ROOT = Path(__file__).resolve().parents[3]
CSV = b"id,value\n001,2\n001,2\n"


@unittest.skipUnless(
    os.environ.get("INDUSENSE_POSTGRES_TESTS") == "1",
    "Activer INDUSENSE_POSTGRES_TESTS=1 pour les tests PostgreSQL",
)
class PostgresWorkflowCase(unittest.TestCase):
    # Ces scénarios couvrent le moteur historique conservé pour lire les anciens snapshots.
    # La création publique initialise désormais toujours une préparation v2.
    legacy_fixture = True
    @classmethod
    def setUpClass(cls):
        cls.name = "indusense_test_" + uuid4().hex[:12]
        cls.url = database_url()
        cls.engine = create_engine(cls.url.set(database=cls.name))
        with cls.admin() as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.name))
            )
        cls.addClassCleanup(cls.remove_database)
        with patch.dict(os.environ, {"DB_NAME": cls.name}):
            command.upgrade(Config(str(ROOT / "apps/api/alembic.ini")), "head")

    @classmethod
    def admin(cls):
        return psycopg.connect(
            host=cls.url.host,
            port=cls.url.port,
            user=cls.url.username,
            password=cls.url.password,
            dbname="postgres",
            autocommit=True,
        )

    @classmethod
    def remove_database(cls):
        cls.engine.dispose()
        with cls.admin() as admin:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(cls.name)))

    def setUp(self):
        with self.engine.begin() as connection:
            for table in reversed(db.metadata.sorted_tables):
                connection.execute(table.delete())
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / "config", self.root / "config")
        (self.root / "config/contracts/test.yaml").write_text(
            "version: 1\ndataset: test\nextra_columns: error\ncolumns:\n  id: {type: IDENTITY}\n  value: {type: INTEGER}\n"
        )
        self.app = create_app(engine=self.engine, resource_root=self.root)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        response = self.client.post("/api/models", json={"name": "Modèle de test"})
        self.assertEqual(response.status_code, 201, response.text)
        self.model = response.json()
        self.version = self.model["version_id"]
        if self.legacy_fixture:
            with self.engine.begin() as connection:
                connection.execute(db.preparations.delete().where(db.preparations.c.model_version_id == self.version))

    def count(self, table):
        with self.engine.connect() as connection:
            return connection.scalar(select(func.count()).select_from(table))

    def upload(
        self,
        content=CSV,
        name="first.csv",
        dataset="mesures",
        version=None,
        client=None,
        contract="test",
        checksum=None,
    ):
        manifest = {"dataset_name": dataset, "contract": contract, "mode": "snapshot"}
        if checksum is not None:
            manifest["sha256"] = checksum
        return (client or self.client).post(
            f"/api/model-versions/{version or self.version}/uploads",
            files=[("files", (name, content))],
            data={"manifest": json.dumps([manifest])},
        )


class BronzeTests(PostgresWorkflowCase):
    def test_migration_creates_three_schemas_and_matches_the_catalog(self):
        inspector = inspect(self.engine)
        self.assertTrue(
            {"bronze", "silver", "gold"} <= set(inspector.get_schema_names())
        )
        self.assertEqual(set(inspector.get_table_names(schema="silver")), {"contracts", "runs", "rows", "quarantine"})
        for table in db.metadata.tables.values():
            self.assertEqual(
                {c.name for c in table.columns},
                {c["name"] for c in inspector.get_columns(table.name, schema=table.schema)},
            )
        constraints = inspector.get_unique_constraints(
            "dataset_versions", schema="bronze"
        )
        self.assertIn(
            {"dataset_id", "source_id"}, [set(c["column_names"]) for c in constraints]
        )

    def test_raw_rows_identity_and_original_bytes_are_preserved(self):
        response = self.upload(checksum=hashlib.sha256(CSV).hexdigest())
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["results"][0]
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["summary"]["duplicate_rows"], 1)
        rows = self.client.get(
            f"/api/dataset-versions/{result['snapshot_id']}/rows"
        ).json()["rows"]
        self.assertEqual([r["data"] for r in rows], [{"id": "001", "value": "2"}] * 2)
        report = self.client.get(
            f"/api/dataset-versions/{result['snapshot_id']}/report"
        )
        self.assertIn("| id | IDENTITY |", report.text)
        self.assertIn("- Source: first.csv", report.text)
        self.assertNotIn(self.temp.name, report.text)
        with self.engine.connect() as connection:
            self.assertEqual(
                bytes(connection.scalar(select(db.sources.c.content))), CSV
            )

    def test_renamed_duplicate_does_not_duplicate_data(self):
        first = self.upload().json()["results"][0]
        again = self.upload(name="renamed.csv").json()["results"][0]
        self.assertEqual(again["status"], "duplicate")
        self.assertEqual(first["snapshot_id"], again["snapshot_id"])
        self.assertEqual(
            (
                self.count(db.sources),
                self.count(db.dataset_versions),
                self.count(db.rows),
            ),
            (1, 1, 2),
        )
        events = self.client.get(f"/api/model-versions/{self.version}").json()[
            "history"
        ]
        self.assertEqual(events[0]["action"], "upload_duplicate")

    def test_new_complete_snapshot_does_not_append_to_old_rows(self):
        first = self.upload().json()["results"][0]
        second = self.upload(b"id,value\n002,3\n").json()["results"][0]
        self.assertEqual((first["number"], second["number"]), (1, 2))
        for result, length in ((first, 2), (second, 1)):
            self.assertEqual(
                len(
                    self.client.get(
                        f"/api/dataset-versions/{result['snapshot_id']}/rows"
                    ).json()["rows"]
                ),
                length,
            )
        versions = self.client.get(f"/api/datasets/{first['dataset_id']}").json()[
            "versions"
        ]
        self.assertEqual([v["number"] for v in versions], [2, 1])

    def test_model_versions_reuse_snapshots_without_copying_rows(self):
        first = self.upload().json()["results"][0]
        version = self.client.post(
            f"/api/models/{self.model['id']}/versions",
            json={"from_version_id": self.version},
        ).json()
        detail = self.client.get(f"/api/model-versions/{version['id']}").json()
        self.assertEqual(detail["datasets"][0]["snapshot_id"], first["snapshot_id"])
        self.assertEqual(self.upload(b"id,value\n002,3\n", version=version["id"]).status_code, 409)
        old = self.client.get(f"/api/model-versions/{self.version}").json()
        self.assertEqual(old["datasets"][0]["snapshot_id"], first["snapshot_id"])
        self.assertEqual(self.count(db.rows), 2)

    def test_existing_snapshot_can_be_attached_to_an_empty_model_version(self):
        first = self.upload().json()["results"][0]
        version = self.client.post(
            f"/api/models/{self.model['id']}/versions", json={}
        ).json()
        self.assertEqual(self.upload(version=version["id"]).status_code, 409)
        detail = self.client.get(f"/api/model-versions/{version['id']}").json()
        self.assertEqual(detail["preparation"]["state"], "draft")
        self.assertEqual(self.count(db.rows), 2)

    def test_duplicate_files_within_one_batch(self):
        response = self.client.post(
            f"/api/model-versions/{self.version}/uploads",
            files=[("files", ("a.csv", CSV)), ("files", ("b.csv", CSV))],
            data={
                "manifest": json.dumps(
                    [{"dataset_name": "mesures", "contract": "test"}] * 2
                )
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            [r["status"] for r in response.json()["results"]], ["created", "duplicate"]
        )
        self.assertEqual(self.count(db.rows), 2)

    def test_mixed_csv_and_sql_batch_has_independent_contracts(self):
        response = self.client.post(
            f"/api/model-versions/{self.version}/uploads",
            files=[
                ("files", ("mesures.csv", CSV)),
                (
                    "files",
                    (
                        "machines.sql",
                        b"CREATE TABLE machine (id INTEGER); INSERT INTO machine VALUES (7);",
                    ),
                ),
            ],
            data={
                "manifest": json.dumps(
                    [
                        {"dataset_name": "mesures", "contract": "test"},
                        {"dataset_name": "machines"},
                    ]
                )
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            [r["summary"]["rows"] for r in response.json()["results"]], [2, 1]
        )
        detail = self.client.get(f"/api/model-versions/{self.version}").json()
        self.assertEqual(
            {d["name"] for d in detail["datasets"]}, {"mesures", "machines"}
        )

    def test_batch_failure_rolls_back_all_sources_snapshots_and_rows(self):
        response = self.client.post(
            f"/api/model-versions/{self.version}/uploads",
            files=[
                ("files", ("good.csv", CSV)),
                ("files", ("bad.csv", b"wrong,headers\na,b\n")),
            ],
            data={
                "manifest": json.dumps(
                    [
                        {"dataset_name": "good", "contract": "test"},
                        {"dataset_name": "bad", "contract": "test"},
                    ]
                )
            },
        )
        self.assertEqual(response.status_code, 422, response.text)
        for table in (db.sources, db.dataset_versions, db.rows, db.datasets):
            self.assertEqual(self.count(table), 0)
        self.assertEqual(
            self.client.get(f"/api/model-versions/{self.version}").json()["history"][0][
                "action"
            ],
            "upload_rejected",
        )

    def test_bad_checksums_empty_files_paths_and_limits_do_not_load_data(self):
        for kwargs in (
            {"checksum": "0" * 64},
            {"content": b""},
            {"name": "../escape.csv"},
            {"name": "data.json"},
            {"contract": None},
        ):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.upload(**kwargs).status_code, 422)
        with patch("indusense_api.services.analysis.MAX_FILE_BYTES", 4):
            self.assertEqual(self.upload().status_code, 413)
        self.assertEqual(self.count(db.sources), 0)

    def test_sql_is_parsed_into_raw_tables_without_execution(self):
        content = b"CREATE TABLE machine_test (id INTEGER PRIMARY KEY, label TEXT, at TIMESTAMPTZ DEFAULT NOW()); INSERT INTO machine_test (id, label) VALUES (1, 'hello');"
        response = self.upload(content, "machines.sql", contract=None)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["results"][0]
        rows = self.client.get(
            f"/api/dataset-versions/{result['snapshot_id']}/rows?table=machine_test"
        ).json()["rows"]
        self.assertEqual(rows[0]["data"], {"id": "1", "label": "hello"})
        self.assertFalse(inspect(self.engine).has_table("machine_test"))
        invalid = self.upload(
            content + b" DROP TABLE bronze.models;", "bad.sql", contract=None
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(self.count(db.models), 1)

    def test_simultaneous_uploads_create_one_snapshot(self):
        barrier = Barrier(2)

        def send(index):
            with TestClient(
                create_app(engine=self.engine, resource_root=self.root)
            ) as client:
                barrier.wait(timeout=10)
                return self.upload(client=client, name=f"copy-{index}.csv")

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(send, range(2)))
        self.assertEqual(
            [r.status_code for r in responses], [200, 200], [r.text for r in responses]
        )
        self.assertEqual(
            sorted(r.json()["results"][0]["status"] for r in responses),
            ["created", "duplicate"],
        )
        self.assertEqual(
            (
                self.count(db.sources),
                self.count(db.dataset_versions),
                self.count(db.rows),
            ),
            (1, 1, 2),
        )

    def test_large_csv_passes_the_upload_route_limit(self):
        # Dépasser la limite JSON globale de 1 Mio vérifie l’héritage du seuil multipart.
        content = b"id,value\n" + b"001,2\n" * 180000
        response = self.upload(content)
        self.assertEqual(response.status_code, 200, response.text[:400])
        self.assertEqual(response.json()["results"][0]["summary"]["rows"], 180000)
