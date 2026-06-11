"""Feature 11 — Monte Carlo condicional + eliminação matemática.

A partir do estado REAL do torneio (resultados registrados em ``resultados_copa`` e
reconstruídos pela feature_10), simula **apenas os jogos restantes** N vezes e produz
probabilidades CONDICIONAIS por fase — mesma semântica da feature_08: se o Brasil perdeu
o 1º jogo, todas as simulações partem de 0 pontos reais e a probabilidade cai de forma
matematicamente justa. Também identifica seleções **matematicamente eliminadas** e grava
um snapshot append-only em ``gold_probabilidades_rodada`` a cada execução.

Estatística pura em Python: o LLM nunca calcula nada aqui.

Reuso (sem duplicação) de ``monte_carlo.py``: ``preparar`` (cache de λ via modelos .pkl,
``peso_torneio=3``, ``peso_recencia=1.0``), ``_classificar_grupo``, ``_resolver_terceiros``,
``slots_terceiros``, ``NIVEL_VENCEDOR``, ``COLS_PROB`` e ``NEUTRO_MATAMATA``.
O import de ``estado_torneio`` (feature_10) é **lazy** — feito dentro de ``executar`` —
para que este módulo carregue e seja testável mesmo sem a feature_10 presente
(``--sintetico`` usa um builder interno compatível com o contrato).
"""

from __future__ import annotations

import argparse
import io
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from db import get_engine, get_raw_connection
from monte_carlo import (
    COLS_PROB,
    NEUTRO_MATAMATA,
    NIVEL_VENCEDOR,
    SEED,
    _classificar_grupo,
    _resolver_terceiros,
    preparar,
    slots_terceiros,
)

N_PADRAO = 10_000

# Append-only: histórico de snapshots por rodada — NUNCA dropar.
DDL = """
CREATE TABLE IF NOT EXISTS gold_probabilidades_rodada (
    id             bigint generated always as identity primary key,
    rotulo_rodada  text NOT NULL,
    selecao        text NOT NULL,
    prob_grupo     double precision,
    prob_oitavas   double precision,
    prob_quartas   double precision,
    prob_semi      double precision,
    prob_final     double precision,
    prob_campea    double precision,
    eliminada      boolean,
    criado_em      timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_prob_rodada_rotulo
    ON gold_probabilidades_rodada (rotulo_rodada, selecao);
"""


# --------------------------------------------------------------------------- #
# Leitura do estado (duck-typing do contrato da feature_10)
# --------------------------------------------------------------------------- #
def _como_lista(colecao) -> list:
    """Normaliza dict (valores) ou lista — tolera variações do contrato da feature_10."""
    if colecao is None:
        return []
    if hasattr(colecao, "values") and callable(colecao.values):
        return list(colecao.values())
    return list(colecao)


def _partidas_grupos(estado) -> list:
    """Todas as ``Partida`` da fase de grupos (itera ``Grupo.partidas``)."""
    partidas = []
    for item in _como_lista(estado.grupos):
        partidas.extend(item.partidas if hasattr(item, "partidas") else [item])
    return partidas


def _partidas_mata_mata(estado) -> dict:
    """``Partida`` do mata-mata indexadas por ``match_id`` (M73..M104)."""
    partidas = []
    for item in _como_lista(estado.mata_mata):
        if hasattr(item, "match_id"):
            partidas.append(item)
        else:  # ex.: dict {fase: [partidas]}
            partidas.extend(item)
    return {p.match_id: p for p in partidas}


def _vencedor_real(partida, casa: str, visit: str) -> tuple[str, str]:
    """(vencedor, perdedor) de um jogo de mata-mata com resultado REAL registrado."""
    gols_c, gols_v = int(partida.gols_casa), int(partida.gols_visitante)
    if gols_c > gols_v:
        return casa, visit
    if gols_v > gols_c:
        return visit, casa
    venc = partida.penaltis_vencedor
    if venc not in (casa, visit):
        raise ValueError(f"{partida.match_id}: empate real sem penaltis_vencedor válido ({venc!r})")
    return (casa, visit) if venc == casa else (visit, casa)


def _stats_reais(partidas_grupo, times) -> dict:
    """Acumula pontos/saldo/gols REAIS dos jogos de grupo já realizados."""
    stats = {t: {"pts": 0, "saldo": 0, "gp": 0, "gc": 0} for t in times}
    for p in partidas_grupo:
        if p.gols_casa is None:
            continue
        gols_c, gols_v = int(p.gols_casa), int(p.gols_visitante)
        for t, marcou, sofreu in ((p.time_casa, gols_c, gols_v), (p.time_visitante, gols_v, gols_c)):
            stats[t]["gp"] += marcou
            stats[t]["gc"] += sofreu
            stats[t]["saldo"] += marcou - sofreu
        if gols_c > gols_v:
            stats[p.time_casa]["pts"] += 3
        elif gols_v > gols_c:
            stats[p.time_visitante]["pts"] += 3
        else:
            stats[p.time_casa]["pts"] += 1
            stats[p.time_visitante]["pts"] += 1
    return stats


# --------------------------------------------------------------------------- #
# Simulação condicional
# --------------------------------------------------------------------------- #
def _simular_restante(stats, times_do_grupo, calendario, lambdas, slots_3, reais_mm, times) -> dict:
    """Uma simulação do torneio a partir de ``stats`` (reais + sorteados) já consolidados.

    Mata-mata: confrontos reais já definidos são respeitados e jogos com resultado real
    registrado têm o vencedor FIXADO (não sorteia); o restante é simulado em sede neutra,
    empate → pênaltis 50/50. Devolve {selecao: nível máximo alcançado} (0..6).
    """
    ordem = {g: _classificar_grupo(ts, stats) for g, ts in times_do_grupo.items()}
    slots: dict[str, str] = {}
    for g in times_do_grupo:
        slots[f"1{g}"], slots[f"2{g}"] = ordem[g][0], ordem[g][1]
    slots.update(_resolver_terceiros(ordem, stats, slots_3))

    nivel = {t: 0 for t in times}
    for classificado in slots.values():
        nivel[classificado] = max(nivel[classificado], 1)

    for m in calendario:
        num = m["match_id"][1:]
        real = reais_mm.get(m["match_id"])
        if real is not None and real.time_casa and real.time_visitante:
            casa, visit = real.time_casa, real.time_visitante  # confronto real definido
            nivel[casa] = max(nivel[casa], 1)
            nivel[visit] = max(nivel[visit], 1)
        else:
            casa, visit = slots[m["home_slot"]], slots[m["away_slot"]]

        if real is not None and real.gols_casa is not None:
            venc, perd = _vencedor_real(real, casa, visit)  # resultado real FIXA o vencedor
        else:
            lam_c, lam_v = lambdas(casa, visit, NEUTRO_MATAMATA)
            gols_c, gols_v = np.random.poisson(lam_c), np.random.poisson(lam_v)
            if gols_c > gols_v:
                venc, perd = casa, visit
            elif gols_v > gols_c:
                venc, perd = visit, casa
            else:
                venc, perd = (casa, visit) if np.random.random() < 0.5 else (visit, casa)

        slots[f"W{num}"] = venc
        if m["round"] in NIVEL_VENCEDOR:
            nivel[venc] = max(nivel[venc], NIVEL_VENCEDOR[m["round"]])
        if isinstance(m["loser_advances_to"], str) and m["loser_advances_to"]:
            slots[f"RU{num}"] = perd
    return nivel


