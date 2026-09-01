"""
Testes unitários do poller PRODES (app/prodes_worker.py): estabilidade do
hash de idempotência e cálculo de backoff exponencial. Essas duas funções
não tocam banco nem GEE — os imports de app.models usados pelo resto do
módulo são tardios (dentro das funções que precisam), então importar
app.prodes_worker aqui não exige DATABASE_URL configurada.

Rodar: python3 -m unittest test_prodes_worker.py
"""
import unittest
from datetime import date

from app.prodes_worker import (
    compute_idempotency_key,
    compute_backoff_seconds,
    BACKOFF_BASE_SECONDS,
    BACKOFF_CAP_SECONDS,
    _scrub_credentials,
)


class TestIdempotencyKey(unittest.TestCase):
    def test_same_inputs_same_key(self):
        k1 = compute_idempotency_key("-21.4,-54.7", "uuid-1", date(2008, 5, 6), date(2009, 1, 10), "v20260528")
        k2 = compute_idempotency_key("-21.4,-54.7", "uuid-1", date(2008, 5, 6), date(2009, 1, 10), "v20260528")
        self.assertEqual(k1, k2)

    def test_different_apontamento_different_key(self):
        k1 = compute_idempotency_key("loc-1", "uuid-1", None, None, "v20260528")
        k2 = compute_idempotency_key("loc-1", "uuid-2", None, None, "v20260528")
        self.assertNotEqual(k1, k2)

    def test_different_dates_different_key(self):
        k1 = compute_idempotency_key("loc-1", "uuid-1", date(2008, 5, 6), None, "v20260528")
        k2 = compute_idempotency_key("loc-1", "uuid-1", date(2008, 5, 7), None, "v20260528")
        self.assertNotEqual(k1, k2)

    def test_different_base_version_different_key(self):
        k1 = compute_idempotency_key("loc-1", "uuid-1", None, None, "v20260528")
        k2 = compute_idempotency_key("loc-1", "uuid-1", None, None, "v20270101")
        self.assertNotEqual(k1, k2)

    def test_none_dates_do_not_collide_with_explicit_auto_string(self):
        # Garante que None não vira acidentalmente igual a alguma data real.
        k_auto = compute_idempotency_key("loc-1", "uuid-1", None, None, "v1")
        k_literal = compute_idempotency_key("loc-1", "uuid-1", date(2000, 1, 1), None, "v1")
        self.assertNotEqual(k_auto, k_literal)


class TestBackoff(unittest.TestCase):
    def test_increases_with_attempts(self):
        delays = [compute_backoff_seconds(n) for n in range(1, 5)]
        self.assertEqual(delays, sorted(delays))
        self.assertTrue(all(d2 >= d1 for d1, d2 in zip(delays, delays[1:])))

    def test_first_attempt_uses_base(self):
        self.assertEqual(compute_backoff_seconds(1), BACKOFF_BASE_SECONDS)

    def test_capped(self):
        self.assertEqual(compute_backoff_seconds(100), BACKOFF_CAP_SECONDS)

    def test_zero_or_negative_attempts_treated_as_first(self):
        self.assertEqual(compute_backoff_seconds(0), BACKOFF_BASE_SECONDS)


class TestScrubCredentials(unittest.TestCase):
    def test_redacts_private_key(self):
        msg = 'Erro: {"private_key": "-----BEGIN PRIVATE KEY-----\\nabc\\n-----END-----"}'
        scrubbed = _scrub_credentials(msg)
        self.assertNotIn('BEGIN PRIVATE KEY', scrubbed)
        self.assertIn('[REDACTED]', scrubbed)

    def test_passes_through_normal_message(self):
        msg = "Falha ao encontrar cena aprovada dentro dos critérios de nuvem."
        self.assertEqual(_scrub_credentials(msg), msg)

    def test_handles_empty(self):
        self.assertEqual(_scrub_credentials(""), "")
        self.assertEqual(_scrub_credentials(None), "")


if __name__ == '__main__':
    unittest.main()
