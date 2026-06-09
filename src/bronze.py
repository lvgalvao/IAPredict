"""Spec 01 — Bronze: ingestão crua de data/results.csv para a tabela ``bronze_jogos``.

Camada bronze do medallion: o dado entra como chegou, apenas com as colunas renomeadas
para português, a data convertida para ``date`` e os gols como inteiro nullable
(os 72 jogos futuros da Copa 2026 trazem ``NA`` → ``NULL``). Nenhuma limpeza ou filtro.
"""

from __future__ import annotations

import io
import os
import sys

import pandas as pd

from db import get_raw_connection

# Dicionário inglês → português (prd.md).
RENAME = {
    "date": "data",
    "home_team": "time_casa",
    "away_team": "time_visitante",
    "home_score": "gols_casa",
    "away_score": "gols_visitante",
    "tournament": "torneio",
    "city": "cidade",
    "country": "pais",
    "neutral": "neutro",
}

# Ordem das colunas na tabela (sem o id, que é gerado pelo banco).
COLUNAS = list(RENAME.values())

DDL = """
DROP TABLE IF EXISTS bronze_jogos;
CREATE TABLE bronze_jogos (
    id              bigint generated always as identity primary key,
    data            date,
    time_casa       text,
    time_visitante  text,
    gols_casa       integer,
    gols_visitante  integer,
    torneio         text,
    cidade          text,
    pais            text,
    neutro          boolean
);
"""


def carregar_csv(caminho: str) -> pd.DataFrame:
    """Lê o CSV cru e aplica apenas as conversões mínimas da camada bronze."""
    # O parser padrão do pandas trata corretamente os campos entre aspas com vírgula
    # embutida (ex.: city = "Washington, D.C."). "NA" nos gols vira NaN automaticamente.
    df = pd.read_csv(caminho, parse_dates=["date"])

    # Gols: inteiro nullable (NaN/NA → NULL no Postgres).
    df["home_score"] = df["home_score"].astype("Int64")
    df["away_score"] = df["away_score"].astype("Int64")

    # neutral chega como booleano (TRUE/FALSE) — garante o tipo bool nativo.
    df["neutral"] = df["neutral"].astype(bool)

    return df.rename(columns=RENAME)


def imprimir_inventario(df: pd.DataFrame) -> None:
    """Inventário exigido pela spec: nº de linhas, tipos e % de nulos por coluna."""
    print("=" * 60)
    print(f"INVENTÁRIO — {len(df):,} linhas")
    print("=" * 60)
    nulos = df.isna().mean() * 100
    for coluna in df.columns:
        print(f"  {coluna:<16} {str(df[coluna].dtype):<10} nulos: {nulos[coluna]:6.2f}%")
    print("=" * 60)


def gravar(df: pd.DataFrame) -> int:
    """Cria a tabela (idempotente) e carrega os dados via COPY."""
    # Buffer CSV em memória: NaN/NA viram string vazia, que o COPY trata como NULL.
    buffer = io.StringIO()
    df[COLUNAS].to_csv(buffer, index=False, header=False, na_rep="")
    buffer.seek(0)

    conn = get_raw_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(DDL)
            cur.copy_expert(
                f"COPY bronze_jogos ({', '.join(COLUNAS)}) "
                "FROM STDIN WITH (FORMAT csv, NULL '')",
                buffer,
            )
            cur.execute("SELECT COUNT(*) FROM bronze_jogos;")
            total = cur.fetchone()[0]
        conn.commit()
        return total
    finally:
        conn.close()


def main() -> None:
    # Caminho do CSV: argumento de linha de comando > CSV_PATH > default.
    caminho = sys.argv[1] if len(sys.argv) > 1 else os.getenv("CSV_PATH", "data/results.csv")
    print(f"Lendo CSV: {caminho}")

    df = carregar_csv(caminho)
    imprimir_inventario(df)

    total = gravar(df)
    print(f"\n✓ bronze_jogos criada com {total:,} linhas.")


if __name__ == "__main__":
    main()