def simular_condicional(estado, n_simulacoes: int = N_PADRAO, seed: int = SEED) -> pd.DataFrame:
    """Simula os jogos restantes N vezes a partir do estado real acumulado.

    1. Stats REAIS (pontos, saldo, gols pró) dos jogos de grupo com placar entram como
       ponto de partida de TODAS as simulações.
    2. Só jogos com ``gols_casa IS NULL`` são sorteados via Poisson (λ do cache de
       ``monte_carlo.preparar``: modelos .pkl, peso_torneio=3, peso_recencia=1.0).
       A fase de grupos é sorteada **em lote** (matriz N × jogos_pendentes).
    3. Agrega frequências → ``prob_grupo .. prob_campea`` (semântica da feature_08).

    Devolve DataFrame (selecao + COLS_PROB) ordenado por ``prob_campea`` desc.
    """
    np.random.seed(seed)
    grupo_de, times_do_grupo, _, calendario, lambdas = preparar()
    slots_3 = slots_terceiros(calendario)
    times = sorted(grupo_de)
    idx = {t: k for k, t in enumerate(times)}

    partidas_grupo = _partidas_grupos(estado)
    reais_mm = _partidas_mata_mata(estado)
    stats0 = _stats_reais(partidas_grupo, times)
    pendentes = [(p.time_casa, p.time_visitante, bool(p.neutro))
                 for p in partidas_grupo if p.gols_casa is None]

    # --- Fase de grupos vetorizada: matrizes N × J de gols sorteados em lote ---
    n, n_pend = n_simulacoes, len(pendentes)
    pts = np.tile([stats0[t]["pts"] for t in times], (n, 1))
    saldo = np.tile([stats0[t]["saldo"] for t in times], (n, 1))
    gp = np.tile([stats0[t]["gp"] for t in times], (n, 1))
    gc = np.tile([stats0[t]["gc"] for t in times], (n, 1))
    if n_pend:
        lam = np.array([lambdas(c, v, ne) for c, v, ne in pendentes])  # J × 2
        gols_casa_sim = np.random.poisson(lam[:, 0], size=(n, n_pend))
        gols_visit_sim = np.random.poisson(lam[:, 1], size=(n, n_pend))
        for j, (casa, visit, _) in enumerate(pendentes):
            ci, vi = idx[casa], idx[visit]
            g_c, g_v = gols_casa_sim[:, j], gols_visit_sim[:, j]
            empate = g_c == g_v
            pts[:, ci] += 3 * (g_c > g_v) + empate
            pts[:, vi] += 3 * (g_v > g_c) + empate
            saldo[:, ci] += g_c - g_v
            saldo[:, vi] += g_v - g_c
            gp[:, ci] += g_c
            gp[:, vi] += g_v
            gc[:, ci] += g_v
            gc[:, vi] += g_c

    # --- Classificação + mata-mata por simulação ---
    contagem = {t: np.zeros(6, dtype=int) for t in times}
    for i in range(n):
        pr, sr, gpr, gcr = pts[i].tolist(), saldo[i].tolist(), gp[i].tolist(), gc[i].tolist()
        stats = {t: {"pts": pr[k], "saldo": sr[k], "gp": gpr[k], "gc": gcr[k]}
                 for k, t in enumerate(times)}
        nivel = _simular_restante(stats, times_do_grupo, calendario, lambdas, slots_3, reais_mm, times)
        for t, nv in nivel.items():
            if nv >= 1:
                contagem[t][:nv] += 1

    linhas = [{"selecao": t, **{c: contagem[t][k] / n for k, c in enumerate(COLS_PROB)}}
              for t in times]
    return pd.DataFrame(linhas).sort_values("prob_campea", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Eliminação matemática
# --------------------------------------------------------------------------- #
def eliminadas_matematicamente(estado, df_probs: pd.DataFrame) -> set[str]:
    """Seleções matematicamente eliminadas no estado atual do torneio.

    Fase de grupos — combinação de DOIS critérios (ambos precisam falhar):

    1. Analítico (exato para o top-2): conta quantos times do grupo já têm MAIS pontos
       reais do que o máximo alcançável pelo time (pontos reais + 3 × jogos restantes).
       Com 2 ou mais acima desse teto, nem vencendo tudo o time alcança o 2º lugar.
    2. ``prob_grupo == 0`` nas N simulações — cobre a vaga de **melhor 3º**, cuja análise
       combinatória exata é impraticável (depende dos placares de todos os 12 grupos).

    APROXIMAÇÃO documentada: o critério 2 é evidência Monte Carlo, não prova formal —
    um caminho de classificação que nunca apareceu em N simulações pode existir com
    probabilidade ínfima. Combinado com o critério 1 (que é exato para as duas vagas
    diretas), o erro fica restrito à vaga de melhor 3º em cenários extremos.

    Mata-mata — exato: perdeu jogo eliminatório com resultado REAL ⇒ eliminada.
    """
    prob_grupo = dict(zip(df_probs["selecao"], df_probs["prob_grupo"]))
    eliminadas: set[str] = set()

    for grupo in _como_lista(estado.grupos):
        times_g = list(grupo.times)
        pts = {t: 0 for t in times_g}
        restantes = {t: 0 for t in times_g}
        for p in grupo.partidas:
            if p.gols_casa is None:
                restantes[p.time_casa] += 1
                restantes[p.time_visitante] += 1
                continue
            gols_c, gols_v = int(p.gols_casa), int(p.gols_visitante)
            if gols_c > gols_v:
                pts[p.time_casa] += 3
            elif gols_v > gols_c:
                pts[p.time_visitante] += 3
            else:
                pts[p.time_casa] += 1
                pts[p.time_visitante] += 1
        for t in times_g:
            teto = pts[t] + 3 * restantes[t]
            acima = sum(1 for u in times_g if u != t and pts[u] > teto)
            if acima >= 2 and prob_grupo.get(t, 0.0) == 0.0:
                eliminadas.add(t)

    for p in _partidas_mata_mata(estado).values():
        if p.gols_casa is None or not p.time_casa or not p.time_visitante:
            continue
        _, perdedor = _vencedor_real(p, p.time_casa, p.time_visitante)
        eliminadas.add(perdedor)
    return eliminadas


# --------------------------------------------------------------------------- #
# Persistência (append-only via COPY)
# --------------------------------------------------------------------------- #
def gravar_snapshot(rotulo_rodada: str, df: pd.DataFrame) -> None:
    """Acrescenta o snapshot (48 linhas) em ``gold_probabilidades_rodada`` via COPY."""
    cols = ["rotulo_rodada", "selecao", *COLS_PROB, "eliminada"]
    saida = df.copy()
    saida["rotulo_rodada"] = rotulo_rodada
    buf = io.StringIO()
    saida[cols].to_csv(buf, index=False, header=False, na_rep="")
    buf.seek(0)
    conn = get_raw_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(DDL)
            cur.copy_expert(
                f"COPY gold_probabilidades_rodada ({', '.join(cols)}) FROM STDIN WITH (FORMAT csv, NULL '')",
                buf,
            )
        conn.commit()
    finally:
        conn.close()


def _snapshot_vigente():
    """Lote mais recente de ``gold_probabilidades_rodada`` (None se vazia/inexistente)."""
    try:
        df = pd.read_sql(
            """
            SELECT selecao, prob_campea, rotulo_rodada
            FROM gold_probabilidades_rodada
            WHERE rotulo_rodada = (
                SELECT rotulo_rodada FROM gold_probabilidades_rodada
                ORDER BY criado_em DESC, id DESC LIMIT 1
            )
            """,
            get_engine(),
        )
    except Exception:
        return None
    return df if len(df) else None


# --------------------------------------------------------------------------- #
# Builder de teste (estado sintético, compatível com o contrato da feature_10)
# --------------------------------------------------------------------------- #
@dataclass
class _Partida:
    """Clone mínimo do contrato ``Partida`` da feature_10 — SÓ para testes (--sintetico)."""

    match_id: str
    fase: str
    rodada: int | None
    grupo: str | None
    time_casa: str | None
    time_visitante: str | None
    gols_casa: int | None = None
    gols_visitante: int | None = None
    penaltis_vencedor: str | None = None
    neutro: bool = True


@dataclass
class _Grupo:
    letra: str
    times: list
    partidas: list


@dataclass
class _EstadoSintetico:
    grupos: dict
    mata_mata: dict

    def _todas(self) -> list:
        return [p for g in self.grupos.values() for p in g.partidas] + list(self.mata_mata.values())

    @property
    def jogos_pendentes(self) -> list:
        return [p for p in self._todas() if p.gols_casa is None]

    @property
    def jogos_realizados(self) -> list:
        return [p for p in self._todas() if p.gols_casa is not None]

    @property
    def fase_grupos_completa(self) -> bool:
        return all(p.gols_casa is not None for g in self.grupos.values() for p in g.partidas)


def _estado_sintetico(resultados: dict | None = None) -> _EstadoSintetico:
    """Monta um estado fake compatível com o contrato da feature_10, direto das fontes
    (``silver_copa2026`` no banco + grupos/calendário CSV) — sem ``estado_torneio.py``.

    ``resultados``: {match_id: (gols_casa, gols_visitante[, penaltis_vencedor])} ou
    {match_id: {campo: valor}} (forma livre — útil para fixar times de mata-mata).
    """
    grupos_df = pd.read_csv("data/grupos_copa2026.csv")
    grupo_de = dict(zip(grupos_df["nation"], grupos_df["group"]))
    jogos = pd.read_sql(
        "SELECT data, time_casa, time_visitante, neutro FROM silver_copa2026 ORDER BY data, id",
        get_engine(),
    )

    # M1..M72 por (data, id); rodada derivada por pares dentro do grupo (contrato feature_10).
    contagem = {g: 0 for g in grupos_df["group"].unique()}
    partidas_grupo: dict[str, list] = {g: [] for g in contagem}
    for i, jogo in enumerate(jogos.itertuples(index=False), start=1):
        g = grupo_de[jogo.time_casa]
        partidas_grupo[g].append(_Partida(
            match_id=f"M{i}", fase="Grupos", rodada=contagem[g] // 2 + 1, grupo=g,
            time_casa=jogo.time_casa, time_visitante=jogo.time_visitante, neutro=bool(jogo.neutro),
        ))
        contagem[g] += 1

    grupos = {
        g: _Grupo(letra=g, times=grupos_df.loc[grupos_df["group"] == g, "nation"].tolist(),
                  partidas=partidas_grupo[g])
        for g in partidas_grupo
    }
    mata_mata = {
        m.match_id: _Partida(match_id=m.match_id, fase=m.round, rodada=None, grupo=None,
                             time_casa=None, time_visitante=None, neutro=True)
        for m in pd.read_csv("data/calendario_copa2026.csv").itertuples(index=False)
    }

    por_id = {p.match_id: p for ps in partidas_grupo.values() for p in ps} | mata_mata
    for match_id, res in (resultados or {}).items():
        partida = por_id[match_id]
        if isinstance(res, dict):
            for campo, valor in res.items():
                setattr(partida, campo, valor)
        else:
            partida.gols_casa, partida.gols_visitante = res[0], res[1]
            partida.penaltis_vencedor = res[2] if len(res) > 2 else None
    return _EstadoSintetico(grupos=grupos, mata_mata=mata_mata)


# --------------------------------------------------------------------------- #
# Orquestração + CLI
# --------------------------------------------------------------------------- #
def executar(rotulo_rodada: str, n_simulacoes: int = N_PADRAO, seed: int = SEED,
             sintetico: bool = False, estado=None) -> pd.DataFrame:
    """Carrega estado → simula → marca eliminadas → grava snapshot (COPY) → devolve o DF.

    ``estado`` permite injetar um estado pronto (testes); ``sintetico`` usa o builder
    interno. Caso contrário importa ``estado_torneio`` (lazy — contrato da feature_10).
    """
    if estado is None:
        if sintetico:
            estado = _estado_sintetico()
        else:
            from estado_torneio import carregar_estado  # lazy: feature_10
            estado = carregar_estado()

    df = simular_condicional(estado, n_simulacoes=n_simulacoes, seed=seed)
    df["eliminada"] = df["selecao"].isin(eliminadas_matematicamente(estado, df))
    gravar_snapshot(rotulo_rodada, df)
    return df


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Monte Carlo condicional da Copa 2026 (snapshot por rodada).")
    parser.add_argument("--rodada", required=True,
                        help="rótulo do snapshot (ex.: pre_torneio, grupos_rodada_1, pos_oitavas)")
    parser.add_argument("--n", type=int, default=N_PADRAO, help="número de simulações")
    parser.add_argument("--seed", type=int, default=SEED, help="seed do gerador")
    parser.add_argument("--sintetico", action="store_true",
                        help="usa o builder de teste em vez de estado_torneio.carregar_estado")
    args = parser.parse_args()

    anterior = _snapshot_vigente()
    base = dict(zip(anterior["selecao"], anterior["prob_campea"])) if anterior is not None else {}
    rotulo_ant = anterior["rotulo_rodada"].iloc[0] if anterior is not None else None

    inicio = time.perf_counter()
    df = executar(args.rodada, n_simulacoes=args.n, seed=args.seed, sintetico=args.sintetico)
    duracao = time.perf_counter() - inicio

    print("\n" + "=" * 78)
    print(f"MONTE CARLO CONDICIONAL — rodada '{args.rodada}' (N={args.n}, seed={args.seed})")
    print("=" * 78)
    cabecalho_var = f"vs {rotulo_ant}" if rotulo_ant else "vs —"
    print(f"  {'seleção':<22}{'grupo':>7}{'oitav':>7}{'quart':>7}{'semi':>7}{'final':>7}"
          f"{'campeã':>8}  {cabecalho_var}")
    for _, r in df.head(10).iterrows():
        var = (f"{(r['prob_campea'] - base[r['selecao']]) * 100:+.1f}pp"
               if r["selecao"] in base else "—")
        print(f"  {r['selecao']:<22}" + "".join(f"{r[c] * 100:>6.1f}%" for c in COLS_PROB)
              + f"  {var:>8}")
    eliminadas = sorted(df.loc[df["eliminada"], "selecao"])
    print("-" * 78)
    print(f"  eliminadas matematicamente ({len(eliminadas)}): "
          + (", ".join(eliminadas) if eliminadas else "nenhuma"))
    print(f"  soma prob_campea = {df['prob_campea'].sum() * 100:.1f}%  |  seleções: {len(df)}"
          f"  |  tempo: {duracao:.1f}s")
    print("=" * 78)
    print(f"\n✓ snapshot '{args.rodada}' gravado em gold_probabilidades_rodada.")


if __name__ == "__main__":
    main()
