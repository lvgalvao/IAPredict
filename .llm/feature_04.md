# Feature 04 — ELO: força das seleções

## Contexto
Medida dinâmica de força, atualizada após cada jogo. Conceito do xadrez, 60 anos.

> Peça o **plano antes do código** — etapa sequencial delicada.

## Objetivo
Calcular o ELO pré-jogo de cada partida e gravar em `silver_elo_pre_jogo` (e `silver_elo_atual`).

## Entrada
- `silver_ponderado` (usa `peso_torneio` no K-factor e `neutro` na expectativa).

## Saída
- `silver_elo_pre_jogo`: `id` PK + `jogo_id, data, time_casa, time_visitante, elo_casa, elo_visitante` (valores ANTES do jogo). `jogo_id` = `silver_ponderado.id` (join 1:1, conveniência da feature_05).
- `silver_elo_atual`: `id` PK + `selecao, elo` (ELO final mais recente por seleção).

## Requisitos (parâmetros fixos — ver `prd.md`)
1. Todo time começa em **1500**.
2. Processar em **ordem cronológica** por `(data, id)` (o `id` desempata jogos do mesmo dia → determinístico).
3. Expectativa: `E_casa = 1 / (1 + 10 ** ((elo_visit - elo_casa - HFA) / 400))`, `E_visit = 1 - E_casa`.
4. **HFA (mando de campo) = 100** quando `neutro = False`; **0** quando `neutro = True`. **Sem** multiplicador de goleada.
5. Resultado real `S_casa`: vitória = 1 / empate = 0.5 / derrota = 0.
6. **K-factor por `peso_torneio`**: 1 → K=20 · 2 → K=40 · 3 → K=60.
7. Atualização: `elo_casa += K·(S_casa − E_casa)` e `elo_visit += K·((1 − S_casa) − E_visit)`.
8. Gravar sempre o ELO **pré-jogo** (antes de atualizar) — anti-leakage: nunca o resultado da própria partida.

## Critérios de aceite
- Primeiros jogos partem de ~1500.
- Ranking final coerente (potências no topo: Espanha, Argentina, França, Brasil…).
- `silver_elo_pre_jogo` tem uma linha por jogo de `silver_ponderado`; `silver_elo_atual` cobre todas as seleções (≈ 319).

## Verificação (SQL)
```sql
SELECT selecao, ROUND(elo) AS elo FROM silver_elo_atual ORDER BY elo DESC LIMIT 10;   -- potências no topo
SELECT data, time_casa, time_visitante, ROUND(elo_casa), ROUND(elo_visitante)
  FROM silver_elo_pre_jogo ORDER BY data, id LIMIT 3;                                  -- ~1500 nos primeiros jogos
SELECT COUNT(*) FROM silver_elo_pre_jogo;                                             -- == silver_ponderado
SELECT COUNT(*) FROM silver_elo_atual;                                               -- ≈ 319
```
> O `MIN(elo_casa)` global NÃO é ~1500 (é ~900, de uma seleção fraca após anos de derrotas). O "~1500"
> vale para os **primeiros** jogos (arranque), conferidos por `ORDER BY data, id LIMIT`.

## Plano de implementação
1. Ler `silver_ponderado` ordenado por `data, id`.
2. Dicionário `elo[selecao]` com default 1500; iterar os jogos.
3. Para cada jogo: ler ELO pré, **gravar a linha pré-jogo**, calcular E (com `neutro`/HFA), atualizar com K por `peso_torneio`.
4. Materializar `silver_elo_atual` do dicionário; gravar as duas tabelas (DROP+CREATE+COPY).

## Para explicar enquanto desenvolve (~7 min)
- ELO é engenharia, não ML: cálculo sequencial acumulado, sem treino.
- Por que a ordem cronológica é sagrada.
- Por que K por torneio; por que o ELO já é "recency-aware" (e `peso_recencia` é só pro Poisson).
