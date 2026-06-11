"""Specs 09 + feature_14 — Dashboard Streamlit do IAPredict (Copa 2026).

Quatro páginas: probabilidades pré-computadas (estável), simulação ao vivo (1 rodada
aleatória), explorador de partidas e o Agente ao vivo (feature_14: registrar resultados
reais, rodar o agente LangGraph com streaming e acompanhar probabilidades/bracket).
Lê o banco via DATABASE_URL e reaproveita os módulos de src/.

Rodar local:  streamlit run app.py
Deploy:       Streamlit Cloud (definir DATABASE_URL em Secrets).
"""

from __future__ import annotations

import os
import sys
import time
import uuid

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
# Página 4 — 🤖 Agente ao vivo (feature_14)
#
# Os módulos das features 10–13 (estado_torneio, agente) podem ainda não existir
# neste checkout: importamos de forma preguiçosa e degradamos graciosamente
# (aviso amigável + dados de demonstração) quando algum deles falta.
# --------------------------------------------------------------------------- #
FASES_BRACKET = ["R32", "R16", "QF", "SF", "3rd", "Final"]
ORDEM_FASES = {"Grupos": 0, "R32": 1, "R16": 2, "QF": 3, "SF": 4, "3rd": 5, "Final": 6}
ROTULOS_SUGERIDOS = [
    "grupos_rodada_1", "grupos_rodada_2", "grupos_rodada_3",
    "pos_r32", "pos_oitavas", "pos_quartas", "pos_semi", "pos_final", "pre_torneio",
]
ESTILO_ELIMINADA = "color: #9e9e9e; text-decoration: line-through"


def _importar_estado_torneio():
    """Import preguiçoso da feature_10; None se o módulo ainda não chegou."""
    try:
        import estado_torneio  # noqa: PLC0415

        return estado_torneio
    except ImportError:
        return None


@st.cache_resource
def _grafo_agente(stub: bool, brasil_lider: bool):
    """Grafo compilado da feature_12/13 (as flags participam da chave de cache).

    As variáveis de ambiente de demonstração precisam estar definidas ANTES do
    import (são lidas na carga do módulo) — o chamador cuida disso.
    """
    import agente  # noqa: PLC0415

    return agente.criar_agente()


# ----------------------------- consultas (cache) ---------------------------- #
@st.cache_data
def _ultimo_snapshot_rodada() -> pd.DataFrame:
    """Lote vigente de gold_probabilidades_rodada (linhas com max(criado_em))."""
    sql = """
        SELECT rotulo_rodada, selecao, prob_grupo, prob_oitavas, prob_quartas,
               prob_semi, prob_final, prob_campea, eliminada, criado_em
        FROM gold_probabilidades_rodada
        WHERE criado_em = (SELECT max(criado_em) FROM gold_probabilidades_rodada)
    """
    try:
        return pd.read_sql(sql, _engine())
    except Exception:
        return pd.DataFrame()


@st.cache_data
def _historico_rodadas() -> pd.DataFrame:
    """Último lote de cada rotulo_rodada — alimenta o gráfico de evolução."""
    sql = """
        SELECT p.rotulo_rodada, p.selecao, p.prob_campea, p.eliminada, p.criado_em
        FROM gold_probabilidades_rodada p
        JOIN (SELECT rotulo_rodada, max(criado_em) AS criado_em
              FROM gold_probabilidades_rodada GROUP BY rotulo_rodada) ult
          USING (rotulo_rodada, criado_em)
        ORDER BY p.criado_em
    """
    try:
        return pd.read_sql(sql, _engine())
    except Exception:
        return pd.DataFrame()


@st.cache_data
def _resultados_copa() -> pd.DataFrame:
    """Tabela operacional da live (somente leitura aqui): os 104 jogos."""
    sql = """
        SELECT match_id, fase, rodada, grupo, data, time_casa, time_visitante,
               gols_casa, gols_visitante, penaltis_vencedor, neutro
        FROM resultados_copa
    """
    try:
        return pd.read_sql(sql, _engine())
    except Exception:
        return pd.DataFrame()


