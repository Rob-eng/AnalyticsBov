"""
Teste de integração/regressão contra o caso de referência validado
manualmente (ver prompt_ferramenta_prodes_bot.md): imóvel CAR
MS-5003207-1B4C085E5E8C452A9708585194C7BFC1, Corumbá/MS, 66.607,81 ha.
Apontamento PRODES d2008 com dois polígonos somando 473,92 ha (315,12 +
158,80), image_date 26/08/2008, Landsat 5 TM.

Não roda no CI comum — precisa de GEE real (para o CAR e as cenas de
satélite), acesso ao WFS do TerraBrasilis/INPE (consulta ao vivo, sem base
local) e um ponto (lat/lon) conhecido dentro desse imóvel. Rodar com:

    RUN_GEE_INTEGRATION=1 PRODES_TEST_LAT=-19.xx PRODES_TEST_LON=-57.xx \\
        python3 -m unittest test_prodes_regression.py

A asserção é sobre intervalo/cobertura/área (±0,5%), não sobre a cena exata
— a cena escolhida pode variar conforme o filtro de disponibilidade do GEE.
"""
import os
import unittest
from datetime import date

RUN_INTEGRATION = os.getenv('RUN_GEE_INTEGRATION') == '1'
TEST_LAT = os.getenv('PRODES_TEST_LAT')
TEST_LON = os.getenv('PRODES_TEST_LON')


@unittest.skipUnless(
    RUN_INTEGRATION and TEST_LAT and TEST_LON,
    "requer RUN_GEE_INTEGRATION=1 e PRODES_TEST_LAT/PRODES_TEST_LON (ponto dentro do "
    "imóvel de referência).",
)
class TestProdesRegressionCorumba(unittest.TestCase):

    EXPECTED_CAR = 'MS-5003207-1B4C085E5E8C452A9708585194C7BFC1'
    EXPECTED_CLASS = 'd2008'
    EXPECTED_AREA_HA = 473.92
    EXPECTED_IMAGE_DATE = date(2008, 8, 26)

    def test_full_pipeline_against_known_case(self):
        from app.prodes_analysis import (
            fetch_car_perimeter_full, find_intersecting_apontamentos, select_before_after_scenes,
        )

        lat, lon = float(TEST_LAT), float(TEST_LON)
        car = fetch_car_perimeter_full(lat, lon)
        self.assertEqual(car['status'], 'OFFICIAL')
        self.assertEqual(car['cod_imovel'], self.EXPECTED_CAR)

        apontamentos = find_intersecting_apontamentos(car['geometry'])
        d2008 = [a for a in apontamentos if a['class_name'] == self.EXPECTED_CLASS]
        self.assertTrue(d2008, "Apontamento d2008 não encontrado no WFS do TerraBrasilis/INPE.")

        total_area = sum(a['area_total_ha'] for a in d2008)
        self.assertAlmostEqual(total_area, self.EXPECTED_AREA_HA, delta=self.EXPECTED_AREA_HA * 0.005)

        scenes = select_before_after_scenes(car['geometry'], {'image_date': self.EXPECTED_IMAGE_DATE})
        scene_before, scene_after = scenes['scene_before'], scenes['scene_after']

        self.assertIsNotNone(scene_before, "Nenhuma cena 'antes' aprovada dentro da janela de 12 meses.")
        self.assertIsNotNone(scene_after, "Nenhuma cena 'depois' aprovada dentro da janela de 12 meses.")

        # Cena "antes" deve ser anterior ao marco de 22/07/2008 (art. 3º, IV, Lei 12.651/2012)
        self.assertLess(scene_before['date'], date(2008, 7, 22))
        self.assertGreaterEqual(scene_before['coverage_pct'], 99.0)
        self.assertLessEqual(scene_before['cloud_pct'], 25.0)

        # Cena "depois" deve ser posterior a image_date
        self.assertGreater(scene_after['date'], self.EXPECTED_IMAGE_DATE)
        self.assertGreaterEqual(scene_after['coverage_pct'], 99.0)


if __name__ == '__main__':
    unittest.main()
