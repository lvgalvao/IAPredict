# Feature 05 — Atributos Gold: tabela de treino

## Contexto
Camada gold: a tabela larga e final que alimenta o modelo (uma linha por jogo).

## Objetivo
Montar `gold_atributos`, pronta para o Poisson.

## Entrada
- `silver_ponderado` e `silver_elo_pre_jogo` (join 1:1 por `silver_elo_pre_jogo.jogo_id = silver_ponderado.id`).

## Saída
- `gold_atributos` com `id` PK + **identificadores** (`jogo_id, data, time_casa, time_visitante`)
  + os **8 atributos**: `elo_casa, elo_visitante, dif_elo, neutro, peso_torneio, peso_recencia, gols_casa, gols_visitante`.
  > A `data` é **funcionalmente necessária** (não só rastreabilidade): a feature_06 a usa para o split temporal. Os identificadores não são features de treino.

## Requisitos
1. Calcular `dif_elo` = `elo_casa` − `elo_visitante`.
2. Usar só jogos competitivos (excluir `eh_amistoso = true` — **filtra por `eh_amistoso`, não por `peso_torneio`**;
   torneios menores não-amistosos de nível 1 entram no treino).
3. **Não incluir confederação** (origem do viés) — não existe coluna de confederação em nenhuma tabela; atendido por construção.
4. Garantir que nenhum jogo da Copa 2026 está presente (anti-leakage; já garantido pelo split da feature_02).
5. Sem nulos nas colunas de atributo (validar com `assert`).

## Critérios de aceite
- Todas as colunas presentes, sem nulos.
- Zero jogos da Copa 2026.
- Tamanho esperado (referência): ≈ 13.182 jogos (silver_jogos − amistosos).

## Verificação (SQL)
```sql
SELECT elo_casa, elo_visitante, dif_elo, neutro, peso_torneio, peso_recencia, gols_casa, gols_visitante
FROM gold_atributos LIMIT 5;
SELECT COUNT(*) FROM gold_atributos WHERE dif_elo IS NULL OR peso_torneio IS NULL;       -- 0
SELECT COUNT(*) FROM gold_atributos WHERE gols_casa IS NULL OR gols_visitante IS NULL;   -- 0
SELECT COUNT(*) FROM gold_atributos WHERE dif_elo <> elo_casa - elo_visitante;           -- 0
```

## Plano de implementação
1. Ler com JOIN já filtrado: `silver_ponderado s JOIN silver_elo_pre_jogo e ON e.jogo_id = s.id WHERE NOT s.eh_amistoso ORDER BY s.data, s.id`.
2. Calcular `dif_elo` (pandas); `assert` 0 nulos nas colunas de atributo.
3. Gravar `gold_atributos` (DROP+CREATE+COPY).

## Para explicar enquanto desenvolve (~7 min)
- O que é feature engineering: colunas derivadas que ajudam o modelo.
- Por que `dif_elo` costuma valer mais que os dois ELOs separados.
- Reforçar o anti-leakage.
