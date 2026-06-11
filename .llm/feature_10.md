# Feature 10 — Estado do torneio ao vivo (fundação do agente)

> Fase **Agente Copa 2026** (`idea.md`). Pré-requisito: pipeline 01–09 concluído
> (`silver_copa2026`, `silver_elo_atual`, modelos `.pkl`, `gold_probabilidades_copa`).
> Decisão de projeto: persistência **só no Supabase** (sem JSON local, diferente do
> rascunho do idea.md). O estado é sempre reconstruído a partir das tabelas.

## Objetivo
Criar a estrutura de estado do torneio — dataclasses representando grupos, times, partidas
e o bracket eliminatório — com persistência no Supabase, para que resultados reais sejam
registrados rodada a rodada sem perder nada entre execuções.

## Skills a invocar (antes de codar)
- `supabase` — orientação geral de desenvolvimento e segurança.
- `supabase-postgres-best-practices` — schema, tipos e índices da tabela nova.

## Spec

### Tabela `resultados_copa` (operacional — sem prefixo medallion, é entrada da live)
```sql
CREATE TABLE IF NOT EXISTS resultados_copa (
    id                bigint generated always as identity primary key,
    match_id          text UNIQUE NOT NULL,   -- M1..M72 (grupos, por ordem data,id) + M73..M104 (calendário)
    fase              text NOT NULL,          -- 'Grupos' | 'R32' | 'R16' | 'QF' | 'SF' | '3rd' | 'Final'
    rodada            integer,                -- 1..3 na fase de grupos; NULL no mata-mata
    grupo             text,                   -- 'A'..'L'; NULL no mata-mata
    data              date,
    time_casa         text,                   -- NULL no mata-mata até os classificados serem definidos
    time_visitante    text,
    gols_casa         integer,                -- NULL = ainda não jogado (mesmo critério do results.csv)
    gols_visitante    integer,
    penaltis_vencedor text,                   -- mata-mata: vencedor nos pênaltis quando houve empate
    neutro            boolean,
    atualizado_em     timestamptz DEFAULT now()
);
```
**Atenção — exceção à convenção de DDL do pipeline:** esta tabela é **mutável** (recebe
UPDATEs durante a live). O seed com `DROP TABLE` só roda com flag explícita `--reset`;
sem a flag, `inicializar_estado()` não destrói resultados já registrados.

### Seed (104 linhas)
- **M1..M72**: de `silver_copa2026` ordenado por `(data, id)` — `time_casa`, `time_visitante`,
  `neutro`, `data`. `grupo` vem de `data/grupos_copa2026.csv`; `rodada` derivada: jogos do
  grupo ordenados por `(data, id)` → pares (1º-2º jogo = rodada 1, 3º-4º = 2, 5º-6º = 3).
- **M73..M104**: de `data/calendario_copa2026.csv` — `fase = round`, `data = match_date`,
  times NULL, `neutro = true`. Carga via `COPY ... FROM STDIN` (convenção do pipeline).

### Módulo `src/estado_torneio.py` (imports flat, executável)
- Dataclasses: `Partida` (match_id, fase, rodada, grupo, times, gols, penaltis_vencedor, neutro),
  `Grupo` (letra, times, partidas), `EstadoTorneio` (grupos, mata_mata, propriedades:
  `jogos_pendentes`, `jogos_realizados`, `fase_grupos_completa`).
- `inicializar_estado(reset: bool = False)` — DDL + seed (só com reset ou tabela vazia).
- `carregar_estado() -> EstadoTorneio` — reconstrói tudo de `resultados_copa`.
- `registrar_resultado(match_id, gols_casa, gols_visitante, penaltis_vencedor=None)` — UPDATE;
  valida: jogo existe, gols ≥ 0, pênaltis só no mata-mata e só em caso de empate.
- `classificacao_grupos(estado) -> dict[str, DataFrame]` — tabela real de cada grupo
  (colunas em português: posicao, selecao, jogos, vitorias, empates, derrotas, gols_pro,
  gols_contra, saldo_gols, pontos), critério: pontos → saldo → gols pró.
- `propagar_classificados(estado)` — quando os 72 jogos tiverem placar: preenche os
  `time_casa`/`time_visitante` reais de M73..M88 (slots `1X`/`2X` + 8 melhores terceiros,
  **reusando** `_resolver_terceiros`/`linear_sum_assignment` de `src/monte_carlo.py` com os
  stats reais); a cada resultado de mata-mata registrado, resolve `W##`/`RU##` nas fases
  seguintes via `winner_advances_to`/`loser_advances_to`.
- `python src/estado_torneio.py [--reset]` imprime inventário: total de jogos, realizados ×
  pendentes por fase/rodada, classificação atual dos grupos com resultados reais.

## Plano
1. Invocar as skills do Supabase; conferir schema existente com `list_tables` (MCP) antes do DDL.
2. Escrever DDL + seed (COPY) com a proteção `--reset`.
3. Implementar dataclasses + `carregar_estado` + `classificacao_grupos`.
4. Implementar `registrar_resultado` e `propagar_classificados` (reuso do matching de terceiros).
5. Rodar o script, registrar 1 resultado de teste, conferir a Verificação, desfazer o teste
   (`UPDATE ... SET gols_casa = NULL, gols_visitante = NULL`).

## Verificação (SQL)
```sql
-- 104 jogos: 72 de grupos (rodadas 1-3, 24 por rodada) + 32 de mata-mata sem times
SELECT fase, rodada, count(*) AS jogos,
       count(*) FILTER (WHERE gols_casa IS NOT NULL) AS realizados,
       count(*) FILTER (WHERE time_casa IS NULL) AS sem_times
FROM resultados_copa GROUP BY fase, rodada ORDER BY min(data);

-- todo jogo de grupo é intra-grupo e tem grupo A..L
SELECT count(*) FROM resultados_copa WHERE fase = 'Grupos' AND (grupo IS NULL OR rodada NOT BETWEEN 1 AND 3);
-- esperado: 0
```
