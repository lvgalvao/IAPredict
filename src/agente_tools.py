"""Features 12-13 — Tools do agente orquestrador da Copa 2026.

Quatro tools LangChain (`@tool`) que o LLM pode chamar — o LLM **nunca calcula nada**,
todo número vem daqui:

1. ``consultar_estado_grupos``   — classificação real dos grupos + jogos pendentes.
2. ``atualizar_probabilidades``  — dispara o Monte Carlo condicional e devolve o ranking.
3. ``listar_eliminados``         — seleções matematicamente eliminadas + motivo resumido.
4. ``buscar_noticias_selecao``   — notícias recentes da Seleção Brasileira (Tavily).

Context engineering (regra do idea.md): retornos enxutos em JSON compacto — top 12 do
ranking **+ Brazil sempre incluído** (com a posição), percentuais com 1 casa decimal,
sem despejar as 48 seleções nem colunas cruas no contexto do LLM.

Desenvolvimento por contrato (features 10-11 em paralelo): ``estado_torneio`` e
``monte_carlo_condicional`` são importados de forma *lazy* dentro de cada tool; se ainda
não existirem (ImportError) — ou se ``AGENTE_STUB=1`` — a tool cai no **modo stub**, com
dados fake realistas no MESMO formato JSON do contrato. ``AGENTE_STUB_BRASIL_LIDER=1``
força o cenário alternativo com o Brasil em 1º (teste do Modo Palpiteiro desativado).
"""

from __future__ import annotations

import csv
import json
import os
import sys

from dotenv import load_dotenv
from langchain_core.tools import tool

load_dotenv()

# --------------------------------------------------------------------------- #
# Modo stub (desenvolvimento por contrato com as features 10-11)
# --------------------------------------------------------------------------- #
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ARQUIVO_GRUPOS = os.path.join(_RAIZ, "data", "grupos_copa2026.csv")


def _stub_forcado() -> bool:
    """True quando o ambiente força o modo stub (testes sem as features 10-11)."""
    return os.getenv("AGENTE_STUB", "") == "1" or os.getenv("AGENTE_STUB_BRASIL_LIDER", "") == "1"


def _avisar_stub(tool_nome: str) -> None:
    print(f"[stub] {tool_nome}: usando dados fake (features 10-11 indisponíveis ou AGENTE_STUB=1)",
          file=sys.stderr)


def _grupos_oficiais() -> dict[str, list[str]]:
    """Grupos reais da Copa 2026 (A..L → 4 seleções), lidos do seed do repositório."""
    grupos: dict[str, list[str]] = {}
    with open(_ARQUIVO_GRUPOS, encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            grupos.setdefault(linha["group"], []).append(linha["nation"])
    return grupos


# Cenário stub: 2 rodadas registradas. Brasil perdeu para Morocco (2º do grupo C);
# New Zealand e Jordan estão matematicamente eliminadas (0 ponto, saldo afundado).
_STUB_RANKING = [
    ("Spain", 0.158), ("France", 0.132), ("England", 0.109), ("Brazil", 0.097),
    ("Argentina", 0.090), ("Germany", 0.076), ("Portugal", 0.064), ("Netherlands", 0.051),
    ("Italy", 0.038), ("Belgium", 0.030), ("Croatia", 0.025), ("Uruguay", 0.021),
    ("Morocco", 0.018), ("Colombia", 0.016), ("Japan", 0.012), ("Mexico", 0.010),
]
_STUB_RANKING_BRASIL_LIDER = [
    ("Brazil", 0.183), ("Spain", 0.149), ("France", 0.121), ("England", 0.098),
    ("Argentina", 0.087), ("Germany", 0.071), ("Portugal", 0.060), ("Netherlands", 0.048),
    ("Italy", 0.036), ("Belgium", 0.028), ("Croatia", 0.023), ("Uruguay", 0.020),
    ("Morocco", 0.017), ("Colombia", 0.015), ("Japan", 0.011), ("Mexico", 0.009),
]
_STUB_ELIMINADAS = {
    "New Zealand": "0 ponto em 2 jogos e saldo -6 no Grupo G; nem vencendo a última rodada "
                   "alcança o 2º lugar nem a vaga de melhor 3º (0.0% de classificação nas simulações)",
    "Jordan": "0 ponto em 2 jogos e saldo -5 no Grupo J; sem combinação de resultados restantes "
              "que dê vaga (0.0% de classificação nas simulações)",
}


def _stub_ranking_completo() -> list[dict]:
    """Ranking fake de prob_campea para as 48 seleções (soma ≈ 1.0), ordenado."""
    explicitas = (_STUB_RANKING_BRASIL_LIDER
                  if os.getenv("AGENTE_STUB_BRASIL_LIDER", "") == "1" else _STUB_RANKING)
    nomes_explicitos = {s for s, _ in explicitas}
    todas = [s for times in _grupos_oficiais().values() for s in times]
    restantes = [s for s in todas if s not in nomes_explicitos]
    sobra = max(0.0, 1.0 - sum(p for _, p in explicitas))
    por_resto = sobra / len(restantes) if restantes else 0.0
    ranking = [{"selecao": s, "prob_campea": p, "eliminada": s in _STUB_ELIMINADAS}
               for s, p in explicitas]
    ranking += [{"selecao": s, "prob_campea": round(por_resto, 4), "eliminada": s in _STUB_ELIMINADAS}
                for s in restantes]
    ranking.sort(key=lambda r: r["prob_campea"], reverse=True)
    for i, r in enumerate(ranking, start=1):
        r["posicao"] = i
    return ranking


def _stub_classificacao() -> dict[str, list[dict]]:
    """Classificação fake (2 rodadas jogadas) coerente com o ranking e as eliminadas do stub."""
    # Padrões (pts, gp, gc) por posição na ordem do grupo: líder, vice, 3º, 4º.
    padrao = [(6, 4, 1), (4, 3, 2), (1, 1, 3), (0, 0, 2)]
    grupos = _grupos_oficiais()
    ordem_especial = {
        # Brasil perdeu de virada para o Morocco e venceu o Haiti: 2º do grupo C.
        "C": (["Morocco", "Brazil", "Scotland", "Haiti"], [(6, 4, 1), (3, 3, 2), (3, 2, 3), (0, 0, 3)]),
        # Lanternas matematicamente eliminadas (saldo afundado).
        "G": (["Belgium", "Egypt", "Iran", "New Zealand"], [(6, 5, 0), (4, 3, 1), (1, 1, 2), (0, 0, 6)]),
        "J": (["Argentina", "Algeria", "Austria", "Jordan"], [(6, 5, 1), (4, 3, 1), (1, 1, 2), (0, 0, 5)]),
    }
    classificacao: dict[str, list[dict]] = {}
    for letra, times in sorted(grupos.items()):
        ordem, stats = ordem_especial.get(letra, (times, padrao))
        classificacao[letra] = [
            {"pos": i + 1, "selecao": t, "pts": pts, "j": 2, "sg": gp - gc, "gp": gp}
            for i, (t, (pts, gp, gc)) in enumerate(zip(ordem, stats))
        ]
    return classificacao


# --------------------------------------------------------------------------- #
# Helpers de context engineering (compartilhados pelo modo real e pelo stub)
# --------------------------------------------------------------------------- #
def _json_compacto(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _pct(fracao) -> str:
    """Fração 0-1 → percentual com 1 casa decimal (ex.: 0.097 → '9.7%')."""
    return f"{float(fracao) * 100:.1f}%"


def _ranking_compacto(ranking: list[dict]) -> dict:
    """Top 12 do ranking de prob_campea + Brazil SEMPRE incluído (com a posição)."""
    topo = [{"pos": r["posicao"], "selecao": r["selecao"], "prob_campea": _pct(r["prob_campea"])}
            for r in ranking[:12]]
    brasil = next((r for r in ranking if r["selecao"] == "Brazil"), None)
    saida = {"ranking_campea_top12": topo, "total_selecoes": len(ranking)}
    if brasil:
        saida["brasil"] = {"pos": brasil["posicao"], "prob_campea": _pct(brasil["prob_campea"]),
                           "eliminada": bool(brasil.get("eliminada", False))}
    return saida


def obter_ranking_vigente() -> list[dict]:
    """Ranking vigente de prob_campea — função ÚNICA usada pelas tools e pelo nó
    determinístico ``verificar_palpiteiro`` do grafo (feature_13).

    Respeita o flag de stub: com ``AGENTE_STUB=1`` (ou ``AGENTE_STUB_BRASIL_LIDER=1``)
    devolve o ranking fake; caso contrário consulta o último snapshot (lote com
    ``max(criado_em)``) de ``gold_probabilidades_rodada``. Sem snapshot → lista vazia.

    Retorno: ``[{posicao, selecao, prob_campea (fração 0-1), eliminada}, ...]`` ordenado.
    """
    if _stub_forcado():
        return _stub_ranking_completo()
    try:
        import pandas as pd

        from db import get_engine

        df = pd.read_sql(
            """
            SELECT selecao, prob_campea, eliminada
            FROM gold_probabilidades_rodada
            WHERE criado_em = (SELECT max(criado_em) FROM gold_probabilidades_rodada)
            ORDER BY prob_campea DESC
            """,
            get_engine(),
        )
    except Exception as exc:  # tabela ainda não existe / banco indisponível
        print(f"[aviso] obter_ranking_vigente: sem snapshot disponível ({exc})", file=sys.stderr)
        return []
    return [{"posicao": i + 1, "selecao": r.selecao, "prob_campea": float(r.prob_campea),
             "eliminada": bool(r.eliminada)} for i, r in enumerate(df.itertuples(index=False))]


# --------------------------------------------------------------------------- #
# Tool 1 — estado real dos grupos
# --------------------------------------------------------------------------- #
@tool
def consultar_estado_grupos() -> str:
    """Consulta o estado REAL e atual da fase de grupos da Copa 2026.

    Use esta tool SEMPRE que precisar saber como estão os grupos de verdade: a
    classificação oficial de cada grupo (A a L) com pontos, jogos, saldo de gols e
    gols pró de cada seleção, além de quantos jogos já foram realizados e quantos
    ainda estão pendentes. É o ponto de partida típico antes de atualizar
    probabilidades ou narrar uma rodada.

    Não recebe argumentos.

    Retorna JSON compacto com:
    - "jogos_realizados" / "jogos_pendentes": contagem de partidas;
    - "fase_grupos_completa": se os 72 jogos de grupos já têm placar;
    - "grupos": {letra: [{pos, selecao, pts, j, sg, gp}, ...]} — classificação
      ordenada (pontos → saldo → gols pró) de cada grupo.
    """
    try:
        if _stub_forcado():
            raise ImportError("AGENTE_STUB=1")
        from estado_torneio import carregar_estado, classificacao_grupos
    except ImportError:
        _avisar_stub("consultar_estado_grupos")
        return _json_compacto({
            "jogos_realizados": 48, "jogos_pendentes": 56, "fase_grupos_completa": False,
            "grupos": _stub_classificacao(),
        })

    estado = carregar_estado()
    tabelas = classificacao_grupos(estado)  # dict[str, DataFrame] (colunas em português)
    grupos = {
        letra: [{"pos": int(r.posicao), "selecao": str(r.selecao), "pts": int(r.pontos),
                 "j": int(r.jogos), "sg": int(r.saldo_gols), "gp": int(r.gols_pro)}
                for r in df.itertuples(index=False)]
        for letra, df in sorted(tabelas.items())
    }
    pendentes, realizados = estado.jogos_pendentes, estado.jogos_realizados
    return _json_compacto({
        "jogos_realizados": realizados if isinstance(realizados, int) else len(realizados),
        "jogos_pendentes": pendentes if isinstance(pendentes, int) else len(pendentes),
        "fase_grupos_completa": bool(estado.fase_grupos_completa),
        "grupos": grupos,
    })


# --------------------------------------------------------------------------- #
# Tool 2 — Monte Carlo condicional
# --------------------------------------------------------------------------- #
@tool
def atualizar_probabilidades(rotulo_rodada: str, n_simulacoes: int = 10000) -> str:
    """Recalcula as probabilidades do torneio com o Monte Carlo CONDICIONAL e grava
    o snapshot oficial no banco (``gold_probabilidades_rodada``).

    Use esta tool sempre que resultados novos tiverem sido registrados (ex.: o
    usuário disse que registrou a rodada 1) ou quando precisar das probabilidades
    atualizadas de título/classificação. A simulação parte do estado REAL acumulado
    e simula apenas os jogos restantes — estatística pura, nada de estimativas.

    Args:
        rotulo_rodada: rótulo do snapshot, ex.: "grupos_rodada_1", "pos_oitavas".
            Use o rótulo que o usuário mencionou; se ele não disse, derive um claro.
        n_simulacoes: número de simulações Monte Carlo (padrão 10000 — já estabiliza
            os percentuais; só aumente se o usuário pedir mais precisão).

    Retorna JSON compacto com:
    - "ranking_campea_top12": [{pos, selecao, prob_campea}] — % com 1 casa decimal;
    - "brasil": posição e probabilidade do Brazil (sempre presente);
    - "eliminadas": seleções matematicamente eliminadas neste snapshot;
    - "rotulo_rodada" / "n_simulacoes" do snapshot gerado.
    """
    try:
        if _stub_forcado():
            raise ImportError("AGENTE_STUB=1")
        from monte_carlo_condicional import executar
    except ImportError:
        _avisar_stub("atualizar_probabilidades")
        ranking = _stub_ranking_completo()
        saida = _ranking_compacto(ranking)
        saida.update({
            "rotulo_rodada": rotulo_rodada, "n_simulacoes": int(n_simulacoes),
            "eliminadas": sorted(r["selecao"] for r in ranking if r["eliminada"]),
        })
        return _json_compacto(saida)

    df = executar(rotulo_rodada, n_simulacoes=int(n_simulacoes))  # ordenado por prob_campea
    df = df.sort_values("prob_campea", ascending=False).reset_index(drop=True)
    ranking = [{"posicao": i + 1, "selecao": str(r.selecao), "prob_campea": float(r.prob_campea),
                "eliminada": bool(getattr(r, "eliminada", False))}
               for i, r in enumerate(df.itertuples(index=False))]
    saida = _ranking_compacto(ranking)
    saida.update({
        "rotulo_rodada": rotulo_rodada, "n_simulacoes": int(n_simulacoes),
        "eliminadas": sorted(r["selecao"] for r in ranking if r["eliminada"]),
    })
    return _json_compacto(saida)


# --------------------------------------------------------------------------- #
# Tool 3 — eliminação matemática
# --------------------------------------------------------------------------- #
@tool
def listar_eliminados() -> str:
    """Lista as seleções já MATEMATICAMENTE eliminadas da Copa 2026, com um motivo
    resumido para cada uma.

    Use esta tool quando o usuário perguntar quem já está fora, quem ainda tem
    chance, ou ao fechar a narrativa de uma rodada (citar quem deu adeus ao
    torneio). A eliminação vem do último snapshot de probabilidades: equipes sem
    qualquer combinação de resultados que classifique (0.0% nas simulações) ou já
    derrotadas no mata-mata.

    Não recebe argumentos.

    Retorna JSON compacto: {"eliminadas": [{selecao, grupo, motivo}], "total": n}.
    Se ainda não houver snapshot, devolve um aviso pedindo para rodar
    atualizar_probabilidades primeiro.
    """
    if _stub_forcado():
        _avisar_stub("listar_eliminados")
        grupo_de = {s: g for g, times in _grupos_oficiais().items() for s in times}
        eliminadas = [{"selecao": s, "grupo": grupo_de.get(s, "?"), "motivo": motivo}
                      for s, motivo in sorted(_STUB_ELIMINADAS.items())]
        return _json_compacto({"eliminadas": eliminadas, "total": len(eliminadas)})

    ranking = obter_ranking_vigente()
    if not ranking:
        return _json_compacto({
            "aviso": "nenhum snapshot de probabilidades encontrado; "
                     "chame atualizar_probabilidades antes de listar eliminados."
        })
    try:
        grupo_de = {s: g for g, times in _grupos_oficiais().items() for s in times}
    except Exception:
        grupo_de = {}
    eliminadas = [
        {"selecao": r["selecao"], "grupo": grupo_de.get(r["selecao"], "?"),
         "motivo": "sem combinação de resultados restantes que classifique "
                   "(0.0% de avanço nas simulações do snapshot vigente)"}
        for r in ranking if r["eliminada"]
    ]
    return _json_compacto({"eliminadas": eliminadas, "total": len(eliminadas)})


# --------------------------------------------------------------------------- #
# Tool 4 — busca de notícias da Seleção (Tavily, sempre real)
# --------------------------------------------------------------------------- #
@tool
def buscar_noticias_selecao(termo: str = "") -> str:
    """Busca na internet notícias RECENTES sobre a Seleção Brasileira na Copa 2026
    (declarações de jogadores, clima no elenco, lesões, histórico no torneio).

    Use esta tool quando precisar de contexto jornalístico fresco sobre o Brasil —
    por exemplo para enriquecer a narrativa ou quando o usuário pedir novidades da
    Seleção. A busca usa o Tavily (topic=news) e devolve no máximo 5 resultados.

    Args:
        termo: refinamento opcional da busca, ex.: "lesão atacante", "declaração
            técnico", "próximo adversário". Vazio busca notícias gerais.

    Retorna JSON compacto: {"consulta": ..., "noticias": [{titulo, trecho, data}]}.
    """
    from langchain_tavily import TavilySearch

    consulta = f"seleção brasileira Copa 2026 {termo}".strip()
    busca = TavilySearch(max_results=5, topic="news")
    resultado = busca.invoke({"query": consulta})
    itens = resultado.get("results", []) if isinstance(resultado, dict) else []
    noticias = [{
        "titulo": (item.get("title") or "")[:120],
        "trecho": (item.get("content") or "").strip()[:220],
        "data": item.get("published_date") or item.get("publishedDate") or "",
    } for item in itens]
    return _json_compacto({"consulta": consulta, "noticias": noticias})


# Conjunto registrado no bind_tools do agente (src/agente.py).
FERRAMENTAS = [consultar_estado_grupos, atualizar_probabilidades,
               listar_eliminados, buscar_noticias_selecao]


if __name__ == "__main__":
    # Teste manual rápido (sem LLM): python src/agente_tools.py [stub|noticias]
    alvo = sys.argv[1] if len(sys.argv) > 1 else "stub"
    if alvo == "noticias":
        print(buscar_noticias_selecao.invoke({"termo": "notícias recentes"}))
    else:
        os.environ.setdefault("AGENTE_STUB", "1")
        print("— consultar_estado_grupos —")
        print(consultar_estado_grupos.invoke({}))
        print("— atualizar_probabilidades —")
        print(atualizar_probabilidades.invoke({"rotulo_rodada": "teste_stub", "n_simulacoes": 1000}))
        print("— listar_eliminados —")
        print(listar_eliminados.invoke({}))
        print("— obter_ranking_vigente (top 5) —")
        print(obter_ranking_vigente()[:5])
