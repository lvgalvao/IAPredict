# Agente de Previsão da Copa do Mundo 2026

O projeto consiste em transformar um código de previsão estático em um agente de IA que atualiza as probabilidades do torneio em tempo real, rodada a rodada.

---

## Fundação

O ponto de partida é o código original de previsão, que já calcula probabilidades baseadas em métricas como Elo e ranking FIFA antes do torneio começar. O agente vai partir desse estado inicial e atualizá-lo conforme os resultados reais chegam.

Para isso, o primeiro passo é construir uma estrutura de estado do torneio — dataclasses representando grupos, times, partidas e o bracket eliminatório — com persistência em JSON para salvar o estado entre as rodadas sem perder nada.

---

## Motor de Simulação

O coração do projeto é um motor de Monte Carlo que roda inteiramente em Python, sem envolver o LLM nos cálculos. A lógica é: dado o estado atual da tabela com os resultados já registrados, simular os jogos restantes centenas de milhares de vezes usando as forças originais das seleções para calcular probabilidade condicional de classificação e título.

O modelo de Poisson gera resultados realistas por jogo — cada simulação parte do estado real já acumulado e completa os jogos que ainda não aconteceram. O percentual de vezes que cada time classifica ou vence o torneio nessas simulações vira a probabilidade exibida.

Isso garante que se o Brasil perdeu o primeiro jogo, as simulações partem de 0 pontos reais, e a probabilidade cai de forma matematicamente justa. Não é o LLM estimando — é estatística pura.

A ideia é que nós tenhamos uma pagina de simulação onde registramos os resultados da primeira rodada, por exemplo, e o agente rode as tools que precisam para gerar os resultados que precisamos até a resposta final utilizando as tools e fazendo todo o context engineering corretamente com as tools.
---

## Tools do Agente


O agente orquestra tres tools principais.  A primeira consulta o estado atual dos grupos. A segunda dispara o motor de Monte Carlo e devolve as probabilidades atualizadas para todas as seleções. A terceira identifica times já matematicamente eliminados.

A regra fundamental é que o LLM nunca calcula nada diretamente — ele decide quais tools chamar, em qual ordem, e interpreta os resultados para gerar narrativa.

---

## Modo Palpiteiro

A quarta tool é o destaque da live. Sempre que o Brasil não estiver na primeira posição do ranking de probabilidades de título — independente de ter perdido ou não —, o agente ativa o Modo Palpiteiro. A tool faz uma busca na internet por informações recentes da Seleção Brasileira, como declarações de jogadores, histórico no torneio ou qualquer dado relevante, e passa esse contexto para o LLM gerar uma frase motivacional curta para o torcedor brasileiro acreditar no hexa, mesmo que a matemática aponte outro favorito. Quanto menor a probabilidade do Brasil, mais dramática e criativa a frase.

---

## Visualização

Um dashboard em Streamlit exibe as tabelas de grupos com os percentuais de classificação de cada time, um gráfico de barras com as probabilidades de título de todas as seleções, e o bracket do mata-mata atualizando conforme os classificados são definidos. Tudo atualiza ao vivo durante a live após cada resultado digitado.

