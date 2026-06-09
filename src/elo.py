"""Spec 04 — ELO: força dinâmica das seleções, gerando ``silver_elo_pre_jogo`` e ``silver_elo_atual``.

ELO é engenharia sequencial (não ML): cada seleção começa em 1500 e o rating é atualizado
após cada jogo, em ordem cronológica. Grava-se sempre o ELO PRÉ-jogo (anti-leakage: o rating
de uma partida nunca incorpora o próprio resultado).
"""

from __future__ import annotations

import io

import pandas as pd

from db import get_engine, get_raw_connection

ELO_INICIAL = 1500.0
HFA = 100.0  # mando de campo (pontos de ELO), aplicado ao time_casa quando não-neutro.
K_POR_PESO = {1: 20.0, 2: 40.0, 3: 60.0}

COLS_PRE = ["jogo_id", "data", "time_casa", "time_visitante", "elo_casa", "elo_visitante"]
COLS_ATUAL = ["selecao", "elo"]

DDL = """
DROP TABLE IF EXISTS silver_elo_pre_jogo;
CREATE TABLE silver_elo_pre_jogo (
    id              bigint generated always as identity primary key,
    jogo_id         bigint,
    data            date,
    time_casa       text,
    time_visitante  text,
    elo_casa        double precision,
    elo_visitante   double precision
);

DROP TABLE IF EXISTS silver_elo_atual;
CREATE TABLE silver_elo_atual (
    id              bigint generated always as identity primary key,
    selecao         text,
    elo             double precision
);
"""


def calcular_elo(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Processa os jogos em ordem cronológica e devolve (silver_elo_pre_jogo, silver_elo_atual)."""
    elo: dict[str, float] = {}
    linhas_pre = []

    for jogo in df.itertuples(index=False):
        r_casa = elo.get(jogo.time_casa, ELO_INICIAL)
        r_visit = elo.get(jogo.time_visitante, ELO_INICIAL)

        # Grava o pré-jogo ANTES de qualquer atualização.
        linhas_pre.append((jogo.id, jogo.data, jogo.time_casa, jogo.time_visitante, r_casa, r_visit))

        hfa = 0.0 if jogo.neutro else HFA
        e_casa = 1.0 / (1.0 + 10.0 ** ((r_visit - r_casa - hfa) / 400.0))
        e_visit = 1.0 - e_casa

        if jogo.gols_casa > jogo.gols_visitante:
            s_casa = 1.0
        elif jogo.gols_casa == jogo.gols_visitante:
            s_casa = 0.5
        else:
            s_casa = 0.0

        k = K_POR_PESO[jogo.peso_torneio]
        elo[jogo.time_casa] = r_casa + k * (s_casa - e_casa)
        elo[jogo.time_visitante] = r_visit + k * ((1.0 - s_casa) - e_visit)

    pre = pd.DataFrame(linhas_pre, columns=["jogo_id", "data", "time_casa", "time_visitante", "elo_casa", "elo_visitante"])
    atual = (
        pd.DataFrame(sorted(elo.items(), key=lambda kv: kv[1], reverse=True), columns=COLS_ATUAL)
    )
    return pre, atual


def gravar(pre: pd.DataFrame, atual: pd.DataFrame) -> None:
    conn = get_raw_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(DDL)
            for df, tabela, cols in ((pre, "silver_elo_pre_jogo", COLS_PRE), (atual, "silver_elo_atual", COLS_ATUAL)):
                buffer = io.StringIO()
                df.to_csv(buffer, index=False, header=False, na_rep="")
                buffer.seek(0)
                cur.copy_expert(
                    f"COPY {tabela} ({', '.join(cols)}) FROM STDIN WITH (FORMAT csv, NULL '')",
                    buffer,
                )
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    print("Lendo silver_ponderado (ordem cronológica)...")
    df = pd.read_sql(
        "SELECT id, data, time_casa, time_visitante, gols_casa, gols_visitante, neutro, peso_torneio "
        "FROM silver_ponderado ORDER BY data, id",
        get_engine(), parse_dates=["data"],
    )
    print(f"  {len(df):,} jogos")

    pre, atual = calcular_elo(df)
    gravar(pre, atual)

    print("\n" + "=" * 60)
    print("RELATÓRIO ELO")
    print("=" * 60)
    print(f"  silver_elo_pre_jogo: {len(pre):,} linhas")
    print(f"  silver_elo_atual:    {len(atual):,} seleções")
    print(f"  primeiro jogo: elo_casa={pre.iloc[0]['elo_casa']:.0f} elo_visitante={pre.iloc[0]['elo_visitante']:.0f}")
    print("  Top 10 ELO atual:")
    for _, r in atual.head(10).iterrows():
        print(f"    {r['selecao']:<20} {r['elo']:.0f}")
    print("=" * 60)
    print("\n✓ ELO concluído.")


if __name__ == "__main__":
    main()
