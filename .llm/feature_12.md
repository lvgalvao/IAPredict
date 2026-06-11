# Feature 12 — Agente orquestrador (LangChain + LangGraph) com 3 tools

> Fase **Agente Copa 2026**. Depende das features 10–11. LLM: **OpenAI (GPT)** via
> `langchain-openai`. Arquitetura: tools LangChain + grafo LangGraph (StateGraph).
> **Não usar Deep Agents** (decisão do projeto) — agente ReAct próprio, explícito e didático.

## Objetivo
Agente de IA que orquestra as tools do torneio: o LLM **nunca calcula nada** — decide quais
tools chamar, em qual ordem, e interpreta os resultados para gerar a narrativa da rodada.
Cada execução fica registrada em `agente_execucoes`.

## Skills a invocar (antes de codar)
- `ecosystem-primer` — situar o que vem do LangChain vs. LangGraph nesta arquitetura.
- `langchain-dependencies` — pacotes/versões corretos (`langchain`, `langgraph`, `langchain-openai`).
- `langchain-fundamentals` — `@tool`, mensagens, `init_chat_model`/`ChatOpenAI`, `bind_tools`.
- `langgraph-fundamentals` — StateGraph, `add_messages`, ToolNode, conditional edges, streaming.
- `langgraph-persistence` — checkpointer (`MemorySaver`) com `thread_id` por sessão da live.
- `supabase` — tabela `agente_execucoes`.

(Excluídas de propósito: `deep-agents-*`, `managed-deep-agents`, `swarm` — sem deep agents;
`langchain-rag` — não há RAG; `langgraph-cli` — roda embutido no Streamlit, sem servidor;
`langgraph-human-in-the-loop` — a entrada humana é o form do Streamlit, sem `interrupt()`.)

## Spec

### Dependências e ambiente
- `requirements.txt` += `langchain`, `langgraph`, `langchain-openai` (versões conforme a
  skill `langchain-dependencies`).
- `.env.example` += `OPENAI_API_KEY=` e `OPENAI_MODEL=` (padrão: modelo OpenAI atual com
  bom tool-calling; deixar configurável, não hardcoded).

### Tabela `agente_execucoes` (auditoria — append-only)
```sql
CREATE TABLE IF NOT EXISTS agente_execucoes (
    id               bigint generated always as identity primary key,
    rotulo_rodada    text,
    pergunta         text,
    narrativa        text,
    frase_palpiteiro text,            -- preenchida pela feature_13
    tools_chamadas   text,            -- ex.: 'consultar_estado_grupos,atualizar_probabilidades'
    criado_em        timestamptz DEFAULT now()
);
```

### `src/agente_tools.py` — 3 tools com `@tool` (docstrings em português, ricas — são o contrato do LLM)
1. `consultar_estado_grupos() -> str` — classificação real dos grupos + jogos pendentes
   (de `estado_torneio.carregar_estado`/`classificacao_grupos`), JSON compacto.
2. `atualizar_probabilidades(rotulo_rodada: str, n_simulacoes: int = 10000) -> str` —
   dispara `monte_carlo_condicional.executar`, grava o snapshot e devolve o ranking por
   `prob_campea` em JSON.
3. `listar_eliminados() -> str` — seleções matematicamente eliminadas + motivo resumido.

**Context engineering das tools** (regra do idea.md): retornos enxutos — top 12 do ranking
**+ Brazil sempre incluído** (com a posição), percentuais com 1 casa decimal, sem despejar
as 48 seleções nem colunas cruas no contexto do LLM.

### `src/agente.py` — grafo LangGraph
```python
class EstadoAgente(TypedDict):
    messages: Annotated[list, add_messages]
    rotulo_rodada: str
    frase_palpiteiro: str   # usada pela feature_13
```
- Nós: `agente` (ChatOpenAI + `bind_tools`) ⇄ `tools` (`ToolNode(tools, handle_tool_errors=True)`),
  loop ReAct clássico via conditional edge (`tool_calls` → `tools`; senão → fim do loop).
  A feature_13 acrescenta o desvio determinístico do Palpiteiro **depois** do loop — deixar
  o ponto de saída do loop num nó nomeado (ex. `finalizar`), não direto no `END`.
- System prompt (português): papel de comentarista da Copa 2026; **regra de ouro: jamais
  calcular, estimar ou inventar números — todo número vem das tools**; ordem típica:
  estado → probabilidades → eliminados; narrar com personalidade e citar variações.
- Checkpointer `MemorySaver` + `thread_id` — memória da conversa entre rodadas na mesma live.
- `compile()` exposto como `criar_agente()` (o `app.py` da feature_14 importa daqui).
- Pós-execução: gravar em `agente_execucoes` (narrativa = última AIMessage; tools_chamadas
  extraídas das ToolMessages).
- CLI de teste: `python src/agente.py "Registrei a rodada 1, atualize as probabilidades"`
  — imprime tools chamadas na ordem + narrativa final.

## Plano
1. Invocar as skills na ordem listada; instalar dependências; atualizar `.env.example`.
2. Criar `agente_execucoes`.
3. Implementar as 3 tools com retornos compactos (testá-las direto, sem LLM).
4. Montar o grafo (estado, nós, edges, checkpointer) + system prompt.
5. Rodar o CLI 2× na mesma thread (memória) e conferir a Verificação.

## Verificação (SQL)
```sql
-- cada execução registra narrativa e as tools usadas
SELECT rotulo_rodada, left(narrativa, 80) AS inicio_narrativa, tools_chamadas, criado_em
FROM agente_execucoes ORDER BY criado_em DESC LIMIT 5;

-- a execução do agente gerou snapshot novo de probabilidades
SELECT rotulo_rodada, count(*) FROM gold_probabilidades_rodada GROUP BY rotulo_rodada;
```
