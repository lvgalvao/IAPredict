# PRD — IAPredict · Previsão da Copa 2026 (Humanos vs. Máquinas)

## Visão geral
Pipeline de ML que estima, de forma probabilística, o desempenho de cada seleção na Copa
2026. O modelo estima gols esperados por jogo (Poisson), converte em probabilidades de
resultado e simula o torneio milhares de vezes (Monte Carlo). A previsão final compete, num
bolão, contra os palpites humanos.

## Regra inegociável — anti data leakage
O modelo treina SOMENTE em dados históricos. Os 72 jogos da Copa 2026 ficam separados e
NUNCA entram no treino.

## Estrutura do projeto
```
IAPredict/
├── .llm/
│   ├── prd.md              <- este arquivo
│   ├── feature_01.md ...   <- as features (spec + plano)
│   └── feature_09.md
├── data/
│   ├── results.csv             <- jogos internacionais (Kaggle, 1872→2026); inclui os 72 jogos de grupo da Copa
│   ├── calendario_copa2026.csv <- mata-mata da Copa (M73–M104): slots + advances_to (referência fixa)
│   └── grupos_copa2026.csv     <- grupos A–L da Copa (group,position,nation) (referência fixa)
├── src/                    <- código gerado (um módulo por feature + compartilhados)
│   ├── db.py               <- conexão reutilizável (get_engine / get_raw_connection)
│   ├── bronze.py · silver.py · pesos.py · elo.py · gold.py
│   ├── treino.py · previsao.py · monte_carlo.py
│   ├── poisson.py          <- utilitários de Poisson (probabilidades V/E/D) — compartilhado
│   └── bandeiras.py        <- nome da seleção → emoji de bandeira (feature_09)
├── models/                 <- modelos treinados (.pkl)
├── requirements.txt        <- pandas, sqlalchemy, psycopg2-binary, python-dotenv, statsmodels, scipy, streamlit
└── app.py                  <- dashboard Streamlit (feature_09)
```

## Acesso ao banco — preferir connection string (não MCP)
Para gravar dados, use **connection string direta** (ex.: SQLAlchemy/psycopg via `DATABASE_URL`),
**não o MCP**. Inserir ~50k linhas em lote por connection string é muito mais rápido — o MCP
tem overhead de protocolo por chamada e é melhor para ações pontuais, não carga em massa.

Logo no início do projeto, gerar um **`.env.example`** com as variáveis de conexão:
```
# .env.example
DATABASE_URL=postgresql://usuario:senha@host:5432/iapredict
CAMINHO_CSV=data/results.csv
```
O `.env` real (com credenciais) fica no `.gitignore`; versionar só o `.env.example`.

## De onde vem cada peça da Copa 2026 (importante — evita confusão na feature_08)
A simulação monta a Copa a partir de **três fontes** distintas:
1. **Jogos da fase de grupos (72 confrontos + mando):** vêm de `silver_copa2026` — ou seja, do
   próprio `results.csv`, que já traz os 72 jogos de grupo agendados (com placar `NA`, ainda não
   jogados). É de lá que saem `time_casa`, `time_visitante` e `neutro` de cada jogo de grupo.
2. **Rótulos de grupo A–L:** vêm de `data/grupos_copa2026.csv` (`group,position,nation`) — mapeiam
   cada seleção ao seu grupo. Necessário porque `silver_copa2026` não carrega o rótulo do grupo;
   `position` é o pote/seeding do sorteio (não a classificação final, que a simulação calcula).
3. **Estrutura do mata-mata (32 jogos M73–M104):** vem de `data/calendario_copa2026.csv` — slots
   simbólicos + `winner/loser_advances_to`. Os jogos de grupo M1–M72 NÃO estão nesse arquivo.

## Calendário e chaveamento da Copa 2026 — `data/calendario_copa2026.csv`
Dado de **referência fixa** do projeto (não é transformado por nenhuma feature; é consumido).
Contém **apenas o mata-mata** (R32 → Final, jogos M73–M104). Resolve a **estrutura do torneio**
(essencial para o Monte Carlo chegar ao campeão) e as **datas** (para o agente diário do dia 3).

Schema:
```
match_id, round, match_date, match_time, home_slot, away_slot, winner_advances_to, loser_advances_to
```

Os confrontos usam **slots simbólicos**, resolvidos durante a simulação (não são times fixos):
- `1A`, `2B` = 1º/2º colocado do grupo A/B.
- `3ABCDF` = um dos **melhores terceiros** vindo desse conjunto de grupos (regra oficial da Copa de 48).
- `W74` = vencedor da partida M74; `RU101` = perdedor (runner-up) da semifinal M101 (vai pro 3º lugar).

