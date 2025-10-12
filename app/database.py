import os
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from urllib.parse import quote_plus

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE_PATH = BACKEND_ROOT / "data" / "posapp.db"


def _first_env(keys: list[str]) -> str | None:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return None


def _get_raw_database_url() -> str:
    explicit = _first_env(
        [
            "DATABASE_URL",
            "APPSETTING_DATABASE_URL",  # Azure App Service prefix
            "SQLALCHEMY_DATABASE_URL",
        ]
    )
    if explicit:
        return explicit

    for key, value in os.environ.items():
        if key.startswith(
            (
                "SQLAZURECONNSTR_",
                "SQLCONNSTR_",
                "MYSQLCONNSTR_",
                "POSTGRESQLCONNSTR_",
                "CUSTOMCONNSTR_",
            )
        ):
            return value

    DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+pysqlite:///{DEFAULT_SQLITE_PATH}"


def _convert_azure_adonet_url(raw: str) -> str | None:
    """
    Convert Azure-style ADO.NET connection strings into SQLAlchemy URLs.
    Only handles the most common SQL Server and MySQL shapes.
    """
    parts: dict[str, str] = {}
    for fragment in raw.strip().split(";"):
        if not fragment:
            continue
        if "=" not in fragment:
            continue
        key, value = fragment.split("=", 1)
        parts[key.strip().lower()] = value.strip()

    if not parts:
        return None

    if "driver" in parts and "server" in parts and "database" in parts:
        # Likely SQL Server
        username = parts.get("uid") or parts.get("user id") or ""
        password = parts.get("pwd") or parts.get("password") or ""
        server = parts["server"]
        database = parts["database"]
        driver = parts["driver"].strip("{}")
        auth = ""
        if username:
            auth = f"{quote_plus(username)}:{quote_plus(password)}@"
        query = f"driver={quote_plus(driver)}"
        if parts.get("encrypt", "").lower() in {"true", "yes"}:
            query += "&Encrypt=yes"
        return f"mssql+pyodbc://{auth}{server}/{database}?{query}"

    if "server" in parts and "database" in parts and "uid" in parts:
        # MySQL style
        username = parts.get("uid") or ""
        password = parts.get("pwd") or ""
        server = parts["server"].removeprefix("tcp:")
        if "," in server:
            server = server.split(",", 1)[0]
        database = parts["database"]
        auth = f"{quote_plus(username)}:{quote_plus(password)}@"
        return f"mysql+pymysql://{auth}{server}/{database}"

    return None


def _resolve_database_url() -> tuple[URL, dict[str, object], dict[str, object]]:
    raw = _get_raw_database_url()
    if "Driver=" in raw or "driver=" in raw:
        converted = _convert_azure_adonet_url(raw)
        if converted:
            raw = converted
    url = make_url(raw)

    connect_args: dict[str, object] = {}
    engine_kwargs: dict[str, object] = {"pool_pre_ping": True}

    if url.drivername.startswith("sqlite"):
        db_value = url.database or str(DEFAULT_SQLITE_PATH)
        db_path = Path(db_value)
        if not db_path.is_absolute():
            db_path = (BACKEND_ROOT / db_path).resolve()
        else:
            db_path = db_path.expanduser()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        url = url.set(database=str(db_path))
        connect_args["check_same_thread"] = False
        engine_kwargs.pop("pool_pre_ping", None)

    if url.drivername.startswith("mysql"):
        query = dict(url.query)
        if "charset" not in query:
            query["charset"] = "utf8mb4"
        url = url.set(query=query)
        engine_kwargs["pool_recycle"] = int(os.getenv("SQLALCHEMY_POOL_RECYCLE", "1800"))

    return url, connect_args, engine_kwargs


resolved_url, connect_args, engine_kwargs = _resolve_database_url()
engine = create_engine(
    resolved_url,
    echo=False,
    future=True,
    connect_args=connect_args,
    **engine_kwargs,
)

if resolved_url.drivername.startswith("sqlite"):

    @event.listens_for(engine, "connect", insert=True)
    def set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
