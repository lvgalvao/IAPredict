# Feature 03 — Pesos: torneio + recência

## Contexto
Nem todo jogo importa igual. Vamos materializar isso em duas colunas de peso.

## Objetivo
Adicionar `peso_torneio` e `peso_recencia` ao silver, gerando `silver_ponderado`.

## Entrada
- `silver_jogos`.

## Saída
- `silver_ponderado`: todas as colunas de `silver_jogos` + `peso_torneio` (integer) + `peso_recencia` (double precision). `id` PK próprio.

## Requisitos
1. **`peso_torneio`** (ordinal 1/2/3) derivado do nome do `torneio`. Classificação por palavra-chave,
   avaliada **nesta ordem** (igualdade exata primeiro, para "FIFA World Cup qualification" cair em 2):
   - **Nível 3** (set exato): `FIFA World Cup`, `Confederations Cup`, `CONMEBOL–UEFA Cup of Champions`.
   - **Nível 2:** nome contém `qualification` **ou** `nations league` (case-insensitive), **ou** está em
     {`UEFA Euro`, `Copa América`, `African Cup of Nations`, `AFC Asian Cup`, `Gold Cup`, `Oceania Nations Cup`}.
   - **Nível 1 (default):** `Friendly` + todo o resto (cauda longa de torneios menores/regionais).
2. **`peso_recencia`** por decaimento exponencial, meia-vida 5 anos, ancorado em data fixa:
   `peso_recencia = 0.5 ** (idade_anos / 5)`, com `idade_anos = (DATA_REF - data).days / 365.25` e
   **`DATA_REF = 2026-06-11`** (início da Copa).
3. Não normalizar (uso relativo no treino).

## Critérios de aceite
- `peso_torneio` só assume {1, 2, 3}.
- `peso_recencia` em (0, 1], maior para jogos recentes.
- Distribuição esperada (referência): nível 1 ≈ 9.192 · nível 2 ≈ 10.085 · nível 3 ≈ 369.

## Verificação (SQL)
```sql
SELECT peso_torneio, COUNT(*) FROM silver_ponderado GROUP BY peso_torneio ORDER BY 1;   -- só {1,2,3}
SELECT data, ROUND(peso_recencia::numeric, 4) FROM silver_ponderado ORDER BY data DESC LIMIT 5;
SELECT MIN(peso_recencia), MAX(peso_recencia) FROM silver_ponderado;                    -- > 0 e <= 1
SELECT COUNT(*) FROM silver_ponderado;                                                  -- == silver_jogos
```

## Plano de implementação
1. Ler `silver_jogos`.
2. Função `classificar(torneio)` com a regra acima → `peso_torneio` (constantes `NIVEL3` e `CONTINENTAIS` no topo).
3. Calcular `idade_anos` a partir de `data` e `DATA_REF`; aplicar a fórmula da meia-vida.
4. Gravar `silver_ponderado` (DROP+CREATE+COPY).

## Para explicar enquanto desenvolve (~7 min)
- Os dois pesos medem eixos diferentes: tipo de jogo vs. recência.
- Decaimento contínuo em vez de "escada": transição suave, nunca zera.
- Construir a coluna não obriga a usá-la — isso é experimento (feature_07).