Regras de uso (implementadas na feature_08):
- A simulação resolve **em ordem de rodada** (R32 → R16 → QF → SF → Final/3º), preenchendo
  `W##`/`RU##` via `winner_advances_to`/`loser_advances_to` à medida que cada jogo é simulado.
- A seleção dos **8 melhores terceiros** e seu mapeamento para os slots `3xxxx` deve ficar numa
  função própria (é a regra mais delicada do chaveamento).
- `match_date`/`match_time`: ignorados na simulação (não mudam quem ganha); usados pelo agente do dia 3.

## Convenção de idioma — TUDO EM PORTUGUÊS
Nenhum nome de coluna, tabela ou artefato em inglês. Use o dicionário abaixo SEM exceção.

> **Exceção — valores de dado:** os *valores* de `torneio` e de `time_casa`/`time_visitante`
> (nomes de torneio e de seleção, ex.: "FIFA World Cup", "Brazil", "Spain") ficam **no idioma
> original do `results.csv`** — não traduzir. Traduzir esses valores não traz ganho e ainda
> arrisca quebrar joins, a padronização de nomes e a leitura do calendário da Copa. A regra de
> português vale para a *estrutura* (colunas, tabelas, artefatos), não para o *conteúdo* das células.

### Dicionário de dados — `data/results.csv` (entrada)
Renomear as colunas originais do CSV logo na ingestão:

| Original (CSV) | Usar (português) |
|----------------|------------------|
| date | `data` |
| home_team | `time_casa` |
| away_team | `time_visitante` |
| home_score | `gols_casa` |
| away_score | `gols_visitante` |
| tournament | `torneio` |
| city | `cidade` |
| country | `pais` |
| neutral | `neutro` |

### Colunas derivadas (criadas no pipeline)
| Coluna | Significado |
|--------|-------------|
| `eh_amistoso` | jogo é amistoso (booleano) |
| `peso_torneio` | importância do tipo de jogo (1/2/3) |
| `peso_recencia` | decaimento por idade (meia-vida 5 anos) |
| `elo_casa`, `elo_visitante` | ELO pré-jogo de cada time |
| `dif_elo` | `elo_casa` − `elo_visitante` |
| `peso_amostra` | `peso_torneio` × `peso_recencia` |
| `gols_esperados_casa`, `gols_esperados_visitante` | λ do Poisson (xG) |
| `prob_vitoria`, `prob_empate`, `prob_derrota` | probabilidades de resultado |
| `prob_campea` | probabilidade de ser campeã |

### Tabelas no banco (agrupadas por camada — o prefixo torna a arquitetura medallion visível)
- **Bronze** (dado cru): `bronze_jogos`
- **Silver** (limpo / enriquecido): `silver_jogos` · `silver_copa2026` · `silver_ponderado` ·
  `silver_elo_pre_jogo` · `silver_elo_atual`
- **Gold** (pronto para consumo): `gold_atributos` · `gold_probabilidades_copa`
- **Saídas de modelo/avaliação** (NÃO são camadas medallion — sem prefixo de propósito):
  `metricas_validacao` · `previsoes` · `experimentos_mae`

### Artefatos de modelo
`models/modelo_poisson_casa.pkl` · `models/modelo_poisson_visitante.pkl` ·
`models/colunas_atributos.pkl`

## As 9 features
| # | Feature | Saída |
|---|---------|-------|
| 01 | Bronze — ingestão do `results.csv` | `bronze_jogos` |
| 02 | Silver — limpeza + anti-leakage | `silver_jogos`, `silver_copa2026` |
| 03 | Pesos — torneio + recência | `silver_ponderado` |
| 04 | ELO — força das seleções | `silver_elo_pre_jogo`, `silver_elo_atual` |
| 05 | Atributos Gold — tabela de treino | `gold_atributos` |
| 06 | Treino Poisson + validação | `.pkl` + `metricas_validacao` |
| 07 | Previsão de partida + experimentos | `previsoes`, `experimentos_mae` |
| 08 | Monte Carlo — simulação | `gold_probabilidades_copa` |
| 09 | Dashboard no Streamlit | `app.py` (3 páginas) |

## Parâmetros canônicos (valores fixos — reproduzir exatamente)
Estes são os valores que definem os resultados do pipeline. Não improvisar; usar exatamente.

**Janela e identificação**
- Janela temporal: só jogos com `data >= 2006-01-01`.
- Copa 2026 = os jogos sem placar (`gols_casa IS NULL`) no `results.csv` → exatamente 72 jogos
  (`FIFA World Cup`, 2026-06-11 a 27). Esse é o critério de separação anti-leakage (feature_02).
