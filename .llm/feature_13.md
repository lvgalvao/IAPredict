# Feature 13 — Modo Palpiteiro (busca web + frase motivacional)

> Fase **Agente Copa 2026**. Depende da feature_12 (grafo do agente). Busca web: **Tavily**
> (`langchain-tavily`). O destaque da live.

## Objetivo
Sempre que o Brasil **não estiver em 1º** no ranking de `prob_campea` — independente de ter
perdido ou não —, o agente ativa o Modo Palpiteiro: busca na internet informações recentes da
Seleção Brasileira e gera uma frase motivacional curta para o torcedor acreditar no hexa.
Quanto menor a probabilidade do Brasil, mais dramática e criativa a frase.

## Skills a invocar (antes de codar)
- `langchain-fundamentals` — integração da tool de busca (`langchain-tavily`).
- `langgraph-fundamentals` — conditional edge determinística + nó dedicado no grafo.

## Spec

### Dependências e ambiente
- `requirements.txt` += `langchain-tavily`.
- `.env.example` += `TAVILY_API_KEY=` (free tier: 1000 buscas/mês — suficiente para a live).

### Tool 4 — `buscar_noticias_selecao` (em `src/agente_tools.py`)
- Encapsula `TavilySearch` (`max_results=5`, `topic="news"`), consulta tipo
  `"seleção brasileira Copa 2026 <termo>"`; devolve título + trecho + data de cada resultado
  (compacto, sem URLs gigantes — context engineering).
- Também registrada no `bind_tools` do agente (o LLM pode buscar quando achar útil), mas a
  **ativação do Modo Palpiteiro não depende do LLM** — ver abaixo.

### Ativação determinística no grafo (`src/agente.py`)
A regra do idea.md é incondicional ("sempre que o Brasil não estiver na primeira posição"),
então ela vira **conditional edge**, não instrução de prompt:
```
agente ⇄ tools                       (loop ReAct da feature_12)
   └─(sem tool_calls)→ verificar_palpiteiro
         ├─ Brazil ≠ 1º em prob_campea → palpiteiro → END
         └─ Brazil = 1º (ou sem snapshot)  → END
```
- `verificar_palpiteiro` **não** parseia mensagens: consulta direto o último snapshot de
  `gold_probabilidades_rodada` (lote com `max(criado_em)`) — determinístico e à prova de
  alucinação.
- Nó `palpiteiro`: chama `buscar_noticias_selecao` direto (invocação Python da tool, sem
  passar pelo LLM decidir) → monta prompt com a posição/probabilidade atual do Brasil + o
  contexto das notícias → chamada LLM **dedicada e sem tools** que devolve só a frase.
- **Dramaticidade calibrada pela probabilidade** (instrução no prompt, com faixas):
  - `≥ 15%` mas fora do topo → provocadora, confiante ("é logo ali");
  - `5–15%` → dramática, invocando a história e o hexa;
  - `1–5%` → épica, romaria, "respeita a Amarelinha";
  - `< 1%` ou eliminada → desesperadamente poética, fé absoluta contra a matemática.
- A frase entra no estado (`frase_palpiteiro`), é anexada à narrativa final e gravada em
  `agente_execucoes.frase_palpiteiro`.

## Plano
1. Invocar as skills; instalar `langchain-tavily`; configurar a chave.
2. Implementar e testar a tool de busca isolada (sem LLM).
3. Adicionar `verificar_palpiteiro` + `palpiteiro` ao grafo (a saída do loop da feature_12
   já aponta para o nó de verificação).
4. Testar os dois cenários: snapshot com Brasil fora do topo (caso real atual) → frase
   gerada; simular Brasil em 1º (editar temporariamente o snapshot de teste) → sem frase.

## Verificação (SQL)
```sql
-- com Brasil fora do 1º lugar, toda execução nova tem frase; com Brasil em 1º, frase nula
SELECT e.rotulo_rodada, e.frase_palpiteiro IS NOT NULL AS ativou, left(e.frase_palpiteiro, 60) AS frase
FROM agente_execucoes e ORDER BY e.criado_em DESC LIMIT 5;

-- conferência da condição: quem é o 1º do último snapshot?
SELECT selecao, prob_campea FROM gold_probabilidades_rodada
WHERE criado_em = (SELECT max(criado_em) FROM gold_probabilidades_rodada)
ORDER BY prob_campea DESC LIMIT 3;
```
