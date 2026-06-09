# Feature 06 — Treino Poisson + validação

## Contexto
O coração do modelo. Gol é contagem (0,1,2,3...), por isso Poisson, não regressão linear.

> Única feature cujo produto principal NÃO é tabela — são os artefatos `.pkl`. Grava só métricas.

## Objetivo
Treinar e validar dois modelos de Poisson e persistir os artefatos.

## Entrada
- `gold_atributos`.

## Saída
- `models/modelo_poisson_casa.pkl`, `models/modelo_poisson_visitante.pkl`, `models/colunas_atributos.pkl`.
- Tabela `metricas_validacao` (`id` PK + `mae_casa, mae_visitante, acuracia`, uma linha).
- Módulo compartilhado `src/poisson.py` (probabilidade de resultado) — reaproveitado em 07/08.

## Requisitos (parâmetros fixos — ver `prd.md`)
1. Dois modelos GLM **Poisson** (statsmodels): gols do mandante e do visitante.
2. **Split temporal por `data`:** treino `< 2024-01-01`; teste `>= 2024-01-01`.
3. **Treinar usando apenas os 6 atributos** (`elo_casa, elo_visitante, dif_elo, neutro, peso_torneio, peso_recencia`)
   — `neutro` como inteiro 0/1; matriz com `add_constant`. Os identificadores NÃO são features.
   Salvar a lista dos 6 em `colunas_atributos.pkl`.
   > `dif_elo = elo_casa − elo_visitante` é colinear com os ELOs; o statsmodels resolve o GLM via
   > pseudo-inversa (`pinv`) — não quebra e as predições (λ) ficam corretas. Manter os 6.
4. Peso de amostra no treino: `peso_amostra = peso_torneio × peso_recencia` (via `var_weights`).
5. Validar no teste:
   - `mae_casa`/`mae_visitante` = média de `|λ − gols reais|`.
   - `acuracia` = resultado previsto vs. real, onde o resultado vem da **grade de Poisson** de
     `src/poisson.py` (duas Poisson independentes até `MAX_GOLS=10`, argmax de P(V)/P(E)/P(D)).
6. Salvar os três `.pkl` (criar `models/`) e gravar `metricas_validacao`.

## Critérios de aceite
- Os três `.pkl` existem em `models/`.
- `acuracia` na faixa ~55–62% (referência: ~0,60; supera o baseline "sempre casa" ≈ 0,47).
- MAE de gols ~0,9–1,3.

## Verificação (SQL + arquivo)
```sql
SELECT mae_casa, mae_visitante, acuracia FROM metricas_validacao;
```
```bash
ls -la models/   # modelo_poisson_casa.pkl, modelo_poisson_visitante.pkl, colunas_atributos.pkl
```

## Plano de implementação
1. Criar `src/poisson.py`: `probabilidades_resultado(λ_casa, λ_visit, max_gols=10)`, `resultados_previstos(...)`, `resultado_real(...)`.
2. Ler `gold_atributos`; split por `data`; `montar_X` (6 atributos + const, `neutro`→int).
3. Treinar dois `sm.GLM(y, X, family=Poisson(), var_weights=peso_torneio*peso_recencia).fit()`.
4. Prever no teste; calcular MAE e acurácia; salvar `.pkl` e gravar `metricas_validacao`.

## Para explicar enquanto desenvolve (~7 min)
- Por que Poisson e não linear (gol é contagem ≥ 0); λ = gols esperados = xG.
- Por que dois modelos (casa ≠ fora).
- O que é train/test split e MAE; por que ~60% de acurácia é bom.
