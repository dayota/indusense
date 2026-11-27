import ast
import copy
import json
import tempfile
import unittest
from jsonschema import Draft202012Validator
from datetime import datetime, timezone
from pathlib import Path

from indusense_ingestion.bronze_contracts import ValidateConfigService
from indusense_ingestion.bronze_sources import FilesystemSourceInspector, source_spec
from indusense_ingestion.bronze_engine import cast, migration_script

ROOT = Path(__file__).resolve().parents[3]


class BronzeContractV2Tests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "data.csv").write_bytes(b'id,value\n001,2\n')
        self.config = {"version": "2.0.0", "kind": "BRONZE", "timezone": "UTC", "source": {"path": "data.csv", "format": "CSV", "encoding": "utf-8", "field_delimiter": ",", "row_delimiter": "\n", "has_header": True},
                       "target": {"schema": "bronze", "table": "data", "natural_key": ["id"]}, "columns": [
                           {"source_name": "id", "target_name": "id", "type": "IDENTIFIER", "silver_type": "TEXT"},
                           {"source_name": "value", "target_name": "value", "type": "NUMBER", "silver_type": "DOUBLE PRECISION", "unit": "HOUR"}], "max_cast_error_ratio": 0.0}
        self.inspector = FilesystemSourceInspector(self.root)
        self.validator = ValidateConfigService(ROOT / 'config/schema/bronze.v2.schema.json', self.inspector)

    def test_complete_config_and_generated_migration_are_valid(self):
        self.assertEqual(self.validator.validate([self.config]), [])
        script = migration_script([self.config])
        ast.parse(script)
        self.assertIn('value_raw', script)
        self.assertIn('_source_hash', script)
        self.assertNotIn('password', script)

    def test_missing_cast_threshold_is_valid_without_mutating_the_recipe(self):
        del self.config['max_cast_error_ratio']
        self.assertEqual(self.validator.validate([self.config]), [])
        self.assertNotIn('max_cast_error_ratio', self.config)

    def test_native_silver_types_parameters_and_arrays_share_one_schema(self):
        schema = json.loads((ROOT / 'config/schema/bronze.v2.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        ref = {'$ref': '#/$defs/postgresql_silver_type'}
        self.assertEqual(schema['properties']['columns']['items']['properties']['silver_type'], ref)
        self.assertEqual(schema['properties']['derived_columns']['items']['properties']['silver_type'], ref)
        validator = Draft202012Validator({**ref, '$defs': schema['$defs']})
        for kind in schema['$defs']['postgresql_native_type']['enum']:
            self.assertTrue(validator.is_valid(kind), kind)
        for kind in ('UUID', 'JSONB', 'INTEGER[][]', 'NUMERIC(6,2)', 'NUMERIC(6, -2)[]',
                     'VARCHAR(32)', 'TIME(6) WITH TIME ZONE', 'TIMESTAMP(3) WITHOUT TIME ZONE[]',
                     'INTERVAL DAY TO SECOND(3)', 'FLOAT(53)', 'INT4MULTIRANGE'):
            self.assertTrue(validator.is_valid(kind), kind)
        for kind in ('', 'public.custom_type', 'VOID', 'NOT_A_TYPE', 'TEXT; DROP TABLE t',
                     'NUMERIC()', 'VARCHAR(0)', 'TIMESTAMP(7)', 'FLOAT(54)', 'SERIAL[]'):
            self.assertFalse(validator.is_valid(kind), kind)

    def test_four_reference_contracts_match_real_sources_and_approved_metadata(self):
        from indusense_ingestion.cli import configuration
        configs, _, _ = configuration(ROOT, None)
        self.assertEqual(len(configs), 4)
        by_table = {config['target']['table']: config for config in configs}
        self.assertEqual({name: config['target']['natural_key'] for name, config in by_table.items()}, {
            'telemetry': ['machine_id', 'timestamp'], 'releves_incidents': ['incident_id'],
            'machine': ['machine_code'], 'maintenance': ['maintenance_id']})
        self.assertTrue(all(config['max_cast_error_ratio'] == 0.0 for config in configs))
        units = {column['source_name']: column.get('unit') for config in configs for column in config['columns']}
        self.assertEqual([units[name] for name in ('pieces_produced', 'severity', 'max_daily_capacity', 'max_hourly_capacity_pieces')],
                         ['PIECE', 'LEVEL', 'PIECE_PER_DAY', 'PIECE_PER_HOUR'])

    def test_validation_aggregates_schema_errors_and_rejects_v1(self):
        config = copy.deepcopy(self.config)
        config['version'], config['timezone'] = 1, 'Europe/Paris'
        del config['source']['encoding']
        del config['columns'][1]['unit']
        self.assertGreaterEqual(len(self.validator.validate([config])), 4)

    def test_semantic_collisions_unknown_inputs_and_business_key_are_aggregated(self):
        config = copy.deepcopy(self.config)
        config['columns'][1]['target_name'] = 'id_raw'
        config['columns'][1]['silver_type'] = 'TIMESTAMP'
        config['target']['natural_key'] = ['ghost']
        config['derived_columns'] = [{'target_name': 'future', 'operation': 'MERGE', 'operate_on_columns': ['id', 'ghost'], 'silver_type': 'TEXT'}]
        issues = self.validator.validate([config, config])
        self.assertGreaterEqual(len(issues), 5)
        self.assertTrue(any('autre configuration' in issue.message for issue in issues))

    def test_csv_inspection_reads_only_header_and_reports_typo(self):
        (self.root / 'data.csv').write_bytes(b'id,value\nmalformed,row,extra\n')
        self.assertEqual(len(self.inspector.inspect(source_spec(self.config)).columns), 2)
        self.config['columns'][1]['source_name'] = 'valu'
        self.assertTrue(any("'value'" in issue.message for issue in self.validator.validate([self.config])))

    def test_absolute_datas_paths_are_portable_and_confined_to_ingestion(self):
        directory = self.root / 'datas/ingestion/model/1/inputs'
        directory.mkdir(parents=True)
        (directory / 'data.csv').write_bytes((self.root / 'data.csv').read_bytes())
        self.config['source']['path'] = '/datas/ingestion/model/1/inputs/data.csv'
        self.assertEqual(self.validator.validate([self.config]), [])
        self.assertEqual(list(self.inspector.rows(source_spec(self.config))), [{'id': '001', 'value': '2'}])
        for wrong in ('/tmp/data.csv', '/datas/ingestion/model/1/../../../../data.csv', '/datas/ingestion/model/1/data.csv', 'datas/ingestion/model/1/data.csv'):
            self.config['source']['path'] = wrong
            self.assertTrue(self.validator.validate([self.config]))
        (directory / 'linked.csv').symlink_to(self.root / 'data.csv')
        self.config['source']['path'] = '/datas/ingestion/model/1/inputs/linked.csv'
        self.assertTrue(self.validator.validate([self.config]))

    def test_sql_ddl_only_columns_and_empty_tables_are_rejected(self):
        (self.root / 'data.sql').write_text("CREATE TABLE t (id TEXT, created_at TEXT DEFAULT 'now'); INSERT INTO t(id) VALUES ('a'),('b'); CREATE TABLE empty (id TEXT);")
        config = copy.deepcopy(self.config)
        config['source'] = {'path': 'data.sql', 'format': 'SQL', 'encoding': 'utf-8', 'table': 't'}
        config['columns'][1] = {'source_name': 'created_at', 'target_name': 'created_at', 'type': 'TEXT', 'silver_type': 'TEXT'}
        self.assertTrue(any('aucun INSERT' in issue.message for issue in self.validator.validate([config])))
        config['source']['table'] = 'empty'
        self.assertTrue(any('aucune donnée' in issue.message for issue in self.validator.validate([config])))

    def test_explicit_encoding_delimiter_and_multiline_cells(self):
        (self.root / 'data.csv').write_bytes('id;value\r\n001;"café\ntexte"\r\n'.encode('cp1252'))
        self.config['source'].update(encoding='cp1252', field_delimiter=';', row_delimiter='\r\n')
        rows = list(self.inspector.rows(source_spec(self.config)))
        self.assertEqual(rows, [{'id': '001', 'value': 'café\ntexte'}])
        self.config['source']['encoding'] = 'utf-8'
        with self.assertRaises(ValueError): list(self.inspector.rows(source_spec(self.config)))

    def test_utc_is_labelled_never_converted_and_blanks_are_not_errors(self):
        self.assertEqual(cast('2025-01-01 10:00:00', 'TIMESTAMPTZ'), datetime(2025, 1, 1, 10, tzinfo=timezone.utc))
        with self.assertRaises(ValueError): cast('2025-01-01T10:00:00+02:00', 'TIMESTAMPTZ')
        self.assertIsNone(cast('', 'NUMBER'))
        with self.assertRaises(ArithmeticError): cast('n/a', 'NUMBER')
