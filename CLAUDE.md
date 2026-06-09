# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é este projeto

IAPredict é um pipeline de Machine Learning para prever os resultados da Copa do Mundo 2026, construído **ao vivo** com o Claude Code usando **Spec-Driven Development**. O fluxo de trabalho é dirigido pelas 8 especificações em `.llm/prd.md`: cada spec é colada no Claude Code, gera código Python, e produz **um resultado verificável no banco** (via SQL), exceto a Spec 06 que gera artefatos `.pkl`.

Atualmente o repositório está em estágio inicial: contém os dados crus (`data/results.csv`), o PRD com as specs (`.llm/prd.md`) e a configuração de infraestrutura. O código Python das specs ainda será gerado.

## Arquitetura: pipeline medallion

O pipeline segue a arquitetura medallion `bronze → silver → gold`, materializada como tabelas no Supabase. As 8 specs são sequenciais e cada uma depende da anterior:

| # | Spec | Saída principal |
|---|------|-----------------|
| 01 | Bronze (ingestão do CSV) | tabela `bronze_jogos` |
| 02 | Silver (limpeza + anti-leakage) | `silver_jogos`, `silver_copa2026` |
| 03 | Pesos (torneio + recência) | `silver_ponderado` |
| 04 | ELO | `silver_elo_pre_jogo`, `silver_elo_atual` |
| 05 | Features Gold | `gold_features` |
| 06 | Treino Poisson + validação | `.pkl` + `metricas_validacao` |
| 07 | Previsão + experimentos | `previsoes`, `experimentos_mae` |
| 08 | Monte Carlo | `gold_probabilidades_copa` |

Ao desenvolver as specs mais delicadas (**04 ELO** e **08 Monte Carlo**), peça o plano antes de gerar o código.

## Convenções inegociáveis (aplicam-se a todas as specs)

Estas regras estão definidas em `.llm/prd.md` e governam toda a modelagem:

- **Anti-leakage (crítico):** os 72 jogos da Copa 2026 ficam SEPARADOS e **nunca** entram no treino. Ranking/head-to-head só podem ser usados como contexto, jamais como feature derivada do resultado.
- **Janela temporal:** usar apenas jogos de **2006 em diante**.
- **`tournament_weight`** (ordinal, 3 níveis): amistoso = 1 / eliminatória e continental = 2 / Copa e finais = 3.
- **`recency_weight`** (decaimento exponencial, meia-vida 5 anos): `0.5 ** (idade_anos / 5)`.
- **ELO:** todos os times começam em 1500; cálculo **sequencial ordenado por data**.
- **Poisson:** gol é contagem (discreta ≥ 0) — por isso usa-se Poisson, não regressão linear.
- **Seed da Copa 2026:** arquivo pequeno com grupos + chaveamento, necessário apenas nas specs 07-08.

## Dados

`data/results.csv` — resultados de partidas internacionais de futebol (~49.450 linhas, de 1872 até jogos agendados da Copa 2026). Colunas: `date, home_team, away_team, home_score, away_score, tournament, city, country, neutral`. Atenção: o campo `tournament` tem alta cardinalidade e alguns valores contêm vírgulas/aspas — tratar o parsing de CSV adequadamente.

## Banco de dados (Supabase)

A persistência é feita no Supabase, acessado via **MCP** (configurado em `.mcp.json`, `project_ref=yncxketqoykxlsqsdztq`). A conexão deve ser definida por variável de ambiente.

- Antes de mudanças de schema, use `list_tables` para entender a estrutura existente.
- Para depurar, comece com `get_logs` e `get_advisors` antes de alterar.
- Cada spec termina com uma **Verificação (SQL)** que deve ser executada para validar o resultado no banco.

## Skills disponíveis

Duas skills do Supabase estão instaladas em `.agents/skills/` (ver `skills-lock.json`):
- `supabase` — orientação geral de desenvolvimento e segurança.
- `supabase-postgres-best-practices` — práticas de schema, índices, RLS e performance (consultar `references/` ao modelar tabelas e queries).
