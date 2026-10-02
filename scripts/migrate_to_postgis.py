"""
Copia o banco principal (Postgres) para o novo Postgres com PostGIS.

Uso (a partir da raiz do projeto):
    SOURCE_URL=postgres://... TARGET_URL=postgres://... python scripts/migrate_to_postgis.py [--verify]

- Cria o esquema no destino a partir de app.models (Base.metadata) e ativa PostGIS.
- Copia todas as tabelas em ordem de dependência (FKs), em lotes.
- Idempotente: TRUNCA as tabelas do destino antes de copiar — rodar de novo
  imediatamente antes da troca do DATABASE_URL pega os registros mais novos.
- Acerta as sequences (ids) para continuar de onde a origem parou.
- --verify: só compara a contagem de linhas origem × destino.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:1/x")  # app.models exige ao importar

from sqlalchemy import create_engine, text, MetaData  # noqa: E402

BATCH = 2000


def _url(u: str) -> str:
    return u.replace("postgres://", "postgresql://", 1)


def main():
    src = create_engine(_url(os.environ["SOURCE_URL"]))
    dst = create_engine(_url(os.environ["TARGET_URL"]))
    verify_only = "--verify" in sys.argv

    from app.models import Base

    src_meta = MetaData()
    src_meta.reflect(bind=src)
    tables = [t for t in Base.metadata.sorted_tables if t.name in src_meta.tables]
    missing = set(src_meta.tables) - {t.name for t in tables}
    if missing:
        print(f"⚠️ Tabelas na origem sem modelo (não copiadas): {sorted(missing)}")

    if not verify_only:
        with dst.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        Base.metadata.create_all(dst)
        # colunas adicionadas por ALTER em init_db também existem nos modelos → create_all cobre
        with dst.begin() as conn:
            names = ", ".join(f'"{t.name}"' for t in tables)
            conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))

        for table in tables:
            src_cols = {c.name for c in src_meta.tables[table.name].columns}
            cols = [c for c in table.columns if c.name in src_cols]
            total = 0
            with src.connect() as s_conn, dst.begin() as d_conn:
                result = s_conn.execution_options(stream_results=True).execute(
                    src_meta.tables[table.name].select().with_only_columns(
                        *[src_meta.tables[table.name].c[c.name] for c in cols]
                    )
                )
                while True:
                    rows = result.fetchmany(BATCH)
                    if not rows:
                        break
                    d_conn.execute(table.insert(), [dict(r._mapping) for r in rows])
                    total += len(rows)
            print(f"  {table.name:28} {total:>8} linhas")

        # sequences: continuar do maior id copiado
        with dst.begin() as conn:
            for table in tables:
                for col in table.primary_key.columns:
                    if col.autoincrement is True or (col.type.python_type is int and col.autoincrement == "auto"):
                        seq = conn.execute(text("SELECT pg_get_serial_sequence(:t, :c)"),
                                           {"t": table.name, "c": col.name}).scalar()
                        if seq:
                            conn.execute(text(
                                f"SELECT setval('{seq}', COALESCE((SELECT MAX(\"{col.name}\") FROM \"{table.name}\"), 0) + 1, false)"
                            ))

    # verificação
    ok = True
    with src.connect() as s_conn, dst.connect() as d_conn:
        for table in tables:
            a = s_conn.execute(text(f'SELECT COUNT(*) FROM "{table.name}"')).scalar()
            b = d_conn.execute(text(f'SELECT COUNT(*) FROM "{table.name}"')).scalar()
            flag = "✅" if a == b else "❌"
            ok &= a == b
            print(f"{flag} {table.name:28} origem={a:>8} destino={b:>8}")
        postgis = d_conn.execute(text("SELECT postgis_full_version()")).scalar()
        print("PostGIS:", postgis.split(" ")[1] if postgis else None)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