@st.cache_data
def _execucoes_banco() -> pd.DataFrame:
    """Últimas execuções registradas pelo agente (tabela pode ainda não existir)."""
    sql = """
        SELECT rotulo_rodada, pergunta, narrativa, frase_palpiteiro, tools_chamadas, criado_em
        FROM agente_execucoes ORDER BY criado_em DESC LIMIT 10
    """
    try:
        return pd.read_sql(sql, _engine())
    except Exception:
        return pd.DataFrame()


@st.cache_data
def _slots_calendario() -> dict:
    """match_id → (home_slot, away_slot) do calendário — rótulos simbólicos do bracket."""
    try:
        cal = pd.read_csv("data/calendario_copa2026.csv")
        return {r.match_id: (r.home_slot, r.away_slot) for r in cal.itertuples()}
    except Exception:
        return {}


def _limpar_caches_live():
    """Invalida as consultas da página após registrar resultado ou rodar o agente."""
    for consulta in (_ultimo_snapshot_rodada, _historico_rodadas, _resultados_copa, _execucoes_banco):
        consulta.clear()


# ----------------------- fallbacks sem estado_torneio ----------------------- #
def _classificacao_fallback(df_copa: pd.DataFrame) -> dict:
    """Classificação dos grupos calculada direto de resultados_copa (leitura).

    Mesmo formato/colunas de estado_torneio.classificacao_grupos — usada apenas
    enquanto a feature_10 não está disponível neste checkout.
    """
    tabelas: dict[str, pd.DataFrame] = {}
    jogos = df_copa[df_copa["fase"] == "Grupos"]
    for grupo, sub in jogos.groupby("grupo"):
        times = sorted(set(sub["time_casa"]) | set(sub["time_visitante"]))
        stats = {t: {"jogos": 0, "vitorias": 0, "empates": 0, "derrotas": 0,
                     "gols_pro": 0, "gols_contra": 0} for t in times}
        for j in sub.dropna(subset=["gols_casa"]).itertuples():
            gc, gv = int(j.gols_casa), int(j.gols_visitante)
            for time_, pro, contra in ((j.time_casa, gc, gv), (j.time_visitante, gv, gc)):
                s = stats[time_]
                s["jogos"] += 1
                s["gols_pro"] += pro
                s["gols_contra"] += contra
                s["vitorias" if pro > contra else "empates" if pro == contra else "derrotas"] += 1
        tabela = pd.DataFrame([{"selecao": t, **s} for t, s in stats.items()])
        tabela["saldo_gols"] = tabela["gols_pro"] - tabela["gols_contra"]
        tabela["pontos"] = tabela["vitorias"] * 3 + tabela["empates"]
        tabela = tabela.sort_values(["pontos", "saldo_gols", "gols_pro", "selecao"],
                                    ascending=[False, False, False, True]).reset_index(drop=True)
        tabela.insert(0, "posicao", tabela.index + 1)
        tabelas[grupo] = tabela[["posicao", "selecao", "jogos", "vitorias", "empates",
                                 "derrotas", "gols_pro", "gols_contra", "saldo_gols", "pontos"]]
    return tabelas


# ------------------------- registro de resultados --------------------------- #
def _rotulo_jogo(p) -> str:
    fase = f"Grupo {p.grupo} · rodada {p.rodada}" if p.fase == "Grupos" else NOMES_RODADA.get(p.fase, p.fase)
    return f"{p.match_id} · {fase} — {com_bandeira(p.time_casa)} × {com_bandeira(p.time_visitante)}"


