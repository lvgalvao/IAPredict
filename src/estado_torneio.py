"""Feature 10 — Estado do torneio ao vivo: fundação do agente Copa 2026.

Cria a tabela operacional ``resultados_copa`` (104 jogos: M1..M72 grupos, M73..M104
mata-mata) e expõe o estado do torneio como dataclasses (``Partida``, ``Grupo``,
``EstadoTorneio``), sempre reconstruído a partir do Supabase.

Atenção — exceção à convenção de DDL do pipeline: esta tabela é MUTÁVEL (recebe
UPDATEs durante a live). O seed destrutivo (``DROP TABLE``) só roda com a flag
``--reset``; sem ela, ``inicializar_estado()`` jamais destrói resultados registrados.

Uso: ``python src/estado_torneio.py [--reset]`` (a partir da raiz do repositório).
"""

from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass, field

import pandas as pd

from db import get_engine, get_raw_connection
from monte_carlo import _resolver_terceiros, slots_terceiros

TABELA = "resultados_copa"
ARQ_GRUPOS = "data/grupos_copa2026.csv"
ARQ_CALENDARIO = "data/calendario_copa2026.csv"

# Ordem cronológica das fases (mesma da Verificação SQL, que ordena por min(data)).
FASES_ORDEM = ["Grupos", "R32", "R16", "QF", "SF", "3rd", "Final"]

# Colunas de negócio (ordem da tabela; id e atualizado_em ficam com o banco).
COLUNAS = [
    "match_id", "fase", "rodada", "grupo", "data", "time_casa", "time_visitante",
    "gols_casa", "gols_visitante", "penaltis_vencedor", "neutro",
]

DDL = """
CREATE TABLE IF NOT EXISTS resultados_copa (
    id                bigint generated always as identity primary key,
    match_id          text UNIQUE NOT NULL,   -- M1..M72 (grupos, por ordem data,id) + M73..M104 (calendário)
    fase              text NOT NULL,          -- 'Grupos' | 'R32' | 'R16' | 'QF' | 'SF' | '3rd' | 'Final'
    rodada            integer,                -- 1..3 na fase de grupos; NULL no mata-mata
    grupo             text,                   -- 'A'..'L'; NULL no mata-mata
    data              date,
    time_casa         text,                   -- NULL no mata-mata até os classificados serem definidos
    time_visitante    text,
    gols_casa         integer,                -- NULL = ainda não jogado (mesmo critério do results.csv)
    gols_visitante    integer,
    penaltis_vencedor text,                   -- mata-mata: vencedor nos pênaltis quando houve empate
    neutro            boolean,
    atualizado_em     timestamptz DEFAULT now()
);
"""


# --------------------------------------------------------------------------- #
# Dataclasses — contrato compartilhado com as features seguintes
# --------------------------------------------------------------------------- #
@dataclass
class Partida:
    match_id: str
    fase: str
    rodada: int | None
    grupo: str | None
    time_casa: str | None
    time_visitante: str | None
    gols_casa: int | None
    gols_visitante: int | None
    penaltis_vencedor: str | None
    neutro: bool

    @property
    def realizada(self) -> bool:
        return self.gols_casa is not None and self.gols_visitante is not None

    @property
    def vencedor(self) -> str | None:
        """Vencedor da partida (pênaltis decidem empates no mata-mata); None se pendente/empate."""
        if not self.realizada:
            return None
        if self.gols_casa > self.gols_visitante:
            return self.time_casa
        if self.gols_visitante > self.gols_casa:
            return self.time_visitante
        return self.penaltis_vencedor

    @property
    def perdedor(self) -> str | None:
        venc = self.vencedor
        if venc is None:
            return None
        return self.time_visitante if venc == self.time_casa else self.time_casa


@dataclass
class Grupo:
    letra: str
    times: list[str] = field(default_factory=list)
    partidas: list[Partida] = field(default_factory=list)


@dataclass
class EstadoTorneio:
    grupos: dict[str, Grupo]
    mata_mata: list[Partida]

    @property
    def partidas(self) -> list[Partida]:
        """Todas as 104 partidas, na ordem M1..M104."""
        de_grupo = [p for g in self.grupos.values() for p in g.partidas]
        return sorted(de_grupo + self.mata_mata, key=lambda p: int(p.match_id[1:]))

    @property
    def jogos_pendentes(self) -> list[Partida]:
        return [p for p in self.partidas if not p.realizada]

    @property
    def jogos_realizados(self) -> list[Partida]:
        return [p for p in self.partidas if p.realizada]

    @property
    def fase_grupos_completa(self) -> bool:
        return all(p.realizada for g in self.grupos.values() for p in g.partidas)


# --------------------------------------------------------------------------- #
# Seed (104 linhas) + inicialização protegida
# --------------------------------------------------------------------------- #
def _seed_dataframe() -> pd.DataFrame:
    """Monta as 104 linhas: M1..M72 de silver_copa2026 + M73..M104 do calendário."""
    grupos_df = pd.read_csv(ARQ_GRUPOS)
    grupo_de = dict(zip(grupos_df["nation"], grupos_df["group"]))

    jogos = pd.read_sql(
        "SELECT data, time_casa, time_visitante, neutro FROM silver_copa2026 ORDER BY data, id",
        get_engine(),
    )
    if len(jogos) != 72:
        raise RuntimeError(f"silver_copa2026 deveria ter 72 jogos, tem {len(jogos)}")

    jogos["grupo"] = jogos["time_casa"].map(grupo_de)
    grupo_visit = jogos["time_visitante"].map(grupo_de)
    if jogos["grupo"].isna().any() or not (jogos["grupo"] == grupo_visit).all():
        raise RuntimeError("seed inconsistente: jogo entre grupos diferentes ou seleção fora do CSV de grupos")

    # match_id global pela ordem (data, id); rodada = pares de jogos dentro do grupo.
    jogos["match_id"] = [f"M{i}" for i in range(1, 73)]
    jogos["fase"] = "Grupos"
    jogos["rodada"] = jogos.groupby("grupo").cumcount() // 2 + 1
    if jogos["rodada"].value_counts().to_dict() != {1: 24, 2: 24, 3: 24}:
        raise RuntimeError("seed inconsistente: cada rodada da fase de grupos deve ter 24 jogos")

    calendario = pd.read_csv(ARQ_CALENDARIO)
    mata = pd.DataFrame({
        "match_id": calendario["match_id"],
        "fase": calendario["round"],
        "rodada": pd.NA,
        "grupo": pd.NA,
        "data": calendario["match_date"],
        "time_casa": pd.NA,
        "time_visitante": pd.NA,
        "neutro": True,
    })

    df = pd.concat([jogos, mata], ignore_index=True)
    df["gols_casa"] = pd.NA
    df["gols_visitante"] = pd.NA
    df["penaltis_vencedor"] = pd.NA
    df["rodada"] = df["rodada"].astype("Int64")
    return df[COLUNAS]


def inicializar_estado(reset: bool = False) -> None:
    """Cria a tabela (idempotente) e roda o seed via COPY.

    Proteção: o seed (com DROP) só roda com ``reset=True``; sem a flag, só acontece
    se a tabela não existir ou estiver vazia — resultados registrados nunca se perdem.
    """
    conn = get_raw_connection()
    try:
        with conn.cursor() as cur:
            if reset:
                cur.execute(f"DROP TABLE IF EXISTS {TABELA};")
            cur.execute(DDL)
            cur.execute(f"SELECT count(*) FROM {TABELA};")
            existentes = cur.fetchone()[0]
            if existentes > 0:
                print(f"  resultados_copa já tem {existentes} jogos — seed pulado (use --reset para recriar).")
            else:
                df = _seed_dataframe()
                buffer = io.StringIO()
                df.to_csv(buffer, index=False, header=False, na_rep="")
                buffer.seek(0)
                cur.copy_expert(
                    f"COPY {TABELA} ({', '.join(COLUNAS)}) FROM STDIN WITH (FORMAT csv, NULL '')",
                    buffer,
                )
                print(f"  seed concluído: {len(df)} jogos em resultados_copa.")
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Estado
# --------------------------------------------------------------------------- #
def _opt(valor):
    """NaN/NaT/None do pandas -> None; preserva o valor caso contrário."""
    return None if pd.isna(valor) else valor


def _opt_int(valor) -> int | None:
    return None if pd.isna(valor) else int(valor)


def carregar_estado() -> EstadoTorneio:
    """Reconstrói o estado inteiro a partir de ``resultados_copa`` (ordem M1..M104)."""
    df = pd.read_sql(f"SELECT {', '.join(COLUNAS)} FROM {TABELA}", get_engine())
    if df.empty:
        raise RuntimeError("resultados_copa vazia — rode inicializar_estado() antes de carregar o estado.")
    df = df.sort_values("match_id", key=lambda s: s.str[1:].astype(int))

    grupos: dict[str, Grupo] = {}
    mata_mata: list[Partida] = []
    for linha in df.itertuples(index=False):
        partida = Partida(
            match_id=linha.match_id,
            fase=linha.fase,
            rodada=_opt_int(linha.rodada),
            grupo=_opt(linha.grupo),
            time_casa=_opt(linha.time_casa),
            time_visitante=_opt(linha.time_visitante),
            gols_casa=_opt_int(linha.gols_casa),
            gols_visitante=_opt_int(linha.gols_visitante),
            penaltis_vencedor=_opt(linha.penaltis_vencedor),
            neutro=bool(linha.neutro),
        )
        if partida.fase == "Grupos":
            grupo = grupos.setdefault(partida.grupo, Grupo(letra=partida.grupo))
            grupo.partidas.append(partida)
            for time in (partida.time_casa, partida.time_visitante):
                if time not in grupo.times:
                    grupo.times.append(time)
        else:
            mata_mata.append(partida)

    return EstadoTorneio(grupos=dict(sorted(grupos.items())), mata_mata=mata_mata)


def registrar_resultado(
    match_id: str,
    gols_casa: int,
    gols_visitante: int,
    penaltis_vencedor: str | None = None,
) -> Partida:
    """Registra (UPDATE) o placar real de um jogo e propaga o bracket.

    Valida: jogo existe e tem times definidos; gols inteiros >= 0; pênaltis só no
    mata-mata e só em caso de empate (onde são obrigatórios). Devolve a Partida
    atualizada após ``propagar_classificados``.
    """
    for nome, gols in (("gols_casa", gols_casa), ("gols_visitante", gols_visitante)):
        if isinstance(gols, bool) or not isinstance(gols, int) or gols < 0:
            raise ValueError(f"{nome} deve ser inteiro >= 0 (recebido: {gols!r})")

    conn = get_raw_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT fase, time_casa, time_visitante FROM {TABELA} WHERE match_id = %s", (match_id,))
            linha = cur.fetchone()
            if linha is None:
                raise ValueError(f"jogo {match_id!r} não existe em resultados_copa")
            fase, casa, visitante = linha
            if casa is None or visitante is None:
                raise ValueError(f"{match_id}: times ainda não definidos — aguarde a propagação dos classificados")

            empate = gols_casa == gols_visitante
            if penaltis_vencedor is not None:
                if fase == "Grupos":
                    raise ValueError("pênaltis não se aplicam à fase de grupos")
                if not empate:
                    raise ValueError("penaltis_vencedor só vale em caso de empate")
                if penaltis_vencedor not in (casa, visitante):
                    raise ValueError(f"penaltis_vencedor deve ser {casa!r} ou {visitante!r}")
            elif fase != "Grupos" and empate:
                raise ValueError(f"{match_id}: empate no mata-mata exige penaltis_vencedor")

            cur.execute(
                f"UPDATE {TABELA} SET gols_casa = %s, gols_visitante = %s, penaltis_vencedor = %s, "
                f"atualizado_em = now() WHERE match_id = %s",
                (gols_casa, gols_visitante, penaltis_vencedor, match_id),
            )
        conn.commit()
    finally:
        conn.close()

    estado = propagar_classificados(carregar_estado())
    return next(p for p in estado.partidas if p.match_id == match_id)


