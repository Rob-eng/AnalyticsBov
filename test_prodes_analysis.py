"""
Testes unitários da lógica de negócio PRODES (app/prodes_analysis.py).
Só exercita as funções puras e select_before_after_scenes (com find_best_scene
mockado) — nada aqui toca o Earth Engine de verdade. Requer as dependências
de requirements.txt instaladas (earthengine-api, sqlalchemy etc. são
importadas pelo módulo, mesmo sem serem chamadas nestes testes).

Rodar: python3 -m unittest test_prodes_analysis.py
"""
import unittest
from datetime import date
from unittest.mock import patch

from app.prodes_analysis import (
    select_collection_for_date,
    decode_qa_pixel_histogram,
    decode_scl_histogram,
    select_before_after_scenes,
    geodesic_area_ha,
    reflectance_visualize_params,
    LEGAL_CONSOLIDATION_MARK,
    _parse_flexible_date,
)


class TestSelectCollectionForDate(unittest.TestCase):
    def test_1990_uses_landsat5(self):
        self.assertEqual(select_collection_for_date(date(1990, 6, 1)), 'LANDSAT/LT05/C02/T1_L2')

    def test_2015_uses_landsat8(self):
        self.assertEqual(select_collection_for_date(date(2015, 1, 1)), 'LANDSAT/LC08/C02/T1_L2')

    def test_2023_uses_sentinel2(self):
        self.assertEqual(select_collection_for_date(date(2023, 3, 1)), 'COPERNICUS/S2_SR_HARMONIZED')

    def test_2012_06_slc_off_window_uses_landsat7(self):
        # Landsat 5 termina em mai/2012, Landsat 8 só começa em abr/2013 —
        # único recurso disponível é o Landsat 7 (SLC-off).
        self.assertEqual(select_collection_for_date(date(2012, 6, 15)), 'LANDSAT/LE07/C02/T1_L2')

    def test_before_1984_returns_none(self):
        self.assertIsNone(select_collection_for_date(date(1980, 1, 1)))


class TestDecodeQaPixelHistogram(unittest.TestCase):
    def test_clear_scene(self):
        # bit0=fill, bit1=nuvem dilatada, bit3=nuvem, bit4=sombra
        hist = {'0': 100}  # nenhum bit setado: sem fill, sem nuvem
        cloud_pct, coverage_pct = decode_qa_pixel_histogram(hist)
        self.assertEqual(coverage_pct, 100.0)
        self.assertEqual(cloud_pct, 0.0)

    def test_cloud_and_fill_mixed(self):
        # 10 fill (bit0), 10 nuvem (bit3=8), 80 limpos
        hist = {'0': 80, '8': 10, '1': 10}
        cloud_pct, coverage_pct = decode_qa_pixel_histogram(hist)
        self.assertAlmostEqual(coverage_pct, 90.0)
        self.assertAlmostEqual(cloud_pct, 10 / 90 * 100, places=4)

    def test_empty_histogram(self):
        cloud_pct, coverage_pct = decode_qa_pixel_histogram({})
        self.assertEqual((cloud_pct, coverage_pct), (100.0, 0.0))


class TestDecodeSclHistogram(unittest.TestCase):
    def test_clear_scene(self):
        hist = {'4': 100}  # 4 = vegetação, classe "limpa"
        cloud_pct, coverage_pct = decode_scl_histogram(hist)
        self.assertEqual(coverage_pct, 100.0)
        self.assertEqual(cloud_pct, 0.0)

    def test_cloud_and_nodata_mixed(self):
        # 10 sem dado (0), 10 nuvem média (8), 80 vegetação (4)
        hist = {'4': 80, '8': 10, '0': 10}
        cloud_pct, coverage_pct = decode_scl_histogram(hist)
        self.assertAlmostEqual(coverage_pct, 90.0)
        self.assertAlmostEqual(cloud_pct, 10 / 90 * 100, places=4)

    def test_cirrus_counts_as_cloud(self):
        hist = {'4': 90, '10': 10}
        cloud_pct, coverage_pct = decode_scl_histogram(hist)
        self.assertAlmostEqual(coverage_pct, 100.0)
        self.assertAlmostEqual(cloud_pct, 10.0)


class TestReflectanceVisualizeParams(unittest.TestCase):
    def test_landsat5_bands(self):
        params = reflectance_visualize_params('LANDSAT/LT05/C02/T1_L2')
        self.assertEqual(params['bands'], ['SR_B3', 'SR_B2', 'SR_B1'])
        self.assertEqual(params['scale_type'], 'landsat_c2')

    def test_landsat8_bands(self):
        params = reflectance_visualize_params('LANDSAT/LC08/C02/T1_L2')
        self.assertEqual(params['bands'], ['SR_B4', 'SR_B3', 'SR_B2'])

    def test_sentinel2_bands(self):
        params = reflectance_visualize_params('COPERNICUS/S2_SR_HARMONIZED')
        self.assertEqual(params['bands'], ['B4', 'B3', 'B2'])
        self.assertEqual(params['scale_type'], 's2')

    def test_fixed_enhancement(self):
        params = reflectance_visualize_params('COPERNICUS/S2_SR_HARMONIZED')
        self.assertEqual(params['min'], 0.0)
        self.assertEqual(params['max'], 0.35)
        self.assertEqual(params['gamma'], 0.85)

    def test_unknown_collection_raises(self):
        with self.assertRaises(ValueError):
            reflectance_visualize_params('UNKNOWN/COLLECTION')


