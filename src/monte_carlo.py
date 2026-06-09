"""Spec 08 — Monte Carlo: simulação da Copa 2026.

Simula o torneio N=1000 vezes (grupos → mata-mata), sorteando cada placar com a Poisson dos
modelos treinados, e agrega a frequência de cada seleção por fase em ``gold_probabilidades_copa``.
Uma simulação é ruído; mil viram probabilidade — o "palpite da máquina".
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from db import get_engine, get_raw_connection
from previsao import PESO_TORNEIO_COPA, carregar_modelos
from treino import montar_X

N_SIMULACOES = 1000
SEED = 42
NEUTRO_MATAMATA = True

# Nível de fase alcançado pelo VENCEDOR de cada rodada (base R32 = 1).
NIVEL_VENCEDOR = {"R32": 2, "R16": 3, "QF": 4, "SF": 5, "Final": 6}
COLS_PROB = ["prob_grupo", "prob_oitavas", "prob_quartas", "prob_semi", "prob_final", "prob_campea"]

DDL = """
DROP TABLE IF EXISTS gold_probabilidades_copa;
CREATE TABLE gold_probabilidades_copa (
    id            bigint generated always as identity primary key,
    selecao       text,
    prob_grupo    double precision,
    prob_oitavas  double precision,
    prob_quartas  double precision,
    prob_semi     double precision,
    prob_final    double precision,
    prob_campea   double precision
);
"""


# --------------------------------------------------------------------------- #
# Preparação (uma vez)
# --------------------------------------------------------------------------- #
def preparar():
    eng = get_engine()
    modelo_casa, modelo_visit, _ = carregar_modelos()
    elos = dict(pd.read_sql("SELECT selecao, elo FROM silver_elo_atual", eng).itertuples(index=False, name=None))

    grupos_df = pd.read_csv("data/grupos_copa2026.csv")
    grupo_de = dict(zip(grupos_df["nation"], grupos_df["group"]))
    times_do_grupo = grupos_df.groupby("group")["nation"].apply(list).to_dict()

    jogos_grupo = pd.read_sql(
        "SELECT time_casa, time_visitante, neutro FROM silver_copa2026 ORDER BY data, id", eng
    ).itertuples(index=False, name=None)
    jogos_grupo = list(jogos_grupo)

    # Validação: cada jogo de grupo é intra-grupo.
    for casa, visit, _ in jogos_grupo:
        assert grupo_de[casa] == grupo_de[visit], f"jogo entre grupos diferentes: {casa} x {visit}"

    calendario = pd.read_csv("data/calendario_copa2026.csv").to_dict("records")

    cache: dict[tuple, tuple] = {}

    def lambdas(casa, visit, neutro):
        chave = (casa, visit, neutro)
        if chave not in cache:
            elo_c, elo_v = elos[casa], elos[visit]
            linha = pd.DataFrame([{
                "elo_casa": elo_c, "elo_visitante": elo_v, "dif_elo": elo_c - elo_v,
                "neutro": bool(neutro), "peso_torneio": PESO_TORNEIO_COPA, "peso_recencia": 1.0,
            }])
            X = montar_X(linha)
            cache[chave] = (float(modelo_casa.predict(X)[0]), float(modelo_visit.predict(X)[0]))
        return cache[chave]

    return grupo_de, times_do_grupo, jogos_grupo, calendario, lambdas


def slots_terceiros(calendario) -> list[str]:
    """Os 8 slots de terceiro (away_slot começando com '3' e com grupos elegíveis)."""
    return [m["away_slot"] for m in calendario
            if isinstance(m["away_slot"], str) and m["away_slot"].startswith("3") and len(m["away_slot"]) > 1]


# --------------------------------------------------------------------------- #
# Uma simulação
# --------------------------------------------------------------------------- #
def _placar(lam_casa, lam_visit):
    return np.random.poisson(lam_casa), np.random.poisson(lam_visit)


def _classificar_grupo(times, stats):
    """Ordena os times de um grupo: pontos → saldo → gols pró → sorteio."""
    return sorted(times, key=lambda t: (stats[t]["pts"], stats[t]["saldo"], stats[t]["gp"], np.random.random()),
                  reverse=True)


# Nomes amigáveis das rodadas do mata-mata (para o app).
NOMES_RODADA = {
    "R32": "32-avos de final", "R16": "Oitavas de final", "QF": "Quartas de final",
    "SF": "Semifinais", "3rd": "Disputa de 3º lugar", "Final": "Final",
}


def _disputar_grupos(grupo_de, times_do_grupo, jogos_grupo, lambdas):
    """Disputa a fase de grupos UMA vez. Devolve (stats, jogos_por_grupo, ordem_por_grupo)."""
    stats = {t: {"jogos": 0, "v": 0, "e": 0, "d": 0, "gp": 0, "gc": 0, "pts": 0} for t in grupo_de}
    jogos_por_grupo: dict[str, list] = {g: [] for g in times_do_grupo}

    for casa, visit, neutro in jogos_grupo:
        lc, lv = lambdas(casa, visit, neutro)
        gc, gv = _placar(lc, lv)
        jogos_por_grupo[grupo_de[casa]].append((casa, int(gc), int(gv), visit))
        for t, marcou, sofreu in ((casa, gc, gv), (visit, gv, gc)):
            stats[t]["jogos"] += 1
            stats[t]["gp"] += marcou
            stats[t]["gc"] += sofreu
        if gc > gv:
            stats[casa]["v"] += 1; stats[casa]["pts"] += 3; stats[visit]["d"] += 1
        elif gc < gv:
            stats[visit]["v"] += 1; stats[visit]["pts"] += 3; stats[casa]["d"] += 1
        else:
            stats[casa]["e"] += 1; stats[visit]["e"] += 1
            stats[casa]["pts"] += 1; stats[visit]["pts"] += 1

    ordem_por_grupo = {
        g: sorted(times, key=lambda t: (stats[t]["pts"], stats[t]["gp"] - stats[t]["gc"],
                                        stats[t]["gp"], np.random.random()), reverse=True)
        for g, times in times_do_grupo.items()
    }
    return stats, jogos_por_grupo, ordem_por_grupo


def _classificacao_df(ordem, stats) -> pd.DataFrame:
    """Tabela de classificação de um grupo, colunas em português."""
    return pd.DataFrame([{
        "posicao": i + 1, "selecao": t, "jogos": stats[t]["jogos"],
        "vitorias": stats[t]["v"], "empates": stats[t]["e"], "derrotas": stats[t]["d"],
        "gols_pro": stats[t]["gp"], "gols_contra": stats[t]["gc"],
        "saldo_gols": stats[t]["gp"] - stats[t]["gc"], "pontos": stats[t]["pts"],
    } for i, t in enumerate(ordem)])


def _resolver_terceiros(ordem_por_grupo, stats, slots_3) -> dict[str, str]:
    """Rankeia os 12 terceiros, pega os 8 melhores e os atribui aos slots 3xxxx (matching)."""
    terceiros = [(ordem_por_grupo[g][2], g) for g in ordem_por_grupo]
    terceiros.sort(key=lambda tg: (stats[tg[0]]["pts"], stats[tg[0]]["gp"] - stats[tg[0]]["gc"],
                                   stats[tg[0]]["gp"], np.random.random()), reverse=True)
    melhores = terceiros[:8]
    custo = np.ones((8, 8))
    for i, (_, g) in enumerate(melhores):
        for j, slot in enumerate(slots_3):
            if g in slot[1:]:
                custo[i][j] = 0
    linhas, colunas = linear_sum_assignment(custo)
    return {slots_3[j]: melhores[i][0] for i, j in zip(linhas, colunas)}


def simular_grupos_detalhado(grupo_de, times_do_grupo, jogos_grupo, lambdas):
    """Fase de grupos detalhada: {grupo: {"jogos": [...], "classificacao": DataFrame PT}}."""
    stats, jogos_por_grupo, ordem = _disputar_grupos(grupo_de, times_do_grupo, jogos_grupo, lambdas)
    return {g: {"jogos": jogos_por_grupo[g], "classificacao": _classificacao_df(ordem[g], stats)}
            for g in times_do_grupo}


def simular_torneio_detalhado(grupo_de, times_do_grupo, jogos_grupo, calendario, lambdas, slots_3):
    """Simula o torneio INTEIRO uma vez e devolve grupos + mata-mata por rodada + campeão.

    Retorna dict com: ``grupos`` (como em simular_grupos_detalhado), ``mata_mata``
    ({round: [(casa, gc, gv, visit, vencedor, penaltis)]}), ``campeao``, ``vice`` e ``terceiro``.
    """
    stats, jogos_por_grupo, ordem = _disputar_grupos(grupo_de, times_do_grupo, jogos_grupo, lambdas)
    grupos = {g: {"jogos": jogos_por_grupo[g], "classificacao": _classificacao_df(ordem[g], stats)}
              for g in times_do_grupo}

    slots: dict[str, str] = {}
    for g in times_do_grupo:
        slots[f"1{g}"], slots[f"2{g}"] = ordem[g][0], ordem[g][1]
    slots.update(_resolver_terceiros(ordem, stats, slots_3))

    mata_mata: dict[str, list] = {}
    campeao = vice = terceiro = None
    for m in calendario:
        num = m["match_id"][1:]
        casa, visit = slots[m["home_slot"]], slots[m["away_slot"]]
        lc, lv = lambdas(casa, visit, NEUTRO_MATAMATA)
        gc, gv = _placar(lc, lv)
        penaltis = gc == gv
        if gc > gv:
            venc, perd = casa, visit
        elif gv > gc:
            venc, perd = visit, casa
        else:
            venc, perd = (casa, visit) if np.random.random() < 0.5 else (visit, casa)
        slots[f"W{num}"] = venc
        if isinstance(m["loser_advances_to"], str) and m["loser_advances_to"]:
            slots[f"RU{num}"] = perd
        mata_mata.setdefault(m["round"], []).append((casa, int(gc), int(gv), visit, venc, penaltis))
        if m["round"] == "Final":
            campeao, vice = venc, perd
        elif m["round"] == "3rd":
            terceiro = venc

    return {"grupos": grupos, "mata_mata": mata_mata, "campeao": campeao, "vice": vice, "terceiro": terceiro}


def simular_torneio(grupo_de, times_do_grupo, jogos_grupo, calendario, lambdas, slots_3):
    stats = {t: {"pts": 0, "saldo": 0, "gp": 0} for t in grupo_de}

    # --- Fase de grupos ---
    for casa, visit, neutro in jogos_grupo:
        lc, lv = lambdas(casa, visit, neutro)
        gc, gv = _placar(lc, lv)
        stats[casa]["gp"] += gc; stats[visit]["gp"] += gv
        stats[casa]["saldo"] += gc - gv; stats[visit]["saldo"] += gv - gc
        if gc > gv:
            stats[casa]["pts"] += 3
        elif gc < gv:
            stats[visit]["pts"] += 3
        else:
            stats[casa]["pts"] += 1; stats[visit]["pts"] += 1

    slots: dict[str, str] = {}
    terceiros = []
    for g, times in times_do_grupo.items():
        ordem = _classificar_grupo(times, stats)
        slots[f"1{g}"], slots[f"2{g}"] = ordem[0], ordem[1]
        terceiros.append((ordem[2], g))

    # --- 8 melhores terceiros → slots 3xxxx (matching por elegibilidade) ---
    terceiros.sort(key=lambda tg: (stats[tg[0]]["pts"], stats[tg[0]]["saldo"], stats[tg[0]]["gp"], np.random.random()),
                   reverse=True)
    melhores = terceiros[:8]
    custo = np.ones((8, 8))
    for i, (_, g) in enumerate(melhores):
        for j, slot in enumerate(slots_3):
            if g in slot[1:]:
                custo[i][j] = 0
    linhas, colunas = linear_sum_assignment(custo)
    for i, j in zip(linhas, colunas):
        slots[slots_3[j]] = melhores[i][0]

    # --- Fase máxima por seleção: base 1 para os 32 do mata-mata ---
    nivel = {t: 0 for t in grupo_de}
    for slot, time in slots.items():
        nivel[time] = max(nivel[time], 1)

    # --- Mata-mata (calendário já em ordem topológica) ---
    for m in calendario:
        num = m["match_id"][1:]
        casa, visit = slots[m["home_slot"]], slots[m["away_slot"]]
        lc, lv = lambdas(casa, visit, NEUTRO_MATAMATA)
        gc, gv = _placar(lc, lv)
        if gc > gv:
            venc, perd = casa, visit
        elif gv > gc:
            venc, perd = visit, casa
        else:
            venc, perd = (casa, visit) if np.random.random() < 0.5 else (visit, casa)  # pênaltis

        slots[f"W{num}"] = venc
        if m["round"] in NIVEL_VENCEDOR:
            nivel[venc] = max(nivel[venc], NIVEL_VENCEDOR[m["round"]])
        if isinstance(m["loser_advances_to"], str) and m["loser_advances_to"]:
            slots[f"RU{num}"] = perd

    return nivel


# --------------------------------------------------------------------------- #
# Agregação + persistência
# --------------------------------------------------------------------------- #
def gravar(df: pd.DataFrame) -> None:
    cols = ["selecao"] + COLS_PROB
    buf = io.StringIO()
    df[cols].to_csv(buf, index=False, header=False, na_rep="")
    buf.seek(0)
    conn = get_raw_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(DDL)
            cur.copy_expert(
                f"COPY gold_probabilidades_copa ({', '.join(cols)}) FROM STDIN WITH (FORMAT csv, NULL '')", buf
            )
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    np.random.seed(SEED)
    print("Preparando dados e modelos...")
    grupo_de, times_do_grupo, jogos_grupo, calendario, lambdas = preparar()
    slots_3 = slots_terceiros(calendario)

    # contagem[selecao] = nº de sims em que atingiu nível >= k, para k=1..6
    contagem = {t: np.zeros(6, dtype=int) for t in grupo_de}

    print(f"Simulando {N_SIMULACOES} torneios...")
    for _ in range(N_SIMULACOES):
        nivel = simular_torneio(grupo_de, times_do_grupo, jogos_grupo, calendario, lambdas, slots_3)
        for t, nv in nivel.items():
            if nv >= 1:
                contagem[t][:nv] += 1

    linhas = [{"selecao": t, **{c: contagem[t][k] / N_SIMULACOES for k, c in enumerate(COLS_PROB)}}
              for t in grupo_de]
    df = pd.DataFrame(linhas).sort_values("prob_campea", ascending=False)
    gravar(df)

    print("\n" + "=" * 64)
    print("RELATÓRIO MONTE CARLO — palpite da máquina (top 10 campeã)")
    print("=" * 64)
    print(f"  {'seleção':<22}{'grupo':>7}{'oitav':>7}{'quart':>7}{'semi':>7}{'final':>7}{'campeã':>8}")
    for _, r in df.head(10).iterrows():
        print(f"  {r['selecao']:<22}" + "".join(f"{r[c]*100:>6.1f}%" for c in COLS_PROB))
    print("=" * 64)
    print(f"  soma prob_campea = {df['prob_campea'].sum()*100:.1f}%  |  seleções: {len(df)}")
    print("\n✓ gold_probabilidades_copa concluída.")


if __name__ == "__main__":
    main()
