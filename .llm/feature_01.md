# Feature 01 — Bronze: ingestão do results.csv

## Contexto
Primeira camada do medallion. Guardar o dado cru de `data/results.csv`, sem transformar.

## Objetivo
Ler `data/results.csv` e gravar como `bronze_jogos` no banco, já com as colunas renomeadas
para português (dicionário no `prd.md`).

## Entrada
- `data/results.csv` (colunas originais: date, home_team, away_team, home_score, away_score, tournament, city, country, neutral). ~49.450 linhas (1872 → jogos agendados de 2026).

## Saída
- Tabela `bronze_jogos` com `id` (PK) + colunas: `data, time_casa, time_visitante, gols_casa, gols_visitante, torneio, cidade, pais, neutro`.

## Requisitos
1. Ler o caminho do CSV de variável de ambiente (`CAMINHO_CSV`, default `data/results.csv`) ou argumento de linha de comando.
2. **Renomear todas as colunas para português** na ingestão (dicionário do `prd.md`).
3. Não limpar nem filtrar — bronze é o dado como chegou. Conversões mínimas de tipo apenas:
   - `data` → `date`.
   - `gols_casa`/`gols_visitante` → **inteiro nullable**: os 72 jogos da Copa 2026 vêm com `NA` → gravar `NULL` (pandas lê `NA` como `NaN`; converter para `Int64`).
   - `neutro` → `boolean` (TRUE/FALSE).
   - `torneio`, `cidade`, `pais` e os nomes de seleção ficam **como vieram (em inglês)**.
   - Atenção ao parsing: 77 linhas têm vírgula embutida em `city` entre aspas (ex.: `"Washington, D.C."`); o parser CSV padrão do pandas trata isso corretamente.
4. Imprimir inventário: nº de linhas, tipos e % de nulos por coluna.

## Saída no banco (schema)
- `id bigint generated always as identity primary key, data date, time_casa text, time_visitante text, gols_casa integer, gols_visitante integer, torneio text, cidade text, pais text, neutro boolean`.
- Gravar de forma **idempotente**: `DROP TABLE IF EXISTS` + `CREATE` + carga via `COPY` (ver Convenções de implementação no `prd.md`).

## Critérios de aceite
- `bronze_jogos` tem o mesmo nº de linhas do CSV (≈ 49.450).
- Todas as colunas estão em português; nenhuma em inglês.
- Os 72 jogos da Copa 2026 têm `gols_casa`/`gols_visitante` nulos.

## Verificação (SQL)
```sql
SELECT COUNT(*) AS linhas FROM bronze_jogos;                              -- ≈ 49450
SELECT data, time_casa, time_visitante, gols_casa, gols_visitante FROM bronze_jogos ORDER BY data LIMIT 5;
SELECT MIN(data) AS mais_antigo, MAX(data) AS mais_recente FROM bronze_jogos;   -- 1872-11-30 .. 2026-06-27
SELECT COUNT(*) FROM bronze_jogos WHERE gols_casa IS NULL;                -- 72 (Copa 2026)
```

## Plano de implementação
1. Criar a infraestrutura compartilhada: `requirements.txt`, `.env.example`, `.gitignore` (ignora `.env`, `.venv/`, `__pycache__/`), e `src/db.py` (`get_engine` / `get_raw_connection`).
2. Ler `results.csv` com pandas; `parse_dates=["date"]`.
3. Converter gols para `Int64` e `neutral` para `bool`; aplicar `df.rename(...)` com o mapa do `prd.md`.
4. Imprimir o inventário.
5. Gravar `bronze_jogos` (DROP+CREATE+COPY, `NULL ''`).

## Para explicar enquanto desenvolve (~7 min)
- O que é a camada bronze e por que nunca se edita o dado cru.
- Por que padronizar o idioma das colunas já na porta de entrada (consistência do projeto).
- Por que rodar um inventário antes de qualquer transformação.