class TestSelectBeforeAfterScenes(unittest.TestCase):
    def setUp(self):
        self.geometry = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
        self.apontamento = {'image_date': date(2008, 8, 26)}  # caso de referência (Corumbá/MS)

    @patch('app.prodes_analysis.find_best_scene')
    def test_search_windows_around_image_date(self, mock_find_best_scene):
        mock_find_best_scene.side_effect = [
            {'system_index': 'before', 'date': date(2008, 5, 6), 'cloud_pct': 1.9,
             'coverage_pct': 100.0, 'collection_id': 'LANDSAT/LT05/C02/T1_L2'},
            {'system_index': 'after', 'date': date(2009, 1, 10), 'cloud_pct': 3.0,
             'coverage_pct': 100.0, 'collection_id': 'LANDSAT/LT05/C02/T1_L2'},
        ]
        result = select_before_after_scenes(self.geometry, self.apontamento)

        before_call, after_call = mock_find_best_scene.call_args_list
        # antes: busca 12 meses para trás a partir de (image_date - 12 meses)
        self.assertEqual(before_call.args[1], date(2006, 8, 26))
        self.assertEqual(before_call.args[2], date(2007, 8, 26))
        # depois: busca 12 meses para frente a partir de image_date
        self.assertEqual(after_call.args[1], date(2008, 8, 26))
        self.assertEqual(after_call.args[2], date(2009, 8, 26))

        self.assertEqual(result['scene_before']['system_index'], 'before')
        self.assertEqual(result['scene_after']['system_index'], 'after')

    @patch('app.prodes_analysis.find_best_scene')
    def test_legal_mark_warning_when_before_scene_predates_2008_07_22(self, mock_find_best_scene):
        mock_find_best_scene.side_effect = [
            {'system_index': 'before', 'date': date(2008, 5, 6), 'cloud_pct': 1.9,
             'coverage_pct': 100.0, 'collection_id': 'LANDSAT/LT05/C02/T1_L2'},
            {'system_index': 'after', 'date': date(2009, 1, 10), 'cloud_pct': 3.0,
             'coverage_pct': 100.0, 'collection_id': 'LANDSAT/LT05/C02/T1_L2'},
        ]
        result = select_before_after_scenes(self.geometry, self.apontamento)
        self.assertTrue(date(2008, 5, 6) < LEGAL_CONSOLIDATION_MARK)
        self.assertTrue(any('22/07/2008' in w for w in result['warnings']))

    @patch('app.prodes_analysis.find_best_scene')
    def test_forced_dates_override_search_window(self, mock_find_best_scene):
        mock_find_best_scene.return_value = {
            'system_index': 'x', 'date': date(2010, 1, 1), 'cloud_pct': 2.0,
            'coverage_pct': 100.0, 'collection_id': 'LANDSAT/LT05/C02/T1_L2',
        }
        forced_before = date(2008, 5, 6)
        select_before_after_scenes(self.geometry, self.apontamento, forced_before=forced_before)
        before_call = mock_find_best_scene.call_args_list[0]
        self.assertEqual(before_call.args[1], forced_before)
        self.assertEqual(before_call.args[2], forced_before)

    @patch('app.prodes_analysis.find_best_scene')
    def test_slc_off_warning_when_landsat7_used(self, mock_find_best_scene):
        mock_find_best_scene.side_effect = [
            {'system_index': 'before', 'date': date(2012, 6, 1), 'cloud_pct': 4.0,
             'coverage_pct': 99.5, 'collection_id': 'LANDSAT/LE07/C02/T1_L2'},
            {'system_index': 'after', 'date': date(2013, 6, 1), 'cloud_pct': 2.0,
             'coverage_pct': 100.0, 'collection_id': 'LANDSAT/LC08/C02/T1_L2'},
        ]
        apontamento = {'image_date': date(2013, 1, 1)}
        result = select_before_after_scenes(self.geometry, apontamento)
        self.assertTrue(any('SLC-off' in w for w in result['warnings']))


class TestParseFlexibleDate(unittest.TestCase):
    def test_iso_string(self):
        self.assertEqual(_parse_flexible_date('2008-08-26'), date(2008, 8, 26))

    def test_compact_string(self):
        self.assertEqual(_parse_flexible_date('20080826'), date(2008, 8, 26))

    def test_br_string(self):
        self.assertEqual(_parse_flexible_date('26/08/2008'), date(2008, 8, 26))

    def test_epoch_millis(self):
        # 2008-08-26T00:00:00Z em epoch millis
        self.assertEqual(_parse_flexible_date(1219708800000), date(2008, 8, 26))

    def test_none_and_empty(self):
        self.assertIsNone(_parse_flexible_date(None))
        self.assertIsNone(_parse_flexible_date(''))

    def test_garbage_returns_none(self):
        self.assertIsNone(_parse_flexible_date('not-a-date'))


class TestGeodesicAreaHa(unittest.TestCase):
    def test_small_square_at_equator(self):
        # 0.001° x 0.001° no equador: ~111.32m por lado (WGS84/GRS80 quase idênticos ali)
        geom = {
            "type": "Polygon",
            "coordinates": [[[0.0, 0.0], [0.001, 0.0], [0.001, 0.001], [0.0, 0.001], [0.0, 0.0]]],
        }
        area_ha = geodesic_area_ha(geom)
        expected_ha = (111319.49 * 0.001) ** 2 / 10000.0
        self.assertAlmostEqual(area_ha, expected_ha, delta=expected_ha * 0.02)


if __name__ == '__main__':
    unittest.main()
