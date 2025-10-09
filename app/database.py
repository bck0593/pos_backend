import os
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+pysqlite:///./posapp.db")
url = make_url(DATABASE_URL)

connect_args: dict[str, object] = {}
pool_kwargs: dict[str, object] = {"pool_pre_ping": True}
if url.drivername.startswith("sqlite"):
    database_path = Path(url.database or "./posapp.db").expanduser().resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connect_args["check_same_thread"] = False
    url = url.set(database=str(database_path))
elif url.drivername.startswith("mysql"):
    query = dict(url.query)
    if "charset" not in query:
        query["charset"] = "utf8mb4"
    url = url.set(query=query)
    pool_kwargs["pool_recycle"] = int(os.getenv("SQLALCHEMY_POOL_RECYCLE", "1800"))

engine = create_engine(url, echo=False, future=True, connect_args=connect_args, **pool_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
