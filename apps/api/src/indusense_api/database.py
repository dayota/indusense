"""Connexion PostgreSQL ; les migrations sont exécutées séparément."""

import os

from sqlalchemy import URL, create_engine


def database_url():
    return URL.create(
        "postgresql+psycopg",
        username=os.environ.get("DB_USER", "indusense_user"),
        password=os.environ.get("DB_PASSWORD", "dbpassword"),
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "5432")),
        database=os.environ.get("DB_NAME", "indusense_db"),
    )


def create_database_engine():
    return create_engine(
        database_url(), pool_pre_ping=True, connect_args={"connect_timeout": 3}
    )
