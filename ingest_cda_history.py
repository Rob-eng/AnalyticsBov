"""
Ingestão histórica de resultados da Correa da Costa.

Uso:
  python3 ingest_cda_history.py
  python3 ingest_cda_history.py --max-pages 20
  python3 ingest_cda_history.py --max-pages 10 --max-urls 50
"""

import argparse

from app.models import init_db
from app.scraper_cda import run_cda_backfill


def main():
    parser = argparse.ArgumentParser(description="Ingestão histórica Correa da Costa")
    parser.add_argument("--max-pages", type=int, default=100, help="Máximo de páginas do listing /resultados")
    parser.add_argument("--max-urls", type=int, default=None, help="Máximo de URLs de resultados para processar")
    args = parser.parse_args()

    init_db()
    summary = run_cda_backfill(max_pages=args.max_pages, max_urls=args.max_urls)
    print(summary)


if __name__ == "__main__":
    main()

