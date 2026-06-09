"""Conexão com o Postgres do Supabase — módulo compartilhado por todas as specs do pipeline.

Lê a connection string de ``DATABASE_URL`` (via .env) e expõe:
- ``get_engine()``: engine SQLAlchemy (consultas, pandas).
- ``get_raw_connection()``: conexão psycopg2 crua (necessária para ``COPY``).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL não definida. Copie .env.example para .env e preencha a "
            "connection string do Supabase (pooler na porta 6543)."
        )
    return url


def get_engine():
    """Engine SQLAlchemy para uso geral (consultas e pandas)."""
    from sqlalchemy import create_engine

    return create_engine(_database_url())


def get_raw_connection():
    """Conexão psycopg2 crua — usada para carga em massa via COPY."""
    import psycopg2

    return psycopg2.connect(_database_url())
