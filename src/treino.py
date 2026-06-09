"""Spec 06 — Treino Poisson + validação.

Treina dois GLM Poisson (gols do mandante e do visitante) sobre ``gold_atributos``, valida num
holdout temporal e persiste três artefatos em ``models/``. Grava as métricas em
``metricas_validacao``. Gol é contagem (≥0): por isso Poisson, não regressão linear.
"""

from __future__ import annotations

import os
import pickle

import numpy as np
import pandas as pd
import statsmodels.api as sm

import poisson
from db import get_engine, get_raw_connection

# Os 6 atributos do modelo (identificadores NÃO entram como feature).
ATRIBUTOS = ["elo_casa", "elo_visitante", "dif_elo", "neutro", "peso_torneio", "peso_recencia"]

CORTE = pd.Timestamp("2024-01-01")  # treino < CORTE <= teste
MODELS_DIR = "models"

DDL = """
DROP TABLE IF EXISTS metricas_validacao;
CREATE TABLE metricas_validacao (
    id              bigint generated always as identity primary key,
    mae_casa        double precision,
    mae_visitante   double precision,
    acuracia        double precision
);
"""


def montar_X(df: pd.DataFrame) -> pd.DataFrame:
    """Monta a matriz de features com constante; neutro como inteiro."""
    X = df[ATRIBUTOS].copy()
    X["neutro"] = X["neutro"].astype(int)
    return sm.add_constant(X, has_constant="add")


def treinar(treino: pd.DataFrame):
    X = montar_X(treino)
    peso_amostra = treino["peso_torneio"] * treino["peso_recencia"]
    poisson_fam = sm.families.Poisson()
    modelo_casa = sm.GLM(treino["gols_casa"], X, family=poisson_fam, var_weights=peso_amostra).fit()
    modelo_visit = sm.GLM(treino["gols_visitante"], X, family=poisson_fam, var_weights=peso_amostra).fit()
    return modelo_casa, modelo_visit


def validar(modelo_casa, modelo_visit, teste: pd.DataFrame) -> dict:
    X = montar_X(teste)
    lam_casa = np.asarray(modelo_casa.predict(X))
    lam_visit = np.asarray(modelo_visit.predict(X))

    mae_casa = float(np.mean(np.abs(lam_casa - teste["gols_casa"].to_numpy())))
    mae_visit = float(np.mean(np.abs(lam_visit - teste["gols_visitante"].to_numpy())))

    previsto = poisson.resultados_previstos(lam_casa, lam_visit)
    real = poisson.resultado_real(teste["gols_casa"].to_numpy(), teste["gols_visitante"].to_numpy())
    acuracia = float(np.mean(previsto == real))

    return {"mae_casa": mae_casa, "mae_visitante": mae_visit, "acuracia": acuracia}


def persistir_modelos(modelo_casa, modelo_visit) -> None:
    os.makedirs(MODELS_DIR, exist_ok=True)
    modelo_casa.save(os.path.join(MODELS_DIR, "modelo_poisson_casa.pkl"))
    modelo_visit.save(os.path.join(MODELS_DIR, "modelo_poisson_visitante.pkl"))
    with open(os.path.join(MODELS_DIR, "colunas_atributos.pkl"), "wb") as f:
        pickle.dump(ATRIBUTOS, f)


def gravar_metricas(m: dict) -> None:
    conn = get_raw_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(DDL)
            cur.execute(
                "INSERT INTO metricas_validacao (mae_casa, mae_visitante, acuracia) VALUES (%s, %s, %s)",
                (m["mae_casa"], m["mae_visitante"], m["acuracia"]),
            )
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    print("Lendo gold_atributos...")
    df = pd.read_sql("SELECT * FROM gold_atributos", get_engine(), parse_dates=["data"])

    treino = df[df["data"] < CORTE]
    teste = df[df["data"] >= CORTE]
    print(f"  treino: {len(treino):,} jogos (< {CORTE.date()}) | teste: {len(teste):,} jogos")

    modelo_casa, modelo_visit = treinar(treino)
    metricas = validar(modelo_casa, modelo_visit, teste)

    persistir_modelos(modelo_casa, modelo_visit)
    gravar_metricas(metricas)

    print("\n" + "=" * 60)
    print("RELATÓRIO TREINO/VALIDAÇÃO")
    print("=" * 60)
    print(f"  MAE gols casa:      {metricas['mae_casa']:.4f}")
    print(f"  MAE gols visitante: {metricas['mae_visitante']:.4f}")
    print(f"  Acurácia resultado: {metricas['acuracia']:.4f} ({metricas['acuracia']*100:.1f}%)")
    print(f"  Artefatos salvos em {MODELS_DIR}/")
    print("=" * 60)
    print("\n✓ Treino concluído.")


if __name__ == "__main__":
    main()
