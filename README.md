# IAPredict — Previsão da Copa do Mundo 2026 🏆

Pipeline de Machine Learning que estima, de forma **probabilística**, o desempenho de cada
seleção na Copa do Mundo de 2026. O modelo aprende com o histórico de jogos internacionais,
estima os gols esperados de cada partida (Poisson), converte em probabilidades de resultado e
**simula o torneio 1000 vezes** (Monte Carlo) para responder: *quem leva a taça?*

O resultado é o "palpite da máquina" — que, num bolão, compete contra os palpites humanos.

> Construído com **Spec-Driven Development**: cada etapa nasce de uma especificação em
> [`.llm/`](.llm/) e produz um resultado verificável no banco. Veja o [PRD](.llm/prd.md).

---

## Como funciona

O projeto segue a **arquitetura medallion** (bronze → silver → gold) e culmina numa simulação
de Monte Carlo. São 9 etapas encadeadas:

| # | Etapa | Script | Saída |
|---|-------|--------|-------|
| 01 | **Bronze** — ingestão do CSV cru | `src/bronze.py` | `bronze_jogos` |
| 02 | **Silver** — limpeza + anti-leakage | `src/silver.py` | `silver_jogos`, `silver_copa2026` |
| 03 | **Pesos** — torneio + recência | `src/pesos.py` | `silver_ponderado` |
| 04 | **ELO** — força das seleções | `src/elo.py` | `silver_elo_pre_jogo`, `silver_elo_atual` |
| 05 | **Gold** — tabela de treino | `src/gold.py` | `gold_atributos` |
| 06 | **Treino Poisson** + validação | `src/treino.py` | `models/*.pkl`, `metricas_validacao` |
| 07 | **Previsão** + experimentos | `src/previsao.py` | `previsoes`, `experimentos_mae` |
| 08 | **Monte Carlo** — simulação | `src/monte_carlo.py` | `gold_probabilidades_copa` |
| 09 | **Dashboard** Streamlit | `app.py` | aplicação web (3 páginas) |

### Conceitos-chave
- **Anti–data leakage (regra inegociável):** os 72 jogos da Copa 2026 ficam **separados** e nunca
  entram no treino. O modelo aprende só com o passado.
- **Poisson:** gol é contagem (0, 1, 2, …); por isso modela-se a taxa de gols (λ = xG) com
  regressão de Poisson, não linear. Dois modelos: gols do mandante e do visitante.
- **ELO:** força dinâmica de cada seleção (começa em 1500, atualizada após cada jogo, em ordem
  cronológica). Considera mando de campo e o peso do torneio no fator K.
- **Monte Carlo:** uma simulação é ruído; mil simulações viram **probabilidade**. Cada Copa é
  sorteada do zero (grupos → mata-mata → campeão) e a frequência por fase vira a previsão final.

---

## Stack

- **Python** · pandas · NumPy · SciPy
- **statsmodels** (GLM Poisson)
- **Supabase / PostgreSQL** (persistência via `DATABASE_URL`, carga em massa por `COPY`)
- **Streamlit** (dashboard) · **Altair** (gráficos)

## Estrutura

```
IAPredict/
├── .llm/                 # PRD + as 9 especificações (spec-driven)
├── data/
│   ├── results.csv               # jogos internacionais (Kaggle, 1872→2026)
│   ├── grupos_copa2026.csv        # grupos A–L da Copa
│   └── calendario_copa2026.csv    # mata-mata da Copa (slots + chaveamento)
├── src/                  # um módulo por etapa + compartilhados (db, poisson, bandeiras)
├── models/               # modelos Poisson treinados (.pkl)
├── app.py                # dashboard Streamlit
└── requirements.txt
```

As tabelas no banco seguem a nomenclatura medallion: **bronze_** (cru) → **silver_** (limpo /
enriquecido) → **gold_** (pronto para consumo). Saídas de modelo (`metricas_validacao`,
`previsoes`, `experimentos_mae`) não levam prefixo de camada.

---

## Como rodar

### 1. Ambiente

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Conexão com o banco

Copie o `.env.example` para `.env` e preencha a connection string do Supabase/PostgreSQL:

```bash
cp .env.example .env
# edite .env:
# DATABASE_URL=postgresql://usuario:senha@host:5432/postgres
# CAMINHO_CSV=data/results.csv
```

### 3. Pipeline (na ordem)

```bash
python src/bronze.py      # 01 — ingestão
python src/silver.py      # 02 — limpeza + split anti-leakage
python src/pesos.py       # 03 — pesos
python src/elo.py         # 04 — ELO
python src/gold.py        # 05 — tabela de treino
python src/treino.py      # 06 — treina os modelos Poisson
python src/previsao.py    # 07 — previsões + experimentos
python src/monte_carlo.py # 08 — simulação de Monte Carlo (N=1000)
```

Cada script imprime um relatório e pode ser conferido pela **Verificação (SQL)** da spec
correspondente em `.llm/feature_NN.md`.

### 4. Dashboard

```bash
streamlit run app.py
```

Três páginas:
1. **Probabilidades pré-computadas** — as 12 seleções com maior chance de título (gráfico + tabela).
2. **Simulação ao vivo** — uma Copa inteira simulada a cada clique (grupos → mata-mata → campeão).
3. **Explorador de partidas** — escolha dois times e veja xG + probabilidades de vitória/empate/derrota.

Cada seleção aparece com a bandeira (emoji). Pronto para deploy no **Streamlit Cloud**
(definir `DATABASE_URL` em *Secrets*).

---

## O palpite da máquina

Validação no holdout temporal (jogos de 2024–2026): **~60% de acurácia** de resultado — acima
do baseline "sempre vence o mandante" (~47%). As favoritas ao título refletem o ranking de ELO
que o pipeline constrói, com Espanha e Argentina à frente, seguidas por França e Brasil.

> Os números exatos mudam a cada re-treino/simulação; consulte a página 1 do dashboard ou a
> tabela `gold_probabilidades_copa`.

---

## Sobre a imersão

Este projeto faz parte da [**Sua Jornada de Dados**](https://www.suajornadadedados.com.br) e da
[**Imersão Copa, Dados & IA**](https://lp.suajornadadedados.com.br/imersao-copa-dados-ia) — onde,
ao vivo, construímos este pipeline e usamos o **palpite da máquina** para prever quem vai ganhar a
Copa do Mundo 2026, num bolão contra os palpites humanos.

▶️ **Live no YouTube:** https://youtube.com/live/hvEFv-OLF88

## Referência

Projeto inspirado por / tomado como referência:
[**football_WorldCup_2026_predictions** — anesriad](https://github.com/anesriad/football_WorldCup_2026_predictions)
# IAPredict
