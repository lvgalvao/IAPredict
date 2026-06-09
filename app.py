"""Spec 09 — Dashboard Streamlit do IAPredict (Copa 2026).

Três páginas: probabilidades pré-computadas (estável), simulação ao vivo (1 rodada aleatória)
e explorador de partidas. Lê o banco via DATABASE_URL e reaproveita os módulos de src/.

Rodar local:  streamlit run app.py
Deploy:       Streamlit Cloud (definir DATABASE_URL em Secrets).
"""

from __future__ import annotations

import os
import sys

import altair as alt
import pandas as pd
import streamlit as st

# Os módulos de src/ usam imports "flat" (from db import ...); replicamos o padrão.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# Ponte de segredo: no Streamlit Cloud a connection string vem de st.secrets; localmente do .env.
# Acessar st.secrets sem secrets.toml pode lançar erro — daí o try/except.
try:
    if "DATABASE_URL" in st.secrets and "DATABASE_URL" not in os.environ:
        os.environ["DATABASE_URL"] = st.secrets["DATABASE_URL"]
except Exception:
    pass

from db import get_engine  # noqa: E402
from previsao import PESO_TORNEIO_COPA, carregar_modelos, prever_jogo  # noqa: E402
from monte_carlo import NOMES_RODADA, preparar, simular_torneio_detalhado, slots_terceiros  # noqa: E402
from bandeiras import bandeira, com_bandeira  # noqa: E402

TOP_N = 12  # quantas seleções mostrar na página de probabilidades

st.set_page_config(page_title="IAPredict — Copa 2026", layout="wide")

FASES_PT = {
    "prob_grupo": "Passa do grupo", "prob_oitavas": "Oitavas", "prob_quartas": "Quartas",
    "prob_semi": "Semi", "prob_final": "Final", "prob_campea": "Campeã",
}


# --------------------------------------------------------------------------- #
# Recursos cacheados
# --------------------------------------------------------------------------- #
@st.cache_resource
def _engine():
    return get_engine()


@st.cache_resource
def _modelos_e_elos():
    modelo_casa, modelo_visit, _ = carregar_modelos()
    elos = dict(pd.read_sql("SELECT selecao, elo FROM silver_elo_atual", _engine()).itertuples(index=False, name=None))
    return modelo_casa, modelo_visit, elos


@st.cache_resource
def _preparacao_torneio():
    return preparar()


@st.cache_data
def _probabilidades() -> pd.DataFrame:
    return pd.read_sql("SELECT * FROM gold_probabilidades_copa ORDER BY prob_campea DESC", _engine())


# --------------------------------------------------------------------------- #
# Páginas
# --------------------------------------------------------------------------- #
def pagina_probabilidades():
    st.title("🏆 Quem leva a taça? — Copa 2026")
    st.caption(f"As {TOP_N} seleções com maior chance de título, da maior para a menor "
               "(1000 simulações de Monte Carlo).")
    df = _probabilidades().head(TOP_N).copy()
    df["selecao"] = df["selecao"].map(com_bandeira)

    st.subheader("Favoritas ao título (% de campeã)")
    favoritas = df[["selecao", "prob_campea"]].copy()
    favoritas["pct"] = (favoritas["prob_campea"] * 100).round(1)
    grafico = (
        alt.Chart(favoritas)
        .mark_bar()
        .encode(
            x=alt.X("pct:Q", title="% de campeã"),
            y=alt.Y("selecao:N", sort="-x", title=None),  # ordena pela %, maior no topo
            tooltip=[alt.Tooltip("selecao:N", title="Seleção"), alt.Tooltip("pct:Q", title="% campeã")],
        )
    )
    st.altair_chart(grafico, use_container_width=True)

    st.subheader(f"Probabilidade por fase — top {TOP_N}")
    tabela = df.rename(columns=FASES_PT).copy()
    for col in FASES_PT.values():
        tabela[col] = (tabela[col] * 100).round(1)
    st.dataframe(
        tabela[["selecao", *FASES_PT.values()]].rename(columns={"selecao": "Seleção"}),
        width="stretch", hide_index=True,
    )


def _placar_md(casa, gc, gv, visit, vencedor, penaltis):
    """Linha de placar do mata-mata, com bandeiras, vencedor em negrito e marca de pênaltis."""
    nome_casa = f"**{com_bandeira(casa)}**" if vencedor == casa else com_bandeira(casa)
    nome_visit = f"**{com_bandeira(visit)}**" if vencedor == visit else com_bandeira(visit)
    pen = " _(pên.)_" if penaltis else ""
    return f"{nome_casa} {gc} - {gv} {nome_visit}{pen}"


def pagina_simulacao():
    st.title("🎲 Simulação ao vivo")
    st.caption("Uma Copa inteira simulada do zero — grupos, mata-mata e campeão. "
               "Muda a cada clique; é aleatória, não é o palpite final.")
    if st.button("🔄 Simular novamente"):
        pass  # o clique já re-executa o script

    grupo_de, times_do_grupo, jogos_grupo, calendario, lambdas = _preparacao_torneio()
    slots_3 = slots_terceiros(calendario)
    r = simular_torneio_detalhado(grupo_de, times_do_grupo, jogos_grupo, calendario, lambdas, slots_3)

    # Campeão em destaque + pódio.
    st.success(f"🏆 Campeã: **{com_bandeira(r['campeao'])}**")
    c1, c2, c3 = st.columns(3)
    c1.metric("🥇 Campeã", com_bandeira(r["campeao"]))
    c2.metric("🥈 Vice", com_bandeira(r["vice"]))
    c3.metric("🥉 Terceiro", com_bandeira(r["terceiro"]))

    # Mata-mata por rodada (na ordem do calendário: 32-avos → ... → 3º → Final).
    st.header("Mata-mata")
    for rodada, jogos in r["mata_mata"].items():
        st.markdown(f"### {NOMES_RODADA.get(rodada, rodada)}")
        for jogo in jogos:
            st.write(_placar_md(*jogo))

    # Fase de grupos (recolhida, para não competir com o mata-mata).
    st.header("Fase de grupos")
    for grupo in sorted(r["grupos"]):
        with st.expander(f"Grupo {grupo}"):
            col_jogos, col_tabela = st.columns([1, 1.3])
            with col_jogos:
                for casa, gc, gv, visit in r["grupos"][grupo]["jogos"]:
                    st.write(f"{com_bandeira(casa)} **{gc} - {gv}** {com_bandeira(visit)}")
            with col_tabela:
                tabela = r["grupos"][grupo]["classificacao"].copy()
                tabela["selecao"] = tabela["selecao"].map(com_bandeira)
                st.dataframe(tabela, width="stretch", hide_index=True)


def pagina_explorador():
    st.title("🔍 Explorador de partidas")
    st.caption("Escolha dois times e veja os gols esperados (xG) e as probabilidades de resultado.")
    modelo_casa, modelo_visit, elos = _modelos_e_elos()
    times = sorted(elos)

    c1, c2 = st.columns(2)
    casa = c1.selectbox("Mandante", times, format_func=com_bandeira,
                        index=times.index("Brazil") if "Brazil" in times else 0)
    fora = c2.selectbox("Visitante", times, format_func=com_bandeira,
                        index=times.index("Spain") if "Spain" in times else 1)
    neutro = st.checkbox("Campo neutro", value=True)

    if st.button("Prever"):
        if casa == fora:
            st.warning("Escolha duas seleções diferentes.")
            return
        p = prever_jogo(casa, fora, neutro, PESO_TORNEIO_COPA,
                        elos=elos, modelo_casa=modelo_casa, modelo_visit=modelo_visit)
        c1.metric(f"xG {com_bandeira(casa)}", round(p["gols_esperados_casa"], 2))
        c2.metric(f"xG {com_bandeira(fora)}", round(p["gols_esperados_visitante"], 2))
        st.subheader("Probabilidades de resultado")
        p1, p2, p3 = st.columns(3)
        p1.metric(f"Vitória {com_bandeira(casa)}", f"{p['prob_vitoria']*100:.1f}%")
        p2.metric("Empate", f"{p['prob_empate']*100:.1f}%")
        p3.metric(f"Vitória {com_bandeira(fora)}", f"{p['prob_derrota']*100:.1f}%")


# --------------------------------------------------------------------------- #
# Navegação
# --------------------------------------------------------------------------- #
PAGINAS = {
    "Probabilidades pré-computadas": pagina_probabilidades,
    "Simulação ao vivo": pagina_simulacao,
    "Explorador de partidas": pagina_explorador,
}

escolha = st.sidebar.radio("Escolha a página", list(PAGINAS))
st.sidebar.caption("IAPredict — pipeline de ML da Copa 2026")
PAGINAS[escolha]()
