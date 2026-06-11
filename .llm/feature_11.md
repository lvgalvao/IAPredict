# Feature 11 — Monte Carlo condicional + eliminação matemática

> Fase **Agente Copa 2026**. Depende da feature_10 (`resultados_copa`, `estado_torneio.py`).
> O coração do agente: **estatística pura em Python, o LLM nunca calcula nada**.

## Objetivo
Motor de Monte Carlo que parte do **estado real acumulado** (resultados já registrados) e
simula apenas os jogos restantes N vezes, produzindo probabilidades **condicionais** de
classificação e título — se o Brasil perdeu o 1º jogo, as simulações partem de 0 pontos
reais e a probabilidade cai de forma matematicamente justa. Também identifica seleções
**matematicamente eliminadas**. Snapshots ficam no histórico `gold_probabilidades_rodada`.

## Skills a invocar (antes de codar)
- `supabase-postgres-best-practices` — DDL append-only, índice por rótulo de rodada.

(Nenhuma skill de IA aqui: este módulo é determinístico, sem LLM.)

## Spec

### Tabela `gold_probabilidades_rodada` (histórico — append-only, NÃO dropar)
```sql
CREATE TABLE IF NOT EXISTS gold_probabilidades_rodada (
    id             bigint generated always as identity primary key,
    rotulo_rodada  text NOT NULL,    -- ex.: 'pre_torneio', 'grupos_rodada_1', 'pos_oitavas'
    selecao        text NOT NULL,
    prob_grupo     double precision,
    prob_oitavas   double precision,
    prob_quartas   double precision,
    prob_semi      double precision,
    prob_final     double precision,
    prob_campea    double precision,
    eliminada      boolean,
    criado_em      timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_prob_rodada_rotulo ON gold_probabilidades_rodada (rotulo_rodada, selecao);
```
Cada execução grava 48 linhas novas (uma por seleção) com o mesmo `rotulo_rodada`.
A "rodada vigente" é sempre o lote com `max(criado_em)`.

### Módulo `src/monte_carlo_condicional.py`
- **Reuso, não duplicação**: importar de `monte_carlo.py` (`preparar`-like, cache de λ,
  `_resolver_terceiros`, `slots_terceiros`, `NIVEL_VENCEDOR`, `COLS_PROB`) e de
  `estado_torneio.py` (`carregar_estado`). Extrair/parametrizar helpers do `monte_carlo.py`
  se necessário em vez de copiar.
- `simular_condicional(estado, n_simulacoes=10_000, seed=42) -> DataFrame`:
  1. Acumula stats REAIS (pontos, saldo, gols pró) dos jogos de grupo com placar.
  2. Para cada simulação: sorteia via Poisson **apenas** os jogos com `gols_casa IS NULL`
     (λ do cache, modelos `.pkl` atuais, `peso_torneio=3`, `peso_recencia=1.0`);
     classifica grupos (pontos → saldo → gols pró → sorteio); resolve terceiros; mata-mata:
     confrontos reais já definidos são respeitados e jogos de mata-mata com resultado real
     registrado têm o vencedor FIXADO (não sorteia); o restante é simulado em sede neutra,
     empate → pênaltis 50/50.
  3. Agrega frequências → `prob_grupo .. prob_campea` (mesma semântica da feature_08).
- **Performance**: sortear os gols da fase de grupos **em lote** (matriz `N × jogos_pendentes`
  via `np.random.poisson(lam, size=N)`), para suportar N grande (meta do idea.md: centenas
  de milhares; padrão da live: 10.000 — já estabiliza os percentuais em segundos).
- `eliminadas_matematicamente(estado, df_probs) -> set[str]`:
  - Grupos: checagem analítica de pontos máximos (nem vencendo tudo alcança o 2º lugar do
    grupo) **combinada** com `prob_grupo == 0` nas N simulações (cobre a vaga de melhor 3º,
    cuja análise combinatória exata é impraticável — documentar a aproximação no docstring).
  - Mata-mata: perdeu jogo eliminatório real → eliminada.
- `executar(rotulo_rodada, n_simulacoes=10_000)` — orquestra: carrega estado → simula →
  marca eliminadas → grava snapshot (COPY) → devolve o DataFrame ordenado por `prob_campea`.
- `python src/monte_carlo_condicional.py --rodada grupos_rodada_1 [--n 10000]` imprime
  relatório: top 10 campeã, variação vs. snapshot anterior, eliminadas.
- Primeira execução (sem nenhum resultado registrado) grava `rotulo_rodada='pre_torneio'`
  — deve concordar com `gold_probabilidades_copa` (mesma seed/N ⇒ valores próximos).

## Plano
1. Invocar a skill de best practices; criar tabela + índice.
2. Refatorar helpers reutilizáveis do `monte_carlo.py` (sem mudar seu comportamento — re-rodar
   a Verificação da feature_08 depois).
3. Implementar acúmulo de stats reais + simulação condicional vetorizada na fase de grupos.
4. Implementar fixação de resultados reais no mata-mata + eliminação matemática.
5. Rodar `pre_torneio`; registrar um resultado de teste (ex. derrota do Brasil), rodar
   `grupos_rodada_1` e conferir que `prob_campea(Brazil)` caiu; desfazer o teste.

## Verificação (SQL)
```sql
-- soma de prob_campea ≈ 1.0 em cada snapshot
SELECT rotulo_rodada, round(sum(prob_campea)::numeric, 3) AS soma, count(*) AS selecoes
FROM gold_probabilidades_rodada GROUP BY rotulo_rodada;

-- probabilidade condicional reage ao resultado real (após o teste do passo 5)
SELECT rotulo_rodada, prob_campea, eliminada
FROM gold_probabilidades_rodada WHERE selecao = 'Brazil' ORDER BY criado_em;
```