- Idioma dos valores: `torneio` e nomes de seleção ficam **em inglês** (crus do `results.csv`).

**`peso_torneio` (ordinal 1/2/3) — classificação por nome do torneio (feature_03)**
- Avaliar nesta ordem (igualdade exata primeiro, para "FIFA World Cup qualification" cair em 2):
- **Nível 3** (set exato): `FIFA World Cup`, `Confederations Cup`, `CONMEBOL–UEFA Cup of Champions`.
- **Nível 2:** nome contém `qualification` **ou** `nations league` (case-insensitive), **ou** está em
  {`UEFA Euro`, `Copa América`, `African Cup of Nations`, `AFC Asian Cup`, `Gold Cup`, `Oceania Nations Cup`}.
- **Nível 1 (default):** `Friendly` + todo o resto (cauda longa de torneios menores/regionais).

**`peso_recencia` (feature_03)**
- `peso_recencia = 0.5 ** (idade_anos / 5)`, com `idade_anos = (DATA_REF - data).days / 365.25`.
- `DATA_REF = 2026-06-11` (início da Copa). Garante `peso_recencia ∈ (0, 1]`.

**ELO (feature_04)** — todos começam em **1500**; processado em ordem `(data, id)`.
- Expectativa: `E_casa = 1 / (1 + 10 ** ((elo_visit - elo_casa - HFA) / 400))`, `E_visit = 1 - E_casa`.
- **HFA (mando) = 100** quando `neutro = False`; **0** quando `neutro = True`. Sem multiplicador de goleada.
- Resultado real `S_casa`: vitória=1 / empate=0.5 / derrota=0.
- **K por `peso_torneio`**: 1→20 · 2→40 · 3→60. Atualização: `elo += K·(S − E)`. Grava-se o ELO **pré-jogo**.
- `eh_amistoso = (torneio == 'Friendly')`.

**Treino Poisson (feature_06)**
- Dois GLM Poisson (statsmodels), `var_weights = peso_torneio × peso_recencia` no treino.
- **6 atributos** (e nada mais): `elo_casa, elo_visitante, dif_elo, neutro, peso_torneio, peso_recencia`
  (`neutro` como inteiro 0/1; matriz com `add_constant`). `dif_elo` é colinear → statsmodels resolve via
  pseudo-inversa; predições corretas. Salvar a lista em `colunas_atributos.pkl`.
- **Split temporal**: treino `data < 2024-01-01`; teste `data >= 2024-01-01`.
- Treino só com jogos competitivos (excluir `eh_amistoso = true`).

**Probabilidade de resultado (feature_06, reaproveitada em 07/08)** — em `src/poisson.py`:
- Placar = duas Poisson independentes (λ_casa, λ_visit), grade até `MAX_GOLS = 10`.
- `probabilidades_resultado → (P(vitória), P(empate), P(derrota))`; resultado = argmax.

**Previsão (feature_07)**
- `prever_jogo` usa o ELO de `silver_elo_atual`; para a Copa, `peso_torneio = 3` e `peso_recencia = 1.0` (jogo no presente).
- Experimentos: recalcular `peso_recencia` de cada config e **re-treinar**; configs `sem_recencia`
  (peso_recencia=1.0 → var_weights = peso_torneio), `meia_vida_3`, `meia_vida_5`, `meia_vida_10`.

**Monte Carlo (feature_08)** — `N = 1000`, `seed = 42`.
- Desempate de grupo: pontos → saldo de gols → gols pró → sorteio aleatório.
- 8 melhores terceiros → slots `3xxxx` por **matching bipartido** respeitando a elegibilidade de cada
  slot (`scipy.optimize.linear_sum_assignment`).
- Mata-mata em sede **neutra** (`neutro=True`); empate no placar → vencedor 50/50 (pênaltis).
- Colunas de fase: `prob_grupo` = passou da fase de grupos (chegou ao R32); `prob_oitavas` = R16;
  `prob_quartas` = QF; `prob_semi` = SF; `prob_final` = chegou à final; `prob_campea` = venceu a final.
- Sem confederação como feature (era origem de viés pró-América do Sul).

## Convenções de implementação (código)
- **Um módulo por feature** em `src/` (`bronze.py`, `silver.py`, …), executável como `python src/<x>.py`.
  Imports entre eles são **flat** (`from db import …`) — o diretório `src/` entra no `sys.path` ao rodar
  o script (e o `app.py` faz `sys.path.insert(0, "src")`). Não transformar `src/` em pacote.
