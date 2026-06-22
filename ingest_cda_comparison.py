"""
Gera comparativos diários entre resultados CDA e cotação da Scot (US$/@) já armazenada.

Uso:
  python3 ingest_cda_comparison.py
  python3 ingest_cda_comparison.py --lookback-days 730
"""

import argparse

from app.cda_analytics import build_cda_scot_comparisons
from app.models import init_db


def main():
    parser = argparse.ArgumentParser(description="Comparativos CDA x Scot")
    parser.add_argument("--lookback-days", type=int, default=3650, help="Janela histórica em dias")
    args = parser.parse_args()

    init_db()
    summary = build_cda_scot_comparisons(lookback_days=args.lookback_days)
    print(summary)


if __name__ == "__main__":
    main()
