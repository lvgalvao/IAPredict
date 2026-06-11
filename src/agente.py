"""Features 12-13 — Agente orquestrador da Copa 2026 (LangChain + LangGraph) + Modo Palpiteiro.

Grafo (StateGraph) com loop ReAct explícito — sem Deep Agents, decisão do projeto:

    START → agente ⇄ tools                       (loop ReAct: LLM decide as tools)
              └─(sem tool_calls)→ verificar_palpiteiro
                    ├─ Brazil ≠ 1º em prob_campea → palpiteiro → END
                    └─ Brazil = 1º (ou sem snapshot) → END

- O LLM (ChatOpenAI, modelo via ``OPENAI_MODEL``) JAMAIS calcula números: orquestra as
  4 tools de ``agente_tools.py`` e narra os resultados.
- ``verificar_palpiteiro`` é DETERMINÍSTICO: não parseia mensagens — consulta o último
  snapshot de ``gold_probabilidades_rodada`` (via ``obter_ranking_vigente``, que respeita
  o modo stub). A regra "Brasil fora do 1º ⇒ Modo Palpiteiro" vira conditional edge.
- ``palpiteiro``: busca Tavily direta (invocação Python da tool, sem o LLM decidir) +
  chamada LLM dedicada SEM tools, com dramaticidade calibrada pela probabilidade.
- Memória: checkpointer ``MemorySaver`` + ``thread_id`` por sessão da live.
- Pós-execução: grava narrativa, tools chamadas e frase em ``agente_execucoes``.

CLI:  python src/agente.py "Registrei a rodada 1, atualize as probabilidades"
      (aceita várias perguntas posicionais — todas na MESMA thread → memória;
       opções: --rodada <rotulo>  --thread <id>)

O ``app.py`` (feature_14) importa ``criar_agente()`` daqui.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from functools import lru_cache
from typing import Annotated, Literal, Optional

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from agente_tools import FERRAMENTAS, buscar_noticias_selecao, obter_ranking_vigente

load_dotenv()  # OPENAI_API_KEY / OPENAI_MODEL / TAVILY_API_KEY / DATABASE_URL via .env

# Modelo OpenAI atual com bom tool-calling e custo baixo; configurável via OPENAI_MODEL.
MODELO_PADRAO = "gpt-4.1-mini"

PROMPT_SISTEMA = """Você é o comentarista oficial e apaixonado da Copa do Mundo 2026 do projeto IAPredict.
Sua função: orquestrar as ferramentas de dados do torneio e transformar os resultados em uma
narrativa de rodada vibrante, em português do Brasil.

REGRA DE OURO (inviolável): você JAMAIS calcula, estima, extrapola ou inventa números.
TODO número citado (pontos, saldo, percentuais, posições) vem EXATAMENTE das ferramentas.
Se não tiver o número de uma ferramenta, não cite número — chame a ferramenta certa.

Ordem típica de trabalho ao narrar uma rodada:
1. consultar_estado_grupos — como os grupos estão de verdade;
2. atualizar_probabilidades — recalcula e grava o snapshot (use o rótulo da rodada que o
   usuário mencionou, ex.: "grupos_rodada_1");
3. listar_eliminados — quem já deu adeus à Copa.
Use buscar_noticias_selecao quando contexto jornalístico do Brasil enriquecer a história.

Estilo da narrativa final: personalidade de locutor, 2 a 4 parágrafos curtos, destaque os
líderes do ranking de título, a situação do Brasil (posição e percentual), variações dignas
de nota e as seleções eliminadas. Sem tabelas; texto corrido com os números das ferramentas."""

PROMPT_PALPITEIRO = """Você é o MODO PALPITEIRO do IAPredict: a voz do torcedor brasileiro raiz que nunca
deixa de acreditar no hexa, mesmo quando a matemática aponta outro favorito.

Situação oficial das simulações: o Brasil está na posição {posicao} do ranking de
probabilidade de título, com {prob_pct} de chance{eliminada_txt}.

Notícias recentes da Seleção (contexto real, use se ajudar):
{contexto_noticias}

Tom obrigatório desta frase: {instrucao_tom}

Gere UMA única frase motivacional curta (no máximo 2 linhas) em português do Brasil para o
torcedor acreditar no hexa. Pode citar a probabilidade dada acima, mas NÃO invente outros
números. Devolva SOMENTE a frase, sem aspas e sem comentários."""


# --------------------------------------------------------------------------- #
# Estado do grafo
# --------------------------------------------------------------------------- #
class EstadoAgente(TypedDict):
    """Estado compartilhado do grafo (feature_12 + campos do Palpiteiro da feature_13)."""

    messages: Annotated[list, add_messages]
    rotulo_rodada: str
    frase_palpiteiro: str           # preenchida pelo nó palpiteiro (feature_13)
    brasil_posicao: int             # interno: decisão determinística do desvio (0 = sem snapshot)
    brasil_prob_campea: float       # interno: calibra a dramaticidade da frase
    brasil_eliminada: bool          # interno: faixa "fé absoluta contra a matemática"


@lru_cache(maxsize=4)
def _obter_llm(temperatura: float) -> ChatOpenAI:
    """ChatOpenAI configurado pelo ambiente (OPENAI_MODEL; padrão bom em tool-calling)."""
    return ChatOpenAI(model=os.getenv("OPENAI_MODEL", MODELO_PADRAO), temperature=temperatura)


# --------------------------------------------------------------------------- #
# Nós do grafo
# --------------------------------------------------------------------------- #
def no_agente(state: EstadoAgente) -> dict:
    """Loop ReAct: o LLM decide a próxima tool ou encerra com a narrativa final."""
    llm_com_tools = _obter_llm(0.3).bind_tools(FERRAMENTAS)
    resposta = llm_com_tools.invoke([SystemMessage(PROMPT_SISTEMA)] + state["messages"])
    atualizacao: dict = {"messages": [resposta]}
    for chamada in getattr(resposta, "tool_calls", None) or []:
        if chamada["name"] == "atualizar_probabilidades" and chamada["args"].get("rotulo_rodada"):
            atualizacao["rotulo_rodada"] = str(chamada["args"]["rotulo_rodada"])
    return atualizacao


def rota_apos_agente(state: EstadoAgente) -> Literal["tools", "verificar_palpiteiro"]:
    """Conditional edge do loop ReAct: pediu tool → executa; senão → saída do loop."""
    ultima = state["messages"][-1]
    return "tools" if getattr(ultima, "tool_calls", None) else "verificar_palpiteiro"


def no_verificar_palpiteiro(state: EstadoAgente) -> dict:
    """Saída do loop ReAct — verificação DETERMINÍSTICA do Modo Palpiteiro.

    Não parseia mensagens do LLM: consulta o ranking vigente (último snapshot de
    ``gold_probabilidades_rodada`` ou stub, via função única ``obter_ranking_vigente``)
    e registra a situação do Brasil no estado. A decisão fica na conditional edge.
    """
    ranking = obter_ranking_vigente()
    brasil = next((r for r in ranking if r["selecao"] == "Brazil"), None)
    if brasil is None:  # sem snapshot (ou Brasil ausente): não ativa o Palpiteiro
        return {"brasil_posicao": 0, "brasil_prob_campea": 0.0,
                "brasil_eliminada": False, "frase_palpiteiro": ""}
    return {
        "brasil_posicao": int(brasil["posicao"]),
        "brasil_prob_campea": float(brasil["prob_campea"]),
        "brasil_eliminada": bool(brasil.get("eliminada", False)),
        "frase_palpiteiro": "",  # reset: cada execução decide de novo
    }


def rota_palpiteiro(state: EstadoAgente) -> Literal["palpiteiro", "__end__"]:
    """Regra incondicional do idea.md: Brasil fora do 1º lugar ⇒ Modo Palpiteiro."""
    return "palpiteiro" if state.get("brasil_posicao", 0) >= 2 else END


def _instrucao_dramaticidade(prob: float, eliminada: bool) -> str:
    """Faixas da spec 13: quanto menor a probabilidade, mais dramática a frase."""
    if eliminada or prob < 0.01:
        return ("desesperadamente poética: fé absoluta contra a matemática, quase uma oração "
                "de torcedor — o impossível é só o hexa atrasado")
    if prob < 0.05:
        return ("épica, tom de romaria: invoque a camisa, a história e o 'respeita a "
                "Amarelinha' — a matemática nunca venceu uma final")
    if prob < 0.15:
        return ("dramática: invoque a história da Seleção, os cinco títulos e a promessa do "
                "hexa — drama de jogo decisivo")
    return ("provocadora e confiante: o topo é logo ali, é questão de tempo — deboche leve "
            "com os favoritos da máquina")


def no_palpiteiro(state: EstadoAgente) -> dict:
    """Modo Palpiteiro: busca Tavily DIRETA (sem o LLM decidir) + LLM dedicado sem tools."""
    posicao = state["brasil_posicao"]
    prob = state.get("brasil_prob_campea", 0.0)
    eliminada = state.get("brasil_eliminada", False)

    try:  # a frase não pode derrubar a execução se a busca falhar
        contexto_noticias = buscar_noticias_selecao.invoke(
            {"termo": "notícias recentes jogadores técnico"})
    except Exception as exc:
        contexto_noticias = f"(busca de notícias indisponível: {exc})"

    prompt = PROMPT_PALPITEIRO.format(
        posicao=posicao,
        prob_pct=f"{prob * 100:.1f}%",
        eliminada_txt=" — e MATEMATICAMENTE ELIMINADO" if eliminada else "",
        contexto_noticias=contexto_noticias,
        instrucao_tom=_instrucao_dramaticidade(prob, eliminada),
    )
    resposta = _obter_llm(0.9).invoke([HumanMessage(prompt)])  # LLM dedicado, SEM tools
    frase = str(resposta.content).strip().strip('"')
    return {"frase_palpiteiro": frase}


# --------------------------------------------------------------------------- #
# Fábrica do grafo (importada pelo app.py da feature_14)
# --------------------------------------------------------------------------- #
def criar_agente(checkpointer=None):
    """Compila o grafo do agente com checkpointer (padrão: ``MemorySaver``).

    O chamador controla a memória da conversa passando o mesmo ``thread_id`` em
    ``config={"configurable": {"thread_id": ...}}`` a cada invocação.
    """
    grafo = (
        StateGraph(EstadoAgente)
        .add_node("agente", no_agente)
        .add_node("tools", ToolNode(FERRAMENTAS, handle_tool_errors=True))
        .add_node("verificar_palpiteiro", no_verificar_palpiteiro)
        .add_node("palpiteiro", no_palpiteiro)
        .add_edge(START, "agente")
        .add_conditional_edges("agente", rota_apos_agente, ["tools", "verificar_palpiteiro"])
        .add_edge("tools", "agente")
        .add_conditional_edges("verificar_palpiteiro", rota_palpiteiro, ["palpiteiro", END])
        .add_edge("palpiteiro", END)
    )
    return grafo.compile(checkpointer=checkpointer or MemorySaver())


# --------------------------------------------------------------------------- #
# Auditoria — tabela agente_execucoes (append-only)
# --------------------------------------------------------------------------- #
DDL_EXECUCOES = """
CREATE TABLE IF NOT EXISTS agente_execucoes (
    id               bigint generated always as identity primary key,
    rotulo_rodada    text,
    pergunta         text,
    narrativa        text,
    frase_palpiteiro text,            -- preenchida pela feature_13
    tools_chamadas   text,            -- ex.: 'consultar_estado_grupos,atualizar_probabilidades'
    criado_em        timestamptz DEFAULT now()
);
"""


def gravar_execucao(rotulo_rodada: Optional[str], pergunta: str, narrativa: str,
                    frase_palpiteiro: Optional[str], tools_chamadas: list[str]) -> None:
    """Grava uma execução em ``agente_execucoes`` (append-only; cria a tabela se preciso)."""
    from sqlalchemy import text

    from db import get_engine

    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text(DDL_EXECUCOES))
        conn.execute(
            text("""
                INSERT INTO agente_execucoes
                    (rotulo_rodada, pergunta, narrativa, frase_palpiteiro, tools_chamadas)
                VALUES (:rotulo, :pergunta, :narrativa, :frase, :tools)
            """),
            {"rotulo": rotulo_rodada, "pergunta": pergunta, "narrativa": narrativa,
             "frase": frase_palpiteiro or None, "tools": ",".join(tools_chamadas)},
        )


# --------------------------------------------------------------------------- #
# Execução de uma pergunta (invoca o grafo + grava auditoria)
# --------------------------------------------------------------------------- #
def executar_agente(grafo, pergunta: str, thread_id: str,
                    rotulo_rodada: Optional[str] = None) -> dict:
    """Invoca o grafo numa thread, extrai narrativa/tools/frase e grava a auditoria.

    Retorna ``{"narrativa", "frase_palpiteiro", "tools_chamadas", "rotulo_rodada"}``.
    """
    config = {"configurable": {"thread_id": thread_id}}
    try:  # nº de mensagens já na thread (para isolar SÓ as mensagens desta execução)
        ja_existentes = len(grafo.get_state(config).values.get("messages", []))
    except Exception:
        ja_existentes = 0

    entrada: dict = {"messages": [HumanMessage(pergunta)]}
    if rotulo_rodada:
        entrada["rotulo_rodada"] = rotulo_rodada
    resultado = grafo.invoke(entrada, config)

    novas = resultado["messages"][ja_existentes:]
    tools_chamadas = [m.name for m in novas if isinstance(m, ToolMessage)]
    narrativa = next(
        (str(m.content) for m in reversed(novas)
         if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None)),
        "",
    )
    frase = resultado.get("frase_palpiteiro") or None
    rotulo = resultado.get("rotulo_rodada") or rotulo_rodada or None

    try:
        gravar_execucao(rotulo, pergunta, narrativa, frase, tools_chamadas)
    except Exception as exc:  # auditoria não derruba a live, mas avisa alto
        print(f"[aviso] falha ao gravar em agente_execucoes: {exc}", file=sys.stderr)

    return {"narrativa": narrativa, "frase_palpiteiro": frase,
            "tools_chamadas": tools_chamadas, "rotulo_rodada": rotulo}


# --------------------------------------------------------------------------- #
# CLI de teste
# --------------------------------------------------------------------------- #
def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):  # console Windows: evita erro com acentos/emoji
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Agente Copa 2026 (features 12-13). Várias perguntas = mesma thread (memória).")
    parser.add_argument("perguntas", nargs="+", help='ex.: "Registrei a rodada 1, atualize as probabilidades"')
    parser.add_argument("--rodada", default=None, help="rotulo_rodada inicial do estado (opcional)")
    parser.add_argument("--thread", default=None, help="thread_id da conversa (padrão: gerado)")
    args = parser.parse_args()

    grafo = criar_agente()
    thread_id = args.thread or f"cli-{uuid.uuid4().hex[:8]}"
    print(f"thread_id: {thread_id}  |  modelo: {os.getenv('OPENAI_MODEL', MODELO_PADRAO)}"
          f"  |  stub: {'sim' if os.getenv('AGENTE_STUB') or os.getenv('AGENTE_STUB_BRASIL_LIDER') else 'não'}")

    for i, pergunta in enumerate(args.perguntas, start=1):
        print("\n" + "=" * 72)
        print(f"PERGUNTA {i}: {pergunta}")
        print("=" * 72)
        info = executar_agente(grafo, pergunta, thread_id, args.rodada)
        ordem = " -> ".join(info["tools_chamadas"]) or "(nenhuma tool chamada)"
        print(f"TOOLS CHAMADAS (ordem): {ordem}")
        print("\n--- NARRATIVA ---")
        print(info["narrativa"])
        if info["frase_palpiteiro"]:
            print("\n--- MODO PALPITEIRO 🇧🇷 ---")
            print(info["frase_palpiteiro"])
        else:
            print("\n(Modo Palpiteiro não ativado — Brasil em 1º ou sem snapshot.)")


if __name__ == "__main__":
    main()