def classificacao_grupos(estado: EstadoTorneio) -> dict[str, pd.DataFrame]:
    """Tabela real de cada grupo (só jogos realizados). Critério: pontos → saldo → gols pró."""
    tabelas: dict[str, pd.DataFrame] = {}
    for letra, grupo in estado.grupos.items():
        stats = {t: {"jogos": 0, "v": 0, "e": 0, "d": 0, "gp": 0, "gc": 0, "pts": 0} for t in grupo.times}
        for p in grupo.partidas:
            if not p.realizada:
                continue
            for time, marcou, sofreu in ((p.time_casa, p.gols_casa, p.gols_visitante),
                                         (p.time_visitante, p.gols_visitante, p.gols_casa)):
                stats[time]["jogos"] += 1
                stats[time]["gp"] += marcou
                stats[time]["gc"] += sofreu
            if p.gols_casa > p.gols_visitante:
                stats[p.time_casa]["v"] += 1; stats[p.time_casa]["pts"] += 3; stats[p.time_visitante]["d"] += 1
            elif p.gols_casa < p.gols_visitante:
                stats[p.time_visitante]["v"] += 1; stats[p.time_visitante]["pts"] += 3; stats[p.time_casa]["d"] += 1
            else:
                stats[p.time_casa]["e"] += 1; stats[p.time_visitante]["e"] += 1
                stats[p.time_casa]["pts"] += 1; stats[p.time_visitante]["pts"] += 1

        ordem = sorted(
            grupo.times,
            key=lambda t: (-stats[t]["pts"], -(stats[t]["gp"] - stats[t]["gc"]), -stats[t]["gp"], t),
        )
        tabelas[letra] = pd.DataFrame([{
            "posicao": i + 1, "selecao": t, "jogos": stats[t]["jogos"],
            "vitorias": stats[t]["v"], "empates": stats[t]["e"], "derrotas": stats[t]["d"],
            "gols_pro": stats[t]["gp"], "gols_contra": stats[t]["gc"],
            "saldo_gols": stats[t]["gp"] - stats[t]["gc"], "pontos": stats[t]["pts"],
        } for i, t in enumerate(ordem)])
    return tabelas


def propagar_classificados(estado: EstadoTorneio) -> EstadoTorneio:
    """Preenche os times reais do mata-mata a partir dos resultados registrados.

    - Fase de grupos completa: resolve slots ``1X``/``2X`` e os 8 melhores terceiros
      (reuso de ``_resolver_terceiros``/``slots_terceiros`` de monte_carlo) em M73..M88.
    - A cada resultado de mata-mata: resolve ``W##``/``RU##`` nas fases seguintes,
      seguindo winner_advances_to/loser_advances_to do calendário.

    Idempotente; persiste em ``resultados_copa`` e devolve o estado atualizado.
    """
    calendario = pd.read_csv(ARQ_CALENDARIO).to_dict("records")
    slots: dict[str, str] = {}

    if estado.fase_grupos_completa:
        tabelas = classificacao_grupos(estado)
        stats: dict[str, dict] = {}
        ordem_por_grupo: dict[str, list[str]] = {}
        for letra, tabela in tabelas.items():
            ordem_por_grupo[letra] = tabela["selecao"].tolist()
            for linha in tabela.itertuples(index=False):
                stats[linha.selecao] = {"pts": linha.pontos, "gp": linha.gols_pro, "gc": linha.gols_contra}
            slots[f"1{letra}"] = ordem_por_grupo[letra][0]
            slots[f"2{letra}"] = ordem_por_grupo[letra][1]
        slots.update(_resolver_terceiros(ordem_por_grupo, stats, slots_terceiros(calendario)))

    partidas_mm = {p.match_id: p for p in estado.mata_mata}
    atualizacoes: list[tuple] = []
    for m in calendario:  # ordem topológica do calendário
        p = partidas_mm[m["match_id"]]
        casa = slots.get(m["home_slot"], p.time_casa)
        visitante = slots.get(m["away_slot"], p.time_visitante)
        if (casa, visitante) != (p.time_casa, p.time_visitante):
            p.time_casa, p.time_visitante = casa, visitante
            atualizacoes.append((casa, visitante, p.match_id))
        if p.realizada and p.time_casa and p.time_visitante:
            numero = p.match_id[1:]
            slots[f"W{numero}"] = p.vencedor
            if isinstance(m["loser_advances_to"], str) and m["loser_advances_to"]:
                slots[f"RU{numero}"] = p.perdedor

    if atualizacoes:
        conn = get_raw_connection()
        try:
            with conn.cursor() as cur:
                cur.executemany(
                    f"UPDATE {TABELA} SET time_casa = %s, time_visitante = %s, atualizado_em = now() "
                    f"WHERE match_id = %s",
                    atualizacoes,
                )
            conn.commit()
        finally:
            conn.close()
    return estado


# --------------------------------------------------------------------------- #
# CLI: inventário do torneio
# --------------------------------------------------------------------------- #
def main() -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
        sys.stdout.reconfigure(encoding="utf-8")  # consoles Windows cp1252 não exibem '✓'
    parser = argparse.ArgumentParser(description="Estado do torneio ao vivo (resultados_copa).")
    parser.add_argument("--reset", action="store_true",
                        help="DROP + seed da tabela (APAGA resultados já registrados!)")
    args = parser.parse_args()

    inicializar_estado(reset=args.reset)
    estado = carregar_estado()

    print("\n" + "=" * 64)
    print("ESTADO DO TORNEIO — Copa 2026")
    print("=" * 64)
    total = len(estado.partidas)
    print(f"  total de jogos: {total}  |  realizados: {len(estado.jogos_realizados)}"
          f"  |  pendentes: {len(estado.jogos_pendentes)}")
    print(f"  fase de grupos completa: {estado.fase_grupos_completa}")
    print(f"\n  {'fase':<8}{'rodada':>7}{'jogos':>7}{'realizados':>12}{'pendentes':>11}{'sem_times':>11}")
    for fase in FASES_ORDEM:
        if fase == "Grupos":
            partidas_fase = [p for g in estado.grupos.values() for p in g.partidas]
            chaves = sorted({p.rodada for p in partidas_fase})
        else:
            partidas_fase = [p for p in estado.mata_mata if p.fase == fase]
            chaves = [None]
        for rodada in chaves:
            ps = [p for p in partidas_fase if p.rodada == rodada]
            realizados = sum(p.realizada for p in ps)
            sem_times = sum(p.time_casa is None for p in ps)
            print(f"  {fase:<8}{('-' if rodada is None else rodada)!s:>7}{len(ps):>7}"
                  f"{realizados:>12}{len(ps) - realizados:>11}{sem_times:>11}")

    com_resultado = {letra: g for letra, g in estado.grupos.items()
                     if any(p.realizada for p in g.partidas)}
    if com_resultado:
        tabelas = classificacao_grupos(estado)
        print("\n  Classificação atual (grupos com resultados reais):")
        for letra in com_resultado:
            print(f"\n  Grupo {letra}")
            print("  " + tabelas[letra].to_string(index=False).replace("\n", "\n  "))
    else:
        print("\n  Nenhum resultado registrado ainda — classificações vazias.")
    print("=" * 64)
    print("\n✓ Estado do torneio disponível em resultados_copa.")


if __name__ == "__main__":
    main()
