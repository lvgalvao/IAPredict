# Feature 08 — Monte Carlo: simulação do torneio

## Contexto
Uma simulação é aleatória e não diz nada. Mil simulações e a frequência viram probabilidade.

> Peça o **plano antes do código**. Pré-compute as 1000 rodadas ANTES da live.

## Objetivo
Simular a Copa 2026 N=1000 vezes e gravar a probabilidade de cada seleção por fase em `gold_probabilidades_copa`.

## Entrada (três fontes — ver "De onde vem cada peça da Copa" no `prd.md`)
- **Jogos de grupo (72):** `silver_copa2026` (confrontos + `neutro`, vindos do `results.csv`).
- **Grupos A–L:** `data/grupos_copa2026.csv` (`group,position,nation`).
- **Mata-mata (M73–M104):** `data/calendario_copa2026.csv` (slots + `winner/loser_advances_to`).
- Modelos `models/*.pkl` e `src/poisson.py` (grade de Poisson) para sortear placares.

## Saída
- `gold_probabilidades_copa`: `id` PK + `selecao, prob_grupo, prob_oitavas, prob_quartas, prob_semi, prob_final, prob_campea` (48 linhas).
- Mapa fase → coluna: `prob_grupo` = passou da fase de grupos (chegou ao R32); `prob_oitavas` = R16;
  `prob_quartas` = QF; `prob_semi` = SF; `prob_final` = chegou à final; `prob_campea` = venceu a final.

## Requisitos (parâmetros fixos — ver `prd.md`)
1. **Fase de grupos:** simular os 72 jogos (placar via `np.random.poisson(λ)` de cada lado, λ de `prever_jogo`).
   Classificar cada grupo por **pontos → saldo de gols → gols pró → sorteio aleatório** → 1º/2º/3º.
2. **8 melhores terceiros:** rankear os 12 terceiros (mesmo critério), pegar os 8 melhores e mapeá-los
   aos slots `3xxxx` por **matching bipartido** respeitando a elegibilidade de cada slot
   (`scipy.optimize.linear_sum_assignment`) — numa função própria.
3. **Mata-mata em ordem de rodada** (R32 → R16 → QF → SF → 3º/Final), resolvendo `home_slot`/`away_slot`
   pelos slots já preenchidos (`1A/2B/3xxxx/W##/RU##`); gravar `W<match>` (vencedor) e, nas semis, `RU<match>` (perdedor).
   - Mata-mata em sede **neutra** (`neutro=True`). Empate no placar → vencedor **50/50** (pênaltis).
4. Sortear placares com a Poisson de `src/poisson.py` (consistência com previsão/validação).
5. Rodar **N = 1000** vezes com **`seed = 42`** (np.random) para reprodutibilidade. λ dos confrontos memoizados (cache).
6. Agregar a frequência por fase/seleção e gravar `gold_probabilidades_copa`.
> `match_date`/`match_time` do calendário NÃO entram na simulação (não mudam quem ganha) — reservados ao agente do dia 3.

## Critérios de aceite
- Soma de `prob_campea` de todas as seleções ≈ 100%.
- `SUM(prob_grupo)` ≈ 32 (exatamente os que passam da fase de grupos).
- Monotonicidade por seleção: `prob_grupo ≥ prob_oitavas ≥ … ≥ prob_campea`.
- Favoritas coerentes no topo (o "palpite da máquina": Espanha, Argentina, França, Brasil…).

## Verificação (SQL)
```sql
SELECT selecao, ROUND((prob_campea * 100)::numeric, 1) AS pct FROM gold_probabilidades_copa ORDER BY prob_campea DESC LIMIT 10;
SELECT ROUND((SUM(prob_campea) * 100)::numeric, 1) AS total_pct FROM gold_probabilidades_copa;   -- ~100
SELECT ROUND(SUM(prob_grupo)::numeric, 1) FROM gold_probabilidades_copa;                         -- ~32
SELECT COUNT(*) FROM gold_probabilidades_copa;                                                   -- 48
```

## Plano de implementação
1. Carregar grupos, mata-mata, modelos; ler os 72 jogos de `silver_copa2026`; pré-computar λ (cache).
2. Implementar uma simulação: grupos → classificação → terceiros (matching) → slots → mata-mata.
3. Registrar a fase máxima de cada seleção por simulação; acumular ao longo de N=1000.
4. Converter contagens em probabilidades; gravar `gold_probabilidades_copa` (DROP+CREATE+COPY).

## Para explicar enquanto desenvolve (~7 min)
- Monte Carlo: rodar processo aleatório milhares de vezes e agregar.
- Por que uma rodada é inútil e mil viram probabilidade; o que é `seed`.
- Por que pré-computamos. Fecho: esta tabela é o palpite da máquina — entra no bolão.