- **Conexão**: `src/db.py` expõe `get_engine()` (SQLAlchemy, p/ ler com pandas) e `get_raw_connection()`
  (psycopg2 cru, p/ `COPY`). Ambos leem `DATABASE_URL` via `python-dotenv`.
- **Escrita de tabelas**: idempotente — `DROP TABLE IF EXISTS` + `CREATE TABLE` com
  `id bigint generated always as identity primary key` + carga em massa via `COPY ... FROM STDIN`
  (buffer CSV em memória, `NULL ''`). Identificadores em lowercase snake_case.
- **Tipos**: `data` → `date`; gols → `integer` (nullable na bronze, `NA`→`NULL`); `neutro` → `boolean`;
  ELO/pesos/probabilidades → `double precision`.
- Cada script imprime um **relatório/inventário** e a tabela pode ser conferida pela **Verificação (SQL)**.

## Monte Carlo — estrutura do mata-mata (`data/calendario_copa2026.csv`):

match_id,round,match_date,match_time,home_slot,away_slot,winner_advances_to,loser_advances_to
M73,R32,2026-06-28,20:00,2A,2B,M90,
M74,R32,2026-06-29,21:30,1E,3ABCDF,M89,
M75,R32,2026-06-30,02:00,1F,2C,M90,
M76,R32,2026-06-29,18:00,1C,2F,M91,
M77,R32,2026-06-30,22:00,1I,3CDFGH,M89,
M78,R32,2026-06-30,18:00,2E,2I,M91,
M79,R32,2026-07-01,02:00,1A,3CEFHI,M92,
M80,R32,2026-07-01,17:00,1L,3EHIJK,M92,
M81,R32,2026-07-02,01:00,1D,3BEFIJ,M94,
M82,R32,2026-07-01,21:00,1G,3AEHIJ,M94,
M83,R32,2026-07-03,00:00,2K,2L,M93,
M84,R32,2026-07-02,20:00,1H,2J,M93,
M85,R32,2026-07-03,04:00,1B,3EFGIJ,M96,
M86,R32,2026-07-03,23:00,1J,2H,M95,
M87,R32,2026-07-04,02:30,1K,3DEIJL,M96,
M88,R32,2026-07-03,19:00,2D,2G,M95,
M89,R16,2026-07-04,22:00,W74,W77,M97,
M90,R16,2026-07-04,18:00,W73,W75,M97,
M91,R16,2026-07-05,21:00,W76,W78,M99,
M92,R16,2026-07-06,01:00,W79,W80,M99,
M93,R16,2026-07-06,20:00,W83,W84,M98,
M94,R16,2026-07-07,01:00,W81,W82,M98,
M95,R16,2026-07-07,17:00,W86,W88,M100,
M96,R16,2026-07-07,21:00,W85,W87,M100,
M97,QF,2026-07-09,21:00,W89,W90,M101,
M98,QF,2026-07-10,20:00,W93,W94,M101,
M99,QF,2026-07-11,22:00,W91,W92,M102,
M100,QF,2026-07-12,02:00,W95,W96,M102,
M101,SF,2026-07-14,20:00,W97,W98,M104,M103
M102,SF,2026-07-15,20:00,W99,W100,M104,M103
M103,3rd,2026-07-18,22:00,RU101,RU102,,
M104,Final,2026-07-19,20:00,W101,W102,,

Fase de grupo

group;position;nation
A;1;Mexico
A;2;South Africa
A;3;South Korea
A;4;Czech Republic
B;1;Canada
B;2;Bosnia and Herzegovina
B;3;Qatar
B;4;Switzerland
C;1;Brazil
C;2;Morocco
C;3;Haiti
C;4;Scotland
D;1;United States
D;2;Paraguay
D;3;Australia
D;4;Turkey
E;1;Germany
E;2;Curaçao
E;3;Ivory Coast
E;4;Ecuador
F;1;Netherlands
F;2;Japan
F;3;Sweden
F;4;Tunisia
G;1;Belgium
G;2;Egypt
G;3;Iran
G;4;New Zealand
H;1;Spain
H;2;Cape Verde
H;3;Saudi Arabia
H;4;Uruguay
I;1;France
I;2;Senegal
I;3;Iraq
I;4;Norway
J;1;Argentina
J;2;Algeria
J;3;Austria
J;4;Jordan
K;1;Portugal
K;2;DR Congo
K;3;Uzbekistan
K;4;Colombia
L;1;England
L;2;Croatia
L;3;Ghana
L;4;Panama

## Fluxo de trabalho (Spec-Driven)
Para cada feature: ler `feature_NN.md` → conferir o **Plano** → o Claude Code implementa →
rodar a **Verificação (SQL)** → seguir.