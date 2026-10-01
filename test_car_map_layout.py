"""
Controle de qualidade do layout do mapa ambiental do CAR (sem internet).

Gera o mapa com imóveis sintéticos de formatos extremos e muitas camadas e
exige que check_map_layout() não aponte sobreposições (painel × mapa, blocos
do painel entre si) nem elementos fora da figura. Imagem de satélite não é
testada aqui (sem GEE) — isso fica na checagem diária app/qa/tool_checks.py.

    python3 -m unittest test_car_map_layout
"""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:1/x")


def _gdfs(width_deg, height_deg, with_many_layers=False):
    import geopandas as gpd
    from shapely.geometry import box
    x0, y0 = -55.0, -20.0
    imovel = box(x0, y0, x0 + width_deg, y0 + height_deg)
    def part(fx0, fy0, fx1, fy1):
        return box(x0 + width_deg * fx0, y0 + height_deg * fy0, x0 + width_deg * fx1, y0 + height_deg * fy1)
    g = lambda geom: gpd.GeoDataFrame({"COD_IMOVEL": ["MS-5001102-" + "A" * 32]}, geometry=[geom], crs="EPSG:4326")
    gdfs = {"imovel": g(imovel), "consolidada": g(part(0, 0, 0.6, 0.6)), "vegetacao": g(part(0.6, 0.6, 1, 1))}
    if with_many_layers:
        gdfs.update({"reserva": g(part(0.6, 0, 1, 0.3)), "app": g(part(0, 0.6, 0.2, 1)),
                     "uso_restrito": g(part(0.3, 0.7, 0.5, 0.9)), "agua": g(part(0.05, 0.65, 0.1, 0.95)),
                     "extra_servidao": g(part(0.7, 0.35, 0.9, 0.45)), "extra_pousio": g(part(0.2, 0.2, 0.3, 0.3))})
    return gdfs


class TestCarMapLayout(unittest.TestCase):
    CASES = {
        "muito alto": (0.01, 0.08),
        "muito largo": (0.10, 0.01),
        "quadrado": (0.03, 0.03),
        "minúsculo": (0.002, 0.003),
        "grande": (0.4, 0.3),
    }

    def _layout_issues(self, gdfs):
        from app import charts
        out = charts.generate_pro_car_map(gdfs)
        self.assertTrue(out and len(out) > 20_000, "mapa não gerado")
        return [i for i in charts.LAST_LAYOUT_ISSUES if "satélite" not in i]

    def test_formatos(self):
        for name, (w, h) in self.CASES.items():
            with self.subTest(formato=name):
                self.assertEqual(self._layout_issues(_gdfs(w, h)), [])

    def test_legenda_longa(self):
        for name, (w, h) in self.CASES.items():
            with self.subTest(formato=name):
                self.assertEqual(self._layout_issues(_gdfs(w, h, with_many_layers=True)), [])


if __name__ == "__main__":
    unittest.main()
