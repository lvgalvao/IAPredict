# Feature 07 — Previsão de partida + experimentos

## Contexto
Com os modelos treinados, criamos a função de previsão e rodamos os experimentos que ensinam
a lição central: mais sofisticação nem sempre melhora.

## Objetivo
(1) Função de previsão de jogo; (2) experimentos comparando configurações por MAE.

## Entrada
- `models/*.pkl`, `silver_elo_atual` (ELO de cada seleção) e `gold_atributos` (para os experimentos).

## Saída
- `previsoes`: `id` PK + `time_casa, time_visitante, gols_esperados_casa, gols_esperados_visitante, prob_vitoria, prob_empate, prob_derrota`.
  Conteúdo: **os 72 jogos da Copa 2026** (de `silver_copa2026`), com `peso_torneio = 3`.
- `experimentos_mae`: `id` PK + `config, mae_casa, mae_visitante`.

## Requisitos
1. Função `prever_jogo(time_casa, time_visitante, neutro, peso_torneio)` → `gols_esperados_*` e
   `prob_vitoria/empate/derrota`.
   - Busca `elo_casa`/`elo_visitante` em `silver_elo_atual`; `dif_elo = elo_casa − elo_visitante`.
   - **`peso_recencia = 1.0`** (jogo no presente) ao montar as features.
   - As probabilidades vêm de **`src/poisson.py`** (`probabilidades_resultado`) — reaproveitar, não reimplementar.
   - (na implementação, os modelos/elos são injetados na função; um wrapper carrega os `.pkl` e o `silver_elo_atual`.)
2. Experimentos (recalcular `peso_recencia` por config, **re-treinar** os 2 GLM no mesmo split temporal da feature_06 e medir MAE no teste):
   - `sem_recencia` → `peso_recencia = 1.0` (var_weights = `peso_torneio`);
   - `meia_vida_3`, `meia_vida_5`, `meia_vida_10` → `0.5 ** (idade_anos / h)`, recalculado de `data` (âncora 2026-06-11).
   - Recalcular afeta tanto a **feature** `peso_recencia` quanto o **var_weights** (re-treino completo por config).
3. Gravar `previsoes` (72 jogos) e `experimentos_mae` (4 configs).

## Critérios de aceite
- `prob_vitoria + prob_empate + prob_derrota` ≈ 1 (todos os 72 jogos).
- `experimentos_mae` permite comparar as configurações. Referência: meia-vidas 3/5/10 quase empatam
  (~1,046–1,048 de MAE casa) e `sem_recencia` é pior (~1,081) — a lição "mais sofisticação nem sempre melhora".

## Verificação (SQL)
```sql
SELECT time_casa, time_visitante, ROUND((prob_vitoria + prob_empate + prob_derrota)::numeric, 3) AS soma
  FROM previsoes LIMIT 5;                                                   -- ≈ 1
SELECT config, ROUND(mae_casa::numeric, 3), ROUND(mae_visitante::numeric, 3)
  FROM experimentos_mae ORDER BY mae_casa;
```

## Plano de implementação
1. Carregar os `.pkl` e o `silver_elo_atual`.
2. Implementar `prever_jogo`: features (incl. `peso_recencia=1.0`) → λ de cada modelo → grade de Poisson (`src/poisson.py`) → V/E/D.
3. Gerar `previsoes` aplicando `prever_jogo` aos 72 jogos de `silver_copa2026` (`neutro` real, `peso_torneio=3`).
4. Rodar os experimentos (recalcular recência + re-treinar) e medir MAE no teste.
5. Gravar `previsoes` e `experimentos_mae` (DROP+CREATE+COPY).

## Para explicar enquanto desenvolve (~7 min)
- Como o λ vira placar: Poisson dá P(gols); combinando os dois times → V/E/D.
- A lição central: variar config nem sempre melhora o MAE. Caso da confederação como alerta.
