import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import yaml
from pandas.testing import assert_frame_equal

from indusense_ingestion.operations import apply_operation, fit_operation, operation_catalog

ROOT = Path(__file__).resolve().parents[3]


def specification(code, parameters, columns=None, target='result'):
    return {'operation': code, 'parameters': parameters, 'operate_on_columns': columns or ['value'],
            'target_name': target, 'silver_type': 'DOUBLE PRECISION'}


class OperationTests(unittest.TestCase):
    def fit(self, frame, spec):
        return fit_operation(frame, spec, root=ROOT)

    def apply(self, frame, state, **kwargs):
        return apply_operation(frame, json.loads(json.dumps(state)), root=ROOT, **kwargs)

    def test_catalog_matches_schema_and_functions_and_rejects_dynamic_imports(self):
        result = operation_catalog(ROOT)
        schema = json.loads((ROOT / 'config/schema/bronze.v2.schema.json').read_text())
        self.assertEqual(set(result['operations']), set(schema['properties']['derived_columns']['items']['properties']['operation']['enum']))
        self.assertTrue(all(value['function'].startswith('indusense_ingestion.operation_methods.') for value in result['operations'].values()))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config/schema').mkdir(parents=True)
            (root / 'config/types.yaml').write_text('version: 1')
            (root / 'config/schema/bronze.v2.schema.json').write_text(json.dumps(schema))
            catalog = yaml.safe_load((ROOT / 'config/operations.yaml').read_text())
            catalog['operations']['ANO']['slug'] = 'os.system'
            (root / 'config/operations.yaml').write_text(yaml.safe_dump(catalog))
            with self.assertRaisesRegex(ValueError, 'Slug'):
                operation_catalog(root)

    def test_min_max_reuses_training_parameters_without_mutating_sources(self):
        train = pd.DataFrame({'value': [0., 10., None]})
        original = train.copy(deep=True)
        state = self.fit(train, specification('NORM', {'method': 'min-max'}))
        assert_frame_equal(train, original)
        test = pd.DataFrame({'value': [20., None]})
        output = self.apply(test, state)
        self.assertEqual(output.result.iloc[0], 2.)  # Pas de clipping ni de fit sur le test.
        self.assertTrue(pd.isna(output.result.iloc[1]))
        self.assertEqual(state['learned']['[]'], {'minimum': 0., 'maximum': 10.})
        self.assertNotIn('result', test)

    def test_standardize_requires_explicit_ddof_and_preserves_training_mean(self):
        train = pd.DataFrame({'value': [0., 2.]})
        spec = specification('STD', {'method': 'z-score', 'ddof': 0})
        output = self.apply(pd.DataFrame({'value': [3.]}), self.fit(train, spec))
        self.assertEqual(output.result.iloc[0], 2.)
        del spec['parameters']['ddof']
        with self.assertRaisesRegex(ValueError, 'ddof'):
            self.fit(train, spec)

    def test_group_statistics_do_not_mix_groups_or_learn_new_ones(self):
        train = pd.DataFrame({'group': ['a', 'a', 'b', 'b'], 'value': [0., 2., 10., 20.]})
        state = self.fit(train, specification('NORM', {'method': 'min-max', 'group_by': ['group']}))
        output = self.apply(pd.DataFrame({'group': ['a', 'b'], 'value': [1., 15.]}), state)
        self.assertEqual(output.result.tolist(), [.5, .5])
        with self.assertRaisesRegex(ValueError, 'Groupe absent'):
            self.apply(pd.DataFrame({'group': ['c'], 'value': [1.]}), state)

    def test_zero_variance_missing_numeric_and_nonfinite_fail_explicitly(self):
        for code, parameters in [('NORM', {'method': 'min-max'}), ('STD', {'method': 'z-score', 'ddof': 0}),
                                 ('OUT', {'method': 'mad', 'threshold': 3.})]:
            with self.subTest(code=code), self.assertRaises(ValueError):
                self.fit(pd.DataFrame({'value': [1., 1.]}), specification(code, parameters))
        for values in ([None, None], [1., float('inf')], ['x', 'y']):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.fit(pd.DataFrame({'value': values}), specification('NORM', {'method': 'min-max'}))

    def test_merge_concat_propagates_nulls_and_never_overwrites_sources(self):
        frame = pd.DataFrame({'first': ['Ada', None], 'last': ['Lovelace', 'Unknown']})
        state = self.fit(frame, specification('MERGE', {'method': 'concat', 'separator': ' '}, ['first', 'last']))
        output = self.apply(frame, state)
        self.assertEqual(output.result.iloc[0], 'Ada Lovelace')
        self.assertTrue(pd.isna(output.result.iloc[1]))
        assert_frame_equal(output.drop(columns='result'), frame)

    def test_merge_date_time_declares_utc_without_converting_clocks(self):
        frame = pd.DataFrame({'day': ['2026-01-01'], 'hour': ['10:30:00']})
        state = self.fit(frame, specification('MERGE', {'method': 'date-time-utc'}, ['day', 'hour']))
        self.assertEqual(self.apply(frame, state).result.iloc[0].isoformat(), '2026-01-01T10:30:00+00:00')
        with self.assertRaisesRegex(ValueError, 'UTC'):
            self.apply(frame.assign(hour='10:30:00+02:00'), state)

    def test_one_hot_has_stable_columns_and_rejects_unseen_categories(self):
        train = pd.DataFrame({'value': ['red', 'blue', None]})
        state = self.fit(train, specification('ENC', {'method': 'one-hot', 'drop_first': False}))
        output = self.apply(pd.DataFrame({'value': ['red', None]}), state)
        self.assertEqual(state['learned']['[]']['categories'], ['blue', 'red'])
        self.assertEqual(output.iloc[0][['result_0', 'result_1']].tolist(), [0, 1])
        self.assertTrue(output[['result_0', 'result_1']].iloc[1].isna().all())
        with self.assertRaisesRegex(ValueError, 'Catégorie inconnue'):
            self.apply(pd.DataFrame({'value': ['green']}), state)
        state = self.fit(train, specification('ENC', {'method': 'one-hot', 'drop_first': True}))
        self.assertEqual(list(self.apply(train, state).columns), ['value', 'result_1'])

    def test_ordinal_requires_explicit_business_order(self):
        frame = pd.DataFrame({'value': ['HIGH', 'LOW', None]})
        spec = specification('ENC', {'method': 'ordinal', 'categories': ['LOW', 'MEDIUM', 'HIGH']})
        output = self.apply(frame, self.fit(frame, spec))
        self.assertEqual(output.result.iloc[:2].tolist(), [2, 0])
        self.assertTrue(pd.isna(output.result.iloc[2]))
        spec['parameters'].pop('categories')
        with self.assertRaises(ValueError):
            self.fit(frame, spec)

    def test_hmac_is_stable_secret_dependent_and_never_serialized(self):
        frame = pd.DataFrame({'value': ['001', '001', None]})
        state = self.fit(frame, specification('ANO', {'method': 'hmac-sha256', 'secret_ref': 'operator'}))
        for secrets in ({}, {'operator': b''}, {'operator': b' '}):
            with self.subTest(secrets=secrets), self.assertRaisesRegex(ValueError, 'secret'):
                self.apply(frame, state, secrets=secrets)
        output = self.apply(frame, state, secrets={'operator': b'local-test-secret'})
        self.assertEqual(output.result.iloc[0], output.result.iloc[1])
        self.assertEqual(len(output.result.iloc[0]), 64)
        self.assertTrue(pd.isna(output.result.iloc[2]))
        other = self.apply(frame, state, secrets={'operator': b'other-test-secret'})
        self.assertNotEqual(output.result.iloc[0], other.result.iloc[0])
        self.assertNotIn('local-test-secret', json.dumps(state))

    def test_strict_dedup_retains_counts_and_refuses_different_unselected_values(self):
        frame = pd.DataFrame({'id': ['a', 'a', 'b'], 'value': [2., 2., 3.]})
        spec = specification('DEL', {'method': 'strict'}, ['id', 'value'], target='measurement_count')
        output = self.apply(frame, self.fit(frame, spec))
        self.assertEqual(output.measurement_count.tolist(), [2, 1])
        self.assertEqual(output.value.tolist(), [2., 3.])
        spec['operate_on_columns'] = ['id']
        with self.assertRaisesRegex(ValueError, 'Doublons de clé'):
            self.apply(frame.assign(value=[2., 4., 3.]), self.fit(frame, spec))

    def test_key_dedup_requires_all_aggregators_and_is_order_independent(self):
        frame = pd.DataFrame({'id': ['a', 'a', 'b'], 'value': [2., 4., None], 'site': ['X', 'X', 'Y']})
        spec = specification('DEL', {'method': 'key', 'aggregations': {'value': 'mean', 'site': 'identical'}}, ['id'])
        output = self.apply(frame, self.fit(frame, spec)).sort_values('id').reset_index(drop=True)
        reverse = self.apply(frame.iloc[::-1], self.fit(frame, spec)).sort_values('id').reset_index(drop=True)
        assert_frame_equal(output, reverse)
        self.assertEqual(output.value.iloc[0], 3.)
        self.assertEqual(output.result.tolist(), [2, 1])
        self.assertTrue(pd.isna(output.value.iloc[1]))
        del spec['parameters']['aggregations']['site']
        with self.assertRaisesRegex(ValueError, 'chaque colonne'):
            self.fit(frame, spec)

    def test_imputation_fills_only_short_whole_gaps_and_adds_indicator(self):
        train = pd.DataFrame({'order': [1, 2], 'value': [2., 4.]})
        spec = specification('IMP', {'method': 'mean', 'order_by': ['order'], 'max_gap_rows': 1})
        state = self.fit(train, spec)
        test = pd.DataFrame({'order': [1, 2, 3, 4, 5], 'value': [1., None, 100., None, None]})
        output = self.apply(test, state)
        self.assertEqual(output.result.iloc[:3].tolist(), [1., 3., 100.])
        self.assertTrue(output.result.iloc[3:].isna().all())
        self.assertEqual(output.result_is_imputed.tolist(), [False, True, False, False, False])
        self.assertTrue(test.value.iloc[[1, 3, 4]].isna().all())

    def test_forward_fill_uses_explicit_order_and_never_crosses_groups(self):
        frame = pd.DataFrame({'group': ['a', 'a', 'b'], 'order': [2, 1, 1], 'value': [None, 'ready', None]})
        spec = specification('IMP', {'method': 'forward-fill', 'group_by': ['group'], 'order_by': ['order'], 'max_gap_rows': 1})
        output = self.apply(frame, self.fit(frame, spec))
        self.assertEqual(output.result.iloc[0], 'ready')
        self.assertTrue(pd.isna(output.result.iloc[2]))
        with self.assertRaisesRegex(ValueError, 'ordre'):
            tied = frame.assign(group='a', order=1)
            self.apply(tied, self.fit(tied, spec))

    def test_group_medians_are_learned_from_training_only(self):
        train = pd.DataFrame({'group': ['a', 'a', 'b', 'b'], 'order': [1, 2, 1, 2], 'value': [1., 3., 10., 30.]})
        spec = specification('IMP', {'method': 'median', 'group_by': ['group'], 'order_by': ['order'], 'max_gap_rows': 1})
        state = self.fit(train, spec)
        test = pd.DataFrame({'group': ['b', 'a'], 'order': [3, 3], 'value': [None, None]})
        output = self.apply(test, state)
        self.assertEqual(output.result.tolist(), [20., 2.])
        self.assertEqual(output.result_is_imputed.tolist(), [True, True])

    def test_all_missing_encoding_and_irrelevant_method_options_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Aucune catégorie'):
            frame = pd.DataFrame({'value': [None, None]})
            self.fit(frame, specification('ENC', {'method': 'one-hot', 'drop_first': False}))
        with self.assertRaises(ValueError):
            frame = pd.DataFrame({'value': ['a', 'b']})
            self.fit(frame, specification('ENC', {'method': 'ordinal', 'categories': ['a', 'b'], 'drop_first': True}))

    def test_outlier_methods_mark_without_removing_or_relearning(self):
        train = pd.DataFrame({'value': [0., 1., 2., 3., 4.]})
        test = pd.DataFrame({'value': [2., 100., None]})
        for method in ('iqr', 'z-score', 'mad'):
            parameters = {'method': method, 'threshold': 3.}
            if method == 'z-score':
                parameters['ddof'] = 0
            with self.subTest(method=method):
                output = self.apply(test, self.fit(train, specification('OUT', parameters)))
                self.assertEqual(len(output), 3)
                self.assertEqual(output.result.iloc[:2].tolist(), [False, True])
                self.assertTrue(pd.isna(output.result.iloc[2]))
                assert_frame_equal(output.drop(columns='result'), test)

    def test_unsafe_or_incomplete_configuration_fails_before_execution(self):
        frame = pd.DataFrame({'value': [1., 2.]})
        spec = specification('NORM', {'method': 'min-max'})
        for change in ({'parameters': {}}, {'target_name': 'value'}, {'operate_on_columns': ['ghost']},
                       {'parameters': {'method': 'min-max', 'secret': 'forbidden'}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.fit(frame, {**spec, **change})
        state = self.fit(frame, spec)
        state['slug'] = 'os.system'
        with self.assertRaisesRegex(ValueError, 'slug'):
            self.apply(frame, state)


if __name__ == '__main__':
    unittest.main()