def _secao_registro(mod_estado):
    st.subheader("📋 Registrar resultado")
    if mod_estado is None:
        st.warning("O módulo `estado_torneio` (feature_10) ainda não está disponível neste "
                   "ambiente — o registro de resultados ficará habilitado assim que ele chegar. "
                   "Por enquanto a lista de jogos pendentes abaixo é somente leitura.")
        df = _resultados_copa()
        if df.empty:
            st.info("Tabela `resultados_copa` ainda não existe no banco.")
            return
        pendentes = df[df["gols_casa"].isna() & df["time_casa"].notna()].copy()
        pendentes["confronto"] = (pendentes["time_casa"].map(com_bandeira) + " × "
                                  + pendentes["time_visitante"].map(com_bandeira))
        st.caption(f"{len(pendentes)} jogos pendentes (modo leitura)")
        st.dataframe(pendentes[["match_id", "fase", "rodada", "grupo", "confronto"]],
                     width="stretch", hide_index=True, height=240)
        return

    try:
        estado = mod_estado.carregar_estado()
    except Exception as exc:  # banco fora do ar, seed ausente etc.
        st.error(f"Não foi possível carregar o estado do torneio: {exc}")
        return

    pendentes = [p for p in estado.jogos_pendentes if p.time_casa and p.time_visitante]
    if not estado.fase_grupos_completa:
        # mata-mata só é habilitado quando os 72 jogos de grupo estiverem completos
        pendentes = [p for p in pendentes if p.fase == "Grupos"]
    pendentes.sort(key=lambda p: (ORDEM_FASES.get(p.fase, 9), p.rodada or 0, int(p.match_id[1:])))

    realizados = len(estado.jogos_realizados)
    st.caption(f"{realizados} jogos registrados · {len(pendentes)} pendentes"
               + ("" if estado.fase_grupos_completa else " (mata-mata libera ao fim dos grupos)"))
    if not pendentes:
        st.success("🎉 Nenhum jogo pendente — todos os resultados disponíveis foram registrados!")
        return

    jogo = st.selectbox("Jogo pendente", pendentes, format_func=_rotulo_jogo)
    c1, c2 = st.columns(2)
    gols_casa = c1.number_input(f"Gols {com_bandeira(jogo.time_casa)}", min_value=0, max_value=20,
                                value=0, step=1, key="reg_gols_casa")
    gols_visitante = c2.number_input(f"Gols {com_bandeira(jogo.time_visitante)}", min_value=0,
                                     max_value=20, value=0, step=1, key="reg_gols_visitante")
    penaltis = None
    if jogo.fase != "Grupos" and gols_casa == gols_visitante:
        penaltis = st.selectbox("Vencedor nos pênaltis (mata-mata empatado)",
                                [jogo.time_casa, jogo.time_visitante], format_func=com_bandeira)

    if st.button("💾 Registrar resultado", type="primary"):
        try:
            # registrar_resultado já propaga os classificados automaticamente (feature_10)
            mod_estado.registrar_resultado(jogo.match_id, int(gols_casa), int(gols_visitante),
                                           penaltis_vencedor=penaltis)
        except Exception as exc:
            st.error(f"Falha ao registrar {jogo.match_id}: {exc}")
        else:
            _limpar_caches_live()
            st.success(f"Resultado de {jogo.match_id} registrado!")
            st.rerun()


# --------------------------- execução do agente ----------------------------- #
def _texto_conteudo(conteudo) -> str:
    """Extrai texto de um content de mensagem (string ou lista de blocos)."""
    if isinstance(conteudo, str):
        return conteudo
    if isinstance(conteudo, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in conteudo)
    return ""


def _stream_agente(grafo, entrada, config, status, tools_usadas: list):
    """Gerador p/ st.write_stream: emite tokens da narrativa e reporta tools no status.

    Um único passe com stream_mode=["updates", "messages"]: "updates" alimenta o
    st.status (tools chamadas/concluídas) e "messages" rende os tokens do LLM.
    """
    for modo, pedaco in grafo.stream(entrada, config, stream_mode=["updates", "messages"]):
        if modo == "updates":
            for no, delta in (pedaco or {}).items():
                if no == "palpiteiro":
                    status.write("🇧🇷 Modo Palpiteiro ativado — buscando notícias da Seleção…")
                mensagens = (delta or {}).get("messages", []) if isinstance(delta, dict) else []
                if not isinstance(mensagens, list):
                    mensagens = [mensagens]
                for msg in mensagens:
                    for tc in getattr(msg, "tool_calls", None) or []:
                        tools_usadas.append(tc.get("name", "?"))
                        status.write(f"🔧 Chamando tool `{tc.get('name', '?')}`")
                    if type(msg).__name__ == "ToolMessage":
                        nome = getattr(msg, "name", None) or "tool"
                        status.write(f"📦 `{nome}` respondeu ({len(str(msg.content))} caracteres)")
        else:  # "messages": (token, metadata)
            token, metadados = pedaco
            if (metadados or {}).get("langgraph_node") == "palpiteiro":
                continue  # a frase do Palpiteiro aparece destacada à parte
            if type(token).__name__ in ("AIMessageChunk", "AIMessage"):
                texto = _texto_conteudo(getattr(token, "content", ""))
                if texto:
                    yield texto


