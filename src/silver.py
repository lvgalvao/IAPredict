"""Spec 02 — Silver: limpeza + anti-leakage a partir de ``bronze_jogos``.

Transforma o dado cru da bronze em dado confiável e aplica o split anti-leakage
(regra inegociável): os 72 jogos da Copa 2026 ficam isolados em ``silver_copa2026`` e
nunca entram no treino; o histórico limpo (>= 2006, com placar) vai para ``silver_jogos``.
"""

from __future__ import annotations

import io

import pandas as pd

from db import get_engine, get_raw_connection

# Padronização de nomes de seleção (inglês). Os dados do Kaggle já estão consistentes
# e os 48 times da Copa 2026 batem com o histórico — o dicionário fica pronto para
# eventuais variantes, mas hoje só aplicamos strip de espaços.
DICIONARIO_SELECOES: dict[str, str] = {}

# Janela temporal do projeto.
DATA_CORTE = "2006-01-01"

# Colunas de negócio (ordem da tabela; o id é gerado pelo banco).
COLUNAS = [
    "data", "time_casa", "time_visitante", "gols_casa", "gols_visitante",
    "torneio", "cidade", "pais", "neutro", "eh_amistoso",
]


def _ddl(tabela: str) -> str:
    return f"""
DROP TABLE IF EXISTS {tabela};
CREATE TABLE {tabela} (
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
    eh_amistoso     boolean
);
"""


def transformar(bronze: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Limpa a bronze e devolve (silver_jogos, silver_copa2026)."""
    df = bronze.drop(columns=["id"]).copy()

    # Gols voltam do banco como float (por causa dos nulos) — reverter p/ inteiro nullable.
    for col in ("gols_casa", "gols_visitante"):
        df[col] = df[col].astype("Int64")

    # 1) Padronizar nomes de seleção: strip + dicionário único.
    for col in ("time_casa", "time_visitante"):
        df[col] = df[col].str.strip().replace(DICIONARIO_SELECOES)

    # 2) Remover duplicatas exatas (colunas de negócio).
    df = df.drop_duplicates()

    # 3) Derivar eh_amistoso.
    df["eh_amistoso"] = df["torneio"] == "Friendly"

    # 4) Split anti-leakage: Copa 2026 = jogos sem placar (futuros, não jogados).
    eh_copa2026 = df["gols_casa"].isna()
    copa2026 = df[eh_copa2026].copy()

    # 5) silver_jogos: histórico com placar, dentro da janela temporal.
    jogos = df[~eh_copa2026].copy()
    jogos = jogos[jogos["data"] >= pd.Timestamp(DATA_CORTE)]

    return jogos[COLUNAS], copa2026[COLUNAS]


def gravar(df: pd.DataFrame, tabela: str) -> int:
    """Cria a tabela (idempotente) e carrega via COPY. Retorna o total inserido."""
    buffer = io.StringIO()
    df.to_csv(buffer, index=False, header=False, na_rep="")
    buffer.seek(0)

    conn = get_raw_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_ddl(tabela))
            cur.copy_expert(
                f"COPY {tabela} ({', '.join(COLUNAS)}) FROM STDIN WITH (FORMAT csv, NULL '')",
                buffer,
            )
            cur.execute(f"SELECT COUNT(*) FROM {tabela};")
            total = cur.fetchone()[0]
        conn.commit()
        return total
    finally:
        conn.close()


def main() -> None:
    print("Lendo bronze_jogos...")
    bronze = pd.read_sql("SELECT * FROM bronze_jogos", get_engine(), parse_dates=["data"])
    print(f"  {len(bronze):,} linhas na bronze")

    jogos, copa2026 = transformar(bronze)

    n_jogos = gravar(jogos, "silver_jogos")
    n_copa = gravar(copa2026, "silver_copa2026")

    print("\n" + "=" * 60)
    print("RELATÓRIO SILVER")
    print("=" * 60)
    print(f"  silver_jogos:     {n_jogos:,} linhas")
    print(f"  silver_copa2026:  {n_copa:,} linhas")
    print(f"  período silver_jogos: {jogos['data'].min().date()} -> {jogos['data'].max().date()}")
    print(f"  gols nulos em silver_jogos: {int(jogos['gols_casa'].isna().sum())}")
    print("  eh_amistoso em silver_jogos:")
    for valor, n in jogos["eh_amistoso"].value_counts().items():
        print(f"    {valor!s:<6} {n:,}")
    print("=" * 60)
    print("\n✓ Camada silver concluída.")


if __name__ == "__main__":
    main()
