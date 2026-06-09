# Feature 09 — Dashboard no Streamlit

## Contexto
As features 06-08 geram o palpite da máquina (modelos + `gold_probabilidades_copa`). Falta dar
cara de produto: um app que qualquer pessoa abre e explora. Espelha o app de referência —
3 páginas: probabilidades pré-computadas, simulação ao vivo e explorador de partidas.

## Objetivo
Construir `app.py` (Streamlit) que leia os resultados do banco/modelos e apresente as 3 páginas.
Deve rodar local e deployar no Streamlit Cloud.

## Entrada
- Tabela `gold_probabilidades_copa` (do banco, via connection string) — página 1.
- Módulos de `src/` (`monte_carlo.simular_torneio_detalhado`, `previsao.prever_jogo`, `bandeiras`, `db`) e
  os dados de referência (`grupos_copa2026.csv`, `calendario_copa2026.csv`) + `models/*.pkl` — páginas 2 e 3.

## Saída
- App Streamlit (`app.py`) com seletor de página na barra lateral. Não é tabela — é produto.

## Páginas
1. **Probabilidades pré-computadas** — lê `gold_probabilidades_copa`; mostra as **12 seleções com maior
   chance de título**, ordenadas da maior para a menor: gráfico de barras (ordenado por %) + tabela por fase.
   (Estável: vem das 1000 rodadas.)
2. **Simulação ao vivo** — roda UMA simulação do **torneio inteiro** e mostra o **campeão** (com
   pódio: campeã/vice/3º), o **mata-mata por rodada** (32-avos → oitavas → quartas → semifinais →
   3º lugar → final, com o vencedor destacado e marca de pênaltis) e a **fase de grupos**
   (placares + classificação por grupo). (Aleatória: muda a cada clique.)
3. **Explorador de partidas** — escolher dois times + checkbox de campo neutro → xG + probabilidade de V/E/D.

## Bandeiras
Toda seleção aparece com o **emoji da sua bandeira** ao lado do nome, em todas as páginas
(gráfico, tabelas, placares, pódio e seletores). Mapeamento nome→bandeira em `src/bandeiras.py`
(Inglaterra/Escócia usam os emojis de subdivisão do Reino Unido; desconhecidas usam 🏳️).

## Colunas da tabela de classificação (em português)
`posicao, selecao, jogos, vitorias, empates, derrotas, gols_pro, gols_contra, saldo_gols, pontos`.
Valores de `selecao` ficam no idioma original (Brazil, Morocco...), precedidos da bandeira.

## Requisitos
1. Conexão ao banco por **connection string** (`DATABASE_URL`), não MCP. Reusar `src/db.get_engine()`.
2. Barra lateral com as 3 páginas; página 1 como padrão.
3. Página 1: ler `gold_probabilidades_copa`, ordenar por `prob_campea` (desc) e exibir as **12 maiores**;
   gráfico + tabela, com bandeiras. O gráfico deve ser **ordenado por %** (usar Altair com `sort="-x"`;
   `st.bar_chart` reordena alfabeticamente e não serve).
4. Página 2: rodar `simular_torneio_detalhado` UMA vez (torneio completo); renderizar campeão/pódio,
   o mata-mata por rodada e a classificação por grupo com as colunas em português acima. Sem cache (re-roda a cada clique).
5. Página 3: dois seletores de seleção (`format_func` com bandeira) + checkbox de campo neutro + botão;
   exibir `gols_esperados_*` e `prob_*` (peso_torneio=3).
6. Pronto para deploy no Streamlit Cloud (sem segredo hard-coded). Ponte: se `DATABASE_URL` estiver em
   `st.secrets`, copiar para `os.environ` antes de `get_engine()` (com try/except, pois local não tem secrets.toml).
7. Bandeiras (emoji) ao lado de cada seleção em todo o app.
8. Imports: `app.py` faz `sys.path.insert(0, "src")` e importa flat (`from monte_carlo import …`).
9. Cache: `@st.cache_resource` para engine/modelos/`preparar()`; `@st.cache_data` para `gold_probabilidades_copa`.

## Critérios de aceite
- `streamlit run app.py` sobe sem erro; as 3 páginas funcionam.
- Página 1 mostra as 12 seleções de maior `prob_campea`, **do maior para o menor** (gráfico e tabela).
- A classificação mostra as colunas em português; os nomes de seleção, no original, com bandeira.
- Página 2 simula o torneio inteiro até o campeão (mata-mata completo, 16+8+4+2+1+1 = 32 jogos).
- Cada seleção exibe a bandeira ao lado do nome nas três páginas.

## Verificação
```bash
streamlit run app.py        # abrir e navegar as 3 páginas
```
```python
# validação headless (sem navegador), via o executor oficial do Streamlit:
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("app.py").run(); assert not at.exception
at.sidebar.radio[0].set_value("Simulação ao vivo").run(); assert not at.exception
at.sidebar.radio[0].set_value("Explorador de partidas").run(); at.button[0].click().run(); assert not at.exception
```
```sql
-- a página 1 deve bater com (top 12):
SELECT selecao, ROUND((prob_campea*100)::numeric,1) AS pct FROM gold_probabilidades_copa ORDER BY prob_campea DESC LIMIT 12;
```

## Esqueleto (ajustado aos módulos reais do projeto)
```python
import os, sys
import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
try:  # ponte de segredo: Cloud usa st.secrets; local usa .env
    if "DATABASE_URL" in st.secrets and "DATABASE_URL" not in os.environ:
        os.environ["DATABASE_URL"] = st.secrets["DATABASE_URL"]
except Exception:
    pass

from db import get_engine
from previsao import PESO_TORNEIO_COPA, carregar_modelos, prever_jogo
from monte_carlo import NOMES_RODADA, preparar, simular_torneio_detalhado, slots_terceiros
from bandeiras import com_bandeira

st.set_page_config(page_title="IAPredict — Copa 2026", layout="wide")
TOP_N = 12

# Página 1: ler gold_probabilidades_copa (cacheado), top 12, gráfico Altair ordenado por % + tabela com bandeiras.
# Página 2: preparar() (cacheado) + simular_torneio_detalhado() (sem cache) → campeão/pódio + mata-mata + grupos.
# Página 3: selectbox(format_func=com_bandeira) + checkbox neutro + prever_jogo (modelos/elos cacheados).
```

## Plano de implementação
1. Criar `src/bandeiras.py` (nome → emoji).
2. Adicionar `simular_torneio_detalhado` a `src/monte_carlo.py` (torneio completo: grupos + mata-mata por rodada + campeão).
3. Criar `app.py`: ponte de segredo, sidebar, as 3 páginas, caches e bandeiras.
4. Validar headless (AppTest) e `streamlit run`; preparar deploy (DATABASE_URL nos Secrets; `.pkl` e CSVs no repo).

## Para explicar enquanto desenvolve (~7 min)
- O que é Streamlit: vira script Python em web app, sem escrever frontend.
- A diferença entre a página estável (probabilidades pré-computadas) e a ao vivo (1 rodada aleatória).
- Por que os nomes de coluna em português, mas os de seleção no original (com bandeira).
- Que isso vira a base do dia 3, onde o app passa a acompanhar a Copa em tempo real.