def _stub_palavras(texto: str):
    """Streaming fake (modo demonstração): palavra a palavra."""
    for palavra in texto.split(" "):
        yield palavra + " "
        time.sleep(0.02)


def _executar_stub_ui(pergunta: str, rotulo: str) -> tuple[str, str, list]:
    """Demonstração local quando o módulo `agente` (features 12–13) ainda não existe."""
    st.warning("⚠️ O módulo `agente` (features 12–13) ainda não está disponível — executando "
               "em **modo demonstração** com dados fictícios. A página integra automaticamente "
               "quando o módulo chegar.")
    tools_fake = ["consultar_estado_grupos", "atualizar_probabilidades", "listar_eliminados"]
    status = st.status("🤖 Agente (demonstração) trabalhando…", expanded=True)
    for nome in tools_fake:
        status.write(f"🔧 Chamando tool `{nome}` _(simulada)_")
        time.sleep(0.4)

    snapshot = _ultimo_snapshot_rodada()
    if not snapshot.empty:
        lider = snapshot.sort_values("prob_campea", ascending=False).iloc[0]
        contexto = (f"o último snapshot ({lider['rotulo_rodada']}) aponta "
                    f"{lider['selecao']} na frente com {lider['prob_campea'] * 100:.1f}% de título")
    else:
        contexto = "ainda não há snapshot em gold_probabilidades_rodada"
    narrativa_fake = (
        f"[demonstração] Pergunta recebida: \"{pergunta}\" (rodada {rotulo}). "
        f"Sem o agente real eu não consulto o LLM, mas {contexto}. Assim que as features "
        "12–13 forem integradas, esta área mostrará a narrativa de verdade, token a token, "
        "com as tools de estado, probabilidades e eliminados rodando ao vivo."
    )
    st.markdown("**Narrativa da rodada**")
    narrativa = st.write_stream(_stub_palavras(narrativa_fake))
    status.update(label="✅ Demonstração concluída — tools simuladas: " + ", ".join(tools_fake),
                  state="complete", expanded=False)
    frase = ("[demonstração] Respeita a Amarelinha: enquanto a matemática duvida, "
             "o coração do torcedor já contou até hexa. 🇧🇷")
    st.warning(f"🇧🇷 **Modo Palpiteiro:** {frase}")
    return str(narrativa), frase, tools_fake


def _executar_agente_ui(pergunta: str, rotulo: str, stub: bool, brasil_lider: bool):
    """Roda o agente com streaming (ou cai no modo demonstração) e guarda o histórico."""
    # Flags de demonstração precisam existir ANTES do import do módulo `agente`.
    if stub:
        os.environ["AGENTE_STUB"] = "1"
    if brasil_lider:
        os.environ["AGENTE_STUB_BRASIL_LIDER"] = "1"
    if "agente" in sys.modules and st.session_state.get("agente_flags") not in (None, (stub, brasil_lider)):
        st.info("O módulo `agente` já foi carregado com outras flags — reinicie o app "
                "para aplicar o novo modo de demonstração.")

    try:
        grafo = _grafo_agente(stub, brasil_lider)
    except ImportError:
        narrativa, frase, tools = _executar_stub_ui(pergunta, rotulo)
    except Exception as exc:
        st.warning(f"Não foi possível inicializar o agente ({exc}) — usando o modo demonstração.")
        narrativa, frase, tools = _executar_stub_ui(pergunta, rotulo)
    else:
        st.session_state["agente_flags"] = (stub, brasil_lider)
        thread_id = st.session_state.setdefault("agente_thread_id", f"live-{uuid.uuid4().hex[:8]}")
        config = {"configurable": {"thread_id": thread_id}}
        entrada = {"messages": [("user", pergunta)], "rotulo_rodada": rotulo}
        tools: list[str] = []
        status = st.status("🤖 Agente trabalhando…", expanded=True)
        st.markdown("**Narrativa da rodada**")
        try:
            narrativa = st.write_stream(_stream_agente(grafo, entrada, config, status, tools))
        except Exception as exc:
            status.update(label="❌ Erro durante a execução do agente", state="error")
            st.error(f"O agente falhou no meio do caminho: {exc}")
            return
        status.update(label="✅ Agente concluído — tools: " + (", ".join(dict.fromkeys(tools)) or "nenhuma"),
                      state="complete", expanded=False)
        frase = None
        try:  # frase do Palpiteiro fica no estado final do grafo (checkpointer da thread)
            frase = (grafo.get_state(config).values or {}).get("frase_palpiteiro")
        except Exception:
            pass
        if frase:
            st.warning(f"🇧🇷 **Modo Palpiteiro:** {frase}")

    st.session_state.setdefault("historico_agente", []).append({
        "rotulo": rotulo, "pergunta": pergunta, "narrativa": str(narrativa or ""),
        "frase": frase, "tools": list(dict.fromkeys(tools)),
    })
    _limpar_caches_live()  # snapshot/execução novos podem ter sido gravados pelas tools


def _secao_agente():
    st.subheader("🧠 Rodar o agente")
    pergunta = st.text_input("Pergunta para o agente",
                             placeholder="Atualize as probabilidades após a rodada 1")
    c1, c2 = st.columns([1.2, 1])
    rotulo = c1.selectbox("Rótulo da rodada", [*ROTULOS_SUGERIDOS, "(outro…)"])
    if rotulo == "(outro…)":
        rotulo = c2.text_input("Rótulo personalizado", value="grupos_rodada_1")
    with st.expander("Opções de demonstração (sem LLM)"):
        stub = st.checkbox("Modo stub — `AGENTE_STUB=1`")
        brasil_lider = st.checkbox("Simular Brasil líder — `AGENTE_STUB_BRASIL_LIDER=1`")

    if st.button("🤖 Rodar agente", type="primary"):
        pergunta_final = pergunta.strip() or f"Atualize as probabilidades da rodada {rotulo}"
        _executar_agente_ui(pergunta_final, rotulo, stub, brasil_lider)

    historico = st.session_state.get("historico_agente", [])
    if historico:
        with st.expander(f"🗂️ Histórico da sessão ({len(historico)} execuções)"):
            for h in reversed(historico):
                st.markdown(f"**{h['rotulo']}** — _{h['pergunta']}_")
                if h["tools"]:
                    st.caption("Tools: " + ", ".join(h["tools"]))
                st.write(h["narrativa"])
                if h["frase"]:
                    st.warning(f"🇧🇷 {h['frase']}")
                st.divider()

    execucoes = _execucoes_banco()
    if not execucoes.empty:
        with st.expander(f"🗄️ Execuções registradas no banco ({len(execucoes)})"):
            mostrar = execucoes.copy()
            mostrar["narrativa"] = mostrar["narrativa"].str.slice(0, 120) + "…"
            st.dataframe(mostrar[["rotulo_rodada", "pergunta", "narrativa", "tools_chamadas", "criado_em"]],
                         width="stretch", hide_index=True)


# ------------------------------ visualizações ------------------------------- #
def _tabela_grupo_estilizada(tabela: pd.DataFrame, prob_grupo: dict, eliminadas: set):
    """Classificação de um grupo com % de classificação e eliminadas em cinza + ❌."""
    t = tabela.copy().reset_index(drop=True)
    if prob_grupo:
        t["% classificação"] = t["selecao"].map(prob_grupo).mul(100).round(1)
    elim = t["selecao"].isin(eliminadas)
    t["selecao"] = t["selecao"].map(lambda s: ("❌ " if s in eliminadas else "") + com_bandeira(s))
    t = t.rename(columns={"selecao": "Seleção"})
    estilo = t.style.apply(
        lambda linha: [ESTILO_ELIMINADA if elim.loc[linha.name] else ""] * len(linha), axis=1,
    ).format(precision=1)
    return estilo


def _secao_grupos(mod_estado, snapshot: pd.DataFrame):
    st.header("🌍 Fase de grupos ao vivo")
    df_copa = _resultados_copa()
    tabelas = None
    if mod_estado is not None:
        try:
            tabelas = mod_estado.classificacao_grupos(mod_estado.carregar_estado())
        except Exception as exc:
            st.warning(f"`classificacao_grupos` falhou ({exc}) — usando o cálculo local.")
    if tabelas is None:
        if df_copa.empty:
            st.info("Sem dados de `resultados_copa` para montar a classificação.")
            return
        tabelas = _classificacao_fallback(df_copa)

    prob_grupo, eliminadas = {}, set()
    if snapshot.empty:
        st.caption("Sem snapshot em `gold_probabilidades_rodada` — rode o agente para "
                   "calcular a coluna “% classificação”.")
    else:
        prob_grupo = dict(zip(snapshot["selecao"], snapshot["prob_grupo"]))
        eliminadas = set(snapshot.loc[snapshot["eliminada"].fillna(False), "selecao"])

    letras = sorted(tabelas)
    colunas = st.columns(3)
    for i, letra in enumerate(letras):
        with colunas[i % 3], st.expander(f"Grupo {letra}", expanded=False):
            st.dataframe(_tabela_grupo_estilizada(tabelas[letra], prob_grupo, eliminadas),
                         width="stretch", hide_index=True)


def _secao_titulo(snapshot: pd.DataFrame):
    st.header("🏆 Probabilidades de título (snapshot vigente)")
    if snapshot.empty:
        st.info("Nenhum snapshot ainda — registre uma rodada e rode o agente.")
        return
    df = snapshot.sort_values("prob_campea", ascending=False)
    top = df.head(TOP_N)
    if "Brazil" not in set(top["selecao"]):  # Brazil sempre presente no gráfico
        top = pd.concat([top, df[df["selecao"] == "Brazil"]])
    top = top.copy()
    top["pct"] = (top["prob_campea"] * 100).round(1)
    top["eh_brasil"] = top["selecao"] == "Brazil"
    top["rotulo"] = top["selecao"].map(com_bandeira)
    st.caption(f"Rodada: `{df['rotulo_rodada'].iloc[0]}` · top {TOP_N} + Brazil em destaque")
    grafico = (
        alt.Chart(top)
        .mark_bar()
        .encode(
            x=alt.X("pct:Q", title="% de campeã"),
            y=alt.Y("rotulo:N", sort="-x", title=None),
            color=alt.condition(alt.datum.eh_brasil, alt.value("#009739"), alt.value("#4c78a8")),
            tooltip=[alt.Tooltip("rotulo:N", title="Seleção"), alt.Tooltip("pct:Q", title="% campeã")],
        )
    )
    st.altair_chart(grafico, use_container_width=True)


def _linha_bracket(jogo, slots: dict) -> str:
    """Uma linha do chaveamento: slots simbólicos, confronto definido ou placar final."""
    casa, visitante = jogo.time_casa, jogo.time_visitante
    if pd.isna(casa) or casa is None:  # ainda sem classificados propagados
        home_slot, away_slot = slots.get(jogo.match_id, ("?", "?"))
        return f"`{jogo.match_id}` _{home_slot} × {away_slot}_"
    if pd.isna(jogo.gols_casa):
        return f"`{jogo.match_id}` {com_bandeira(casa)} × {com_bandeira(visitante)}"
    gols_casa, gols_visitante = int(jogo.gols_casa), int(jogo.gols_visitante)
    penaltis = isinstance(jogo.penaltis_vencedor, str) and bool(jogo.penaltis_vencedor)
    if gols_casa > gols_visitante:
        vencedor = casa
    elif gols_visitante > gols_casa:
        vencedor = visitante
    else:
        vencedor = jogo.penaltis_vencedor
    return f"`{jogo.match_id}` " + _placar_md(casa, gols_casa, gols_visitante, visitante, vencedor, penaltis)


def _secao_bracket():
    st.header("🏟️ Mata-mata — chaveamento (M73–M104)")
    df = _resultados_copa()
    if df.empty:
        st.info("Tabela `resultados_copa` ainda não existe no banco.")
        return
    mata_mata = df[df["fase"] != "Grupos"].copy()
    mata_mata["num"] = mata_mata["match_id"].str[1:].astype(int)
    mata_mata = mata_mata.sort_values("num")
    slots = _slots_calendario()
    colunas = st.columns(len(FASES_BRACKET))
    for coluna, fase in zip(colunas, FASES_BRACKET):
        coluna.markdown(f"**{NOMES_RODADA.get(fase, fase)}**")
        for jogo in mata_mata[mata_mata["fase"] == fase].itertuples():
            coluna.markdown(_linha_bracket(jogo, slots))


def _secao_evolucao():
    st.header("📈 Evolução da % de campeã por rodada")
    historico = _historico_rodadas()
    if historico.empty:
        st.info("O gráfico aparece após o primeiro snapshot de `gold_probabilidades_rodada`.")
        return
    # rótulos no eixo X na ordem cronológica dos lotes
    ordem = (historico.groupby("rotulo_rodada")["criado_em"].max()
             .sort_values().index.tolist())
    ultimo = historico[historico["rotulo_rodada"] == ordem[-1]]
    top5 = ultimo.sort_values("prob_campea", ascending=False).head(5)["selecao"].tolist()
    selecoes = list(dict.fromkeys([*top5, "Brazil"]))
    df = historico[historico["selecao"].isin(selecoes)].copy()
    df["pct"] = (df["prob_campea"] * 100).round(1)
    df["eh_brasil"] = df["selecao"] == "Brazil"
    df["rotulo"] = df["selecao"].map(com_bandeira)
    grafico = (
        alt.Chart(df)
        .mark_line(point=True)
        .encode(
            x=alt.X("rotulo_rodada:N", sort=ordem, title="Rodada"),
            y=alt.Y("pct:Q", title="% de campeã"),
            color=alt.Color("rotulo:N", title=None),
            size=alt.condition(alt.datum.eh_brasil, alt.value(4), alt.value(2)),
            tooltip=[alt.Tooltip("rotulo:N", title="Seleção"),
                     alt.Tooltip("rotulo_rodada:N", title="Rodada"),
                     alt.Tooltip("pct:Q", title="% campeã")],
        )
    )
    st.altair_chart(grafico, use_container_width=True)


def pagina_agente_ao_vivo():
    st.title("🤖 Agente ao vivo — Copa 2026")
    st.caption("Registre os placares reais da rodada, dispare o agente e acompanhe ao vivo: "
               "classificação com % de vaga, favoritas ao título, bracket e a frase do Palpiteiro.")
    mod_estado = _importar_estado_torneio()

    col_registro, col_agente = st.columns([1, 1.4])
    with col_registro:
        _secao_registro(mod_estado)
    with col_agente:
        _secao_agente()

    st.divider()
    snapshot = _ultimo_snapshot_rodada()
    _secao_grupos(mod_estado, snapshot)
    _secao_titulo(snapshot)
    _secao_bracket()
    _secao_evolucao()


# --------------------------------------------------------------------------- #
# Navegação
# --------------------------------------------------------------------------- #
PAGINAS = {
    "Probabilidades pré-computadas": pagina_probabilidades,
    "Simulação ao vivo": pagina_simulacao,
    "Explorador de partidas": pagina_explorador,
    "🤖 Agente ao vivo": pagina_agente_ao_vivo,
}

escolha = st.sidebar.radio("Escolha a página", list(PAGINAS))
st.sidebar.caption("IAPredict — pipeline de ML da Copa 2026")
PAGINAS[escolha]()
