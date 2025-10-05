import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DB_URL")

connect_args: dict[str, Any] = {}

if DATABASE_URL:
    url = DATABASE_URL
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
else:
    db_host = os.getenv("DB_HOST")
    if db_host:
        db_port = os.getenv("DB_PORT", "3306")
        db_user = os.getenv("DB_USER", "root")
        db_password = os.getenv("DB_PASSWORD", "")
        db_name = os.getenv("DB_NAME", "posdb")
        url = f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}?charset=utf8mb4"
        db_ssl_ca = os.getenv("DB_SSL_CA")
        if db_ssl_ca:
            connect_args["ssl"] = {"ca": db_ssl_ca}
    else:
        sqlite_path = os.getenv("SQLITE_PATH", "pos.sqlite3")
        absolute_sqlite_path = Path(sqlite_path).expanduser().resolve()
        absolute_sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite+pysqlite:///{absolute_sqlite_path}"
        connect_args["check_same_thread"] = False

engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
