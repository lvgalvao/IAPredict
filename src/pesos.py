"""Spec 03 — Pesos: torneio + recência, gerando ``silver_ponderado``.

Adiciona dois eixos de importância a ``silver_jogos``:
- ``peso_torneio`` (ordinal 1/2/3): amistoso / eliminatória e continental / Copa e finais.
- ``peso_recencia`` (decaimento exponencial, meia-vida 5 anos): jogos recentes pesam mais.

Os pesos não são normalizados — o uso é relativo e experimental (feature_07).
"""

from __future__ import annotations

import io

import pandas as pd

from db import get_engine, get_raw_connection

# Data fixa que ancora a recência: início da Copa 2026 (o que queremos prever).
DATA_REF = pd.Timestamp("2026-06-11")

# Torneios de nível 3 (Copa e finais) — igualdade exata.
NIVEL3 = {"FIFA World Cup", "Confederations Cup", "CONMEBOL–UEFA Cup of Champions"}

# Continentais maiores → nível 2 (além de qualifications e nations leagues).
CONTINENTAIS = {
    "UEFA Euro", "Copa América", "African Cup of Nations",
    "AFC Asian Cup", "Gold Cup", "Oceania Nations Cup",
}

COLUNAS = [
    "data", "time_casa", "time_visitante", "gols_casa", "gols_visitante",
    "torneio", "cidade", "pais", "neutro", "eh_amistoso",
    "peso_torneio", "peso_recencia",
]

DDL = """
DROP TABLE IF EXISTS silver_ponderado;
CREATE TABLE silver_ponderado (
    id              bigint generated always as identity primary key,
    data            date,
    time_casa       text,
    time_visitante  text,
    gols_casa       integer,
    gols_visitante  integer,
    torneio         text,
    cidade          text,
    pais            text,
    neutro          boolean,
    eh_amistoso     boolean,
    peso_torneio    integer,
    peso_recencia   double precision
);
"""


def classificar(torneio: str) -> int:
    """Mapeia o nome do torneio para o peso ordinal {1, 2, 3}."""
    if torneio in NIVEL3:
        return 3
    t = torneio.lower()
    if "qualification" in t or "nations league" in t or torneio in CONTINENTAIS:
        return 2
    return 1


def calcular_pesos(df: pd.DataFrame) -> pd.DataFrame:
    df = df.drop(columns=["id"]).copy()
    df["peso_torneio"] = df["torneio"].apply(classificar)

    idade_anos = (DATA_REF - df["data"]).dt.days / 365.25
    df["peso_recencia"] = 0.5 ** (idade_anos / 5)

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
                f"COPY silver_ponderado ({', '.join(COLUNAS)}) "
                "FROM STDIN WITH (FORMAT csv, NULL '')",
                buffer,
            )
            cur.execute("SELECT COUNT(*) FROM silver_ponderado;")
            total = cur.fetchone()[0]
        conn.commit()
        return total
    finally:
        conn.close()


def main() -> None:
    print("Lendo silver_jogos...")
    df = pd.read_sql("SELECT * FROM silver_jogos", get_engine(), parse_dates=["data"])
    print(f"  {len(df):,} linhas")

    ponderado = calcular_pesos(df)
    total = gravar(ponderado)

    print("\n" + "=" * 60)
    print("RELATÓRIO PESOS")
    print("=" * 60)
    print(f"  silver_ponderado: {total:,} linhas")
    print("  distribuição peso_torneio:")
    for peso, n in ponderado["peso_torneio"].value_counts().sort_index().items():
        print(f"    nível {peso}: {n:,}")
    print(f"  peso_recencia: min={ponderado['peso_recencia'].min():.4f} "
          f"max={ponderado['peso_recencia'].max():.4f}")
    print("  5 jogos mais recentes:")
    recentes = ponderado.sort_values("data", ascending=False).head(5)
    for _, r in recentes.iterrows():
        print(f"    {r['data'].date()}  recencia={r['peso_recencia']:.4f}  torneio={r['peso_torneio']}")
    print("=" * 60)
    print("\n✓ silver_ponderado concluída.")


if __name__ == "__main__":
    main()
