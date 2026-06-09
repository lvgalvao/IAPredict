# Feature 02 — Silver: limpeza + anti-leakage

## Contexto
Bronze vira dado confiável: nomes padronizados, tipos certos, janela temporal e a separação
que protege o modelo de "trapacear".

## Objetivo
Limpar `bronze_jogos` e produzir as tabelas silver, já com o split anti-leakage.

## Entrada
- `bronze_jogos`.

## Saída
- `silver_jogos`: histórico limpo (sem a Copa 2026), com coluna `eh_amistoso`.
- `silver_copa2026`: os 72 jogos da Copa 2026, separados.
- Mesmo schema nas duas: `id` PK + `data, time_casa, time_visitante, gols_casa, gols_visitante, torneio, cidade, pais, neutro, eh_amistoso`.

## Requisitos
1. Padronizar nomes de seleção (`time_casa`, `time_visitante`) com um dicionário único + `strip()`.
   Os dados do Kaggle já são consistentes (as "variantes" são países distintos legítimos —
   Republic of Ireland × Northern Ireland, North/South Korea); o dicionário inicia praticamente
   vazio, mas fica pronto. **Nomes ficam em inglês** (não traduzir — ver `prd.md`).
2. Acertar tipos e remover **duplicatas exatas** (linhas idênticas nas colunas de negócio).
3. **Anti-leakage (split):**
   - `silver_copa2026` = jogos com `gols_casa IS NULL` (os 72 jogos futuros da Copa 2026).
   - `silver_jogos` = o restante, **filtrado para `data >= 2006-01-01`** (histórico com placar).
4. Criar `eh_amistoso` (booleano) = `(torneio == 'Friendly')`.

## Observações importantes (evitam dúvida)
- O critério da Copa é **gols nulos**, não `torneio = 'FIFA World Cup'`: jogos de Copas passadas
  (2006–2022) são histórico válido e **permanecem** em `silver_jogos`.
- Jogos de 2026 **com placar** (amistosos/eliminatórias já disputados) também ficam em `silver_jogos`
  — só os 72 jogos não jogados da Copa saem. Resultado típico: ~19.646 em `silver_jogos`, 72 em `silver_copa2026`.

## Critérios de aceite
- `silver_jogos` não tem jogo da Copa 2026 nem anterior a 2006; 0 gols nulos.
- `silver_copa2026` tem 72 jogos.
- Sem nomes de seleção duplicados/variantes para o mesmo país.

## Verificação (SQL)
```sql
SELECT MIN(data) FROM silver_jogos;                              -- >= 2006-01-01
SELECT COUNT(*) FROM silver_jogos
  WHERE torneio = 'FIFA World Cup' AND data >= '2026-01-01';     -- 0 (anti-leakage)
SELECT COUNT(*) FROM silver_copa2026;                           -- 72
SELECT COUNT(*) FROM silver_jogos WHERE gols_casa IS NULL;      -- 0
SELECT eh_amistoso, COUNT(*) FROM silver_jogos GROUP BY eh_amistoso;
```
> Nota: o valor do torneio fica em inglês (`FIFA World Cup`), não `Copa do Mundo FIFA`.

## Plano de implementação
1. Ler `bronze_jogos` (reconverter gols para `Int64`, pois vêm do banco como float por causa dos nulos).
2. Aplicar dicionário/`strip` de nomes de seleção; remover duplicatas; derivar `eh_amistoso`.
3. Split: `gols_casa` nulo → `silver_copa2026`; resto com `data >= 2006` → `silver_jogos`.
4. Gravar ambas (DROP+CREATE+COPY).

## Para explicar enquanto desenvolve (~7 min)
- **Data leakage:** a lição mais importante. Treinar no que se quer prever engana.
- Por que padronizar nomes é trabalho real (conformar uma dimensão).
- Por que cortar em 2006.
