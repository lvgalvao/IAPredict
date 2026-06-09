"""Utilitários de Poisson compartilhados pelo pipeline (features 06, 07 e 08).

Dado λ_casa e λ_visitante (gols esperados de cada lado), modela o placar como duas Poisson
independentes e deriva probabilidades de resultado (vitória/empate/derrota do mandante).
"""

from __future__ import annotations

import numpy as np
from scipy.stats import poisson

MAX_GOLS = 10


def matriz_placares(lam_casa: float, lam_visit: float, max_gols: int = MAX_GOLS) -> np.ndarray:
    """Matriz (max_gols+1 × max_gols+1) com P(placar = i×j), Poisson independentes."""
    p_casa = poisson.pmf(np.arange(max_gols + 1), lam_casa)
    p_visit = poisson.pmf(np.arange(max_gols + 1), lam_visit)
    return np.outer(p_casa, p_visit)


def probabilidades_resultado(
    lam_casa: float, lam_visit: float, max_gols: int = MAX_GOLS
) -> tuple[float, float, float]:
    """Retorna (P(vitória casa), P(empate), P(vitória visitante))."""
    m = matriz_placares(lam_casa, lam_visit, max_gols)
    p_vit = np.tril(m, -1).sum()   # gols_casa > gols_visit
    p_emp = np.trace(m)            # diagonal: gols_casa == gols_visit
    p_der = np.triu(m, 1).sum()    # gols_casa < gols_visit
    return float(p_vit), float(p_emp), float(p_der)


def resultado_previsto(lam_casa: float, lam_visit: float, max_gols: int = MAX_GOLS) -> str:
    """Resultado mais provável: 'V' (vitória casa), 'E' (empate) ou 'D' (derrota casa)."""
    return "VED"[int(np.argmax(probabilidades_resultado(lam_casa, lam_visit, max_gols)))]


def resultados_previstos(
    lam_casa: np.ndarray, lam_visit: np.ndarray, max_gols: int = MAX_GOLS
) -> np.ndarray:
    """Versão vetorizada: array de 'V'/'E'/'D' para arrays de λ."""
    rotulos = np.array(["V", "E", "D"])
    saida = np.empty(len(lam_casa), dtype="<U1")
    for i, (lc, lv) in enumerate(zip(lam_casa, lam_visit)):
        probs = probabilidades_resultado(lc, lv, max_gols)
        saida[i] = rotulos[int(np.argmax(probs))]
    return saida


def resultado_real(gols_casa: np.ndarray, gols_visit: np.ndarray) -> np.ndarray:
    """Rotula o resultado observado como 'V'/'E'/'D' (do ponto de vista do mandante)."""
    return np.where(gols_casa > gols_visit, "V", np.where(gols_casa == gols_visit, "E", "D"))
