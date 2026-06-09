import sys, os
import pandas as pd
from sqlalchemy import create_engine
from src.prediction import prever_jogo

engine = create_engine(os.environ["DATABASE_URL"])
casa = sys.argv[1] if len(sys.argv) > 1 else "Brazil"
fora = sys.argv[2] if len(sys.argv) > 2 else "Argentina"

elo = pd.read_sql("SELECT selecao, elo FROM silver_elo_atual", engine).set_index("selecao")["elo"]
p = prever_jogo(casa, fora, neutro=True, peso_torneio=3)

print(f"\n{casa} (ELO {elo[casa]:.0f})  x  {fora} (ELO {elo[fora]:.0f})")
print(f"xG: {casa} {p['gols_esperados_casa']:.2f}  |  {fora} {p['gols_esperados_visitante']:.2f}")
print(f"Vitória {casa}: {p['prob_vitoria']:.0%}  |  Empate: {p['prob_empate']:.0%}  |  Vitória {fora}: {p['prob_derrota']:.0%}")
print(f"Placar mais provável: {p['placar_mais_provavel']}")