# Feature 14 — Página "Agente ao vivo" no Streamlit

> Fase **Agente Copa 2026**. Depende das features 10–13. Fecha o ciclo da live: registrar
> resultado → agente roda as tools → probabilidades, bracket e narrativa atualizam na tela.

## Objetivo
Quarta página no `app.py`: registrar os placares reais da rodada, disparar o agente e exibir
ao vivo — tabelas de grupos com % de classificação, gráfico de barras das probabilidades de
título, bracket do mata-mata preenchendo conforme os classificados são definidos, narrativa
do agente em streaming e a frase do Modo Palpiteiro em destaque.

## Skills a invocar (antes de codar)
- `langgraph-fundamentals` — streaming do grafo (`stream_mode="messages"` / `"updates"`).
- `supabase-postgres-best-practices` — consultas do histórico (último snapshot por rótulo).

## Spec

### Página `pagina_agente_ao_vivo` (registrar em `PAGINAS` como "🤖 Agente ao vivo")
Seguir os padrões do `app.py` existente: `st.cache_resource` para recursos, `com_bandeira`
para nomes, Altair para gráficos, colunas/expanders para layout.

**1. Registro de resultados (sidebar ou coluna esquerda)**
- Selectbox de jogos pendentes (de `estado_torneio.carregar_estado`), agrupados por
  fase/rodada; dois `st.number_input` de gols; no mata-mata empatado, selectbox do vencedor
  nos pênaltis; botão grava via `registrar_resultado` e dá `st.rerun()`.
- Quando os 72 jogos de grupo estiverem completos, chamar `propagar_classificados` e
  habilitar o registro do mata-mata.

**2. Execução do agente**
- Campo de texto (pergunta livre, com placeholder "Atualize as probabilidades após a rodada 1")
  + selectbox/entrada do `rotulo_rodada` + botão "🤖 Rodar agente".
- `criar_agente()` (feature_12) em `st.cache_resource`; `thread_id` em `st.session_state`
  (memória da conversa durante a live).
- Streaming na tela: `st.status` mostrando cada tool chamada (via `stream_mode="updates"`)
  e a narrativa token a token com `st.write_stream` (via `stream_mode="messages"`).
- Frase do Palpiteiro (se houver no estado final) em destaque: `st.warning` com 🇧🇷.
- Histórico das execuções da sessão (narrativas anteriores) em expander.

**3. Visualizações (atualizam após cada execução)**
- **Grupos**: 12 expanders/abas — classificação real (`classificacao_grupos`) com coluna
  extra `% classificação` = `prob_grupo` do último snapshot de `gold_probabilidades_rodada`;
  seleções `eliminada = true` riscadas/cinza com ❌.
- **Título**: barras Altair com `prob_campea` do último snapshot — top 12 **+ Brazil sempre**
  (destacar a barra do Brasil em outra cor).
- **Bracket**: colunas por fase (R32 → Final) a partir de `resultados_copa` M73–M104 —
  slots simbólicos enquanto indefinidos, times reais quando propagados, placar e vencedor
  em negrito quando registrado (reusar o estilo `_placar_md`).
- **Evolução**: gráfico de linhas `prob_campea` × `rotulo_rodada` (ordenado por `criado_em`)
  das 5 melhores seleções + Brazil — o "antes/depois" de cada rodada da live.

### Consultas (cachear com `@st.cache_data` e invalidar com `.clear()` após registrar/rodar)
```sql
-- último snapshot vigente
SELECT * FROM gold_probabilidades_rodada
WHERE criado_em = (SELECT max(criado_em) FROM gold_probabilidades_rodada);
```

## Plano
1. Invocar as skills; criar a página vazia e registrá-la na navegação.
2. Implementar o registro de resultados (+ propagação de classificados).
3. Integrar o agente com streaming (status das tools + narrativa + frase do Palpiteiro).
4. Implementar as 4 visualizações.
5. Ensaiar o roteiro da live: registrar rodada 1 (com derrota do Brasil), rodar o agente e
   conferir que tudo atualiza; limpar os dados de ensaio (`--reset` da feature_10 + apagar
   snapshots/execuções de teste).

## Verificação
Manual: `streamlit run app.py` → registrar um placar → rodar o agente → ver narrativa em
streaming, % atualizados, frase do Palpiteiro e bracket. E no banco:
```sql
-- histórico consistente: cada rodada da live tem snapshot e execução do agente
SELECT p.rotulo_rodada, count(DISTINCT p.selecao) AS selecoes, max(e.criado_em) AS ultima_execucao
FROM gold_probabilidades_rodada p
LEFT JOIN agente_execucoes e USING (rotulo_rodada)
GROUP BY p.rotulo_rodada ORDER BY max(p.criado_em);
```
