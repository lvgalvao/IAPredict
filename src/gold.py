"""Spec 05 — Atributos Gold: a tabela de treino ``gold_atributos``.

Junta ``silver_ponderado`` (pesos + alvos) com ``silver_elo_pre_jogo`` (força pré-jogo), deriva
``dif_elo`` e mantém apenas jogos competitivos (exclui amistosos). Uma linha por jogo, pronta
para o Poisson da feature_06.
"""

from __future__ import annotations

import io

import pandas as pd

from db import get_engine, get_raw_connection

# Colunas de atributo que não podem ter nulos (requisito 5).
COLS_ATRIBUTO = [
    "elo_casa", "elo_visitante", "dif_elo", "neutro",
    "peso_torneio", "peso_recencia", "gols_casa", "gols_visitante",
]

# Ordem final da tabela (identificadores + atributos); id é gerado pelo banco.
COLUNAS = ["jogo_id", "data", "time_casa", "time_visitante"] + COLS_ATRIBUTO

# Join 1:1 já filtrado para jogos competitivos, em ordem cronológica.
QUERY = """
SELECT s.id AS jogo_id, s.data, s.time_casa, s.time_visitante,
       e.elo_casa, e.elo_visitante,
       s.neutro, s.peso_torneio, s.peso_recencia, s.gols_casa, s.gols_visitante
FROM silver_ponderado s
JOIN silver_elo_pre_jogo e ON e.jogo_id = s.id
WHERE NOT s.eh_amistoso
ORDER BY s.data, s.id
"""

DDL = """
DROP TABLE IF EXISTS gold_atributos;
CREATE TABLE gold_atributos (
    id              bigint generated always as identity primary key,
    jogo_id         bigint,
    data            date,
    time_casa       text,
    time_visitante  text,
    elo_casa        double precision,
    elo_visitante   double precision,
    dif_elo         double precision,
    neutro          boolean,
    peso_torneio    integer,
    peso_recencia   double precision,
    gols_casa       integer,
    gols_visitante  integer
);
"""


def montar(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["dif_elo"] = df["elo_casa"] - df["elo_visitante"]

    nulos = df[COLS_ATRIBUTO].isna().sum().sum()
    assert nulos == 0, f"gold_atributos teria {nulos} nulos em colunas de atributo"

    return df[COLUNAS]


def gravar(df: pd.DataFrame) -> int:
    buffer = io.StringIO()
    df.to_csv(buffer, index=False, header=False, na_rep="")
    buffer.seek(0)

    conn = get_raw_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(DDL)
            cur.copy_expert(
                f"COPY gold_atributos ({', '.join(COLUNAS)}) FROM STDIN WITH (FORMAT csv, NULL '')",
                buffer,
            )
            cur.execute("SELECT COUNT(*) FROM gold_atributos;")
            total = cur.fetchone()[0]
        conn.commit()
        return total
    finally:
        conn.close()


def main() -> None:
    print("Juntando silver_ponderado x silver_elo_pre_jogo (só competitivos)...")
    df = pd.read_sql(QUERY, get_engine(), parse_dates=["data"])
    print(f"  {len(df):,} jogos competitivos")

    gold = montar(df)
    total = gravar(gold)

    print("\n" + "=" * 60)
    print("RELATÓRIO GOLD")
    print("=" * 60)
    print(f"  gold_atributos: {total:,} linhas")
    print(f"  nulos em colunas de atributo: {int(gold[COLS_ATRIBUTO].isna().sum().sum())}")
    print(f"  período: {gold['data'].min().date()} -> {gold['data'].max().date()}")
    print("  head (5 linhas):")
    print(gold[COLS_ATRIBUTO].head().to_string(index=False))
    print("=" * 60)
    print("\n✓ gold_atributos concluída.")


if __name__ == "__main__":
    main()
