import hashlib
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from hmac import compare_digest
from typing import Dict, Iterable

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import Item, Sale, SaleLine
from .schemas import (
    HealthOut,
    ItemListOut,
    ItemOut,
    LoginRequest,
    MessageOut,
    SaleIn,
    SaleLineOut,
    SaleOut,
    SaleSummaryOut,
    TokenOut,
)
from .seed_items import seed_items

UTC = timezone.utc

load_dotenv()

logger = logging.getLogger("pos.lv3")
logging.basicConfig(level=logging.INFO)

ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
if not ALLOWED_ORIGINS:
    raise RuntimeError("CORS_ORIGINS must be configured with at least one origin")

JWT_SECRET = os.getenv("JWT_SECRET", "change-me")
if JWT_SECRET in {"", "change-me"}:
    logger.warning("JWT_SECRET is using a development default. Set a strong secret in production.")

JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRES_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRES_MINUTES", "10"))
REFRESH_TOKEN_EXPIRES_MINUTES = int(os.getenv("REFRESH_TOKEN_EXPIRES_MINUTES", "4320"))
REFRESH_COOKIE_NAME = os.getenv("REFRESH_COOKIE_NAME", "pos_refresh_token")
REFRESH_COOKIE_PATH = os.getenv("REFRESH_COOKIE_PATH", "/")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() in {"1", "true", "yes"}
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax").lower()
IDENTIFIER_HASH_SECRET = os.getenv("IDENTIFIER_HASH_SECRET", JWT_SECRET)
DEFAULT_TOKEN_SCOPES = tuple(
    scope.strip()
    for scope in os.getenv("DEFAULT_TOKEN_SCOPES", "items:read sales:read sales:write").split()
    if scope.strip()
)
if not DEFAULT_TOKEN_SCOPES:
    DEFAULT_TOKEN_SCOPES = ("items:read", "sales:read", "sales:write")

DEMO_USERNAME = os.getenv("DEMO_USERNAME", "demo")
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "demo123")
DEMO_PASSWORD_HASH = os.getenv("DEMO_PASSWORD_HASH")
ALLOW_CUSTOM_ITEMS = os.getenv("ALLOW_CUSTOM_ITEMS", "false").lower() in {"1", "true", "yes"}

ACCESS_TOKEN_EXPIRES_SECONDS = ACCESS_TOKEN_EXPIRES_MINUTES * 60
REFRESH_TOKEN_EXPIRES_SECONDS = REFRESH_TOKEN_EXPIRES_MINUTES * 60

app = FastAPI(title="POS Lv3 API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

security = HTTPBearer(auto_error=False)


class SlidingWindowRateLimiter:
    def __init__(self, *, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: Dict[str, list[float]] = {}

    def _prune(self, key: str, now: float) -> None:
        hits = self._hits.setdefault(key, [])
        self._hits[key] = [stamp for stamp in hits if now - stamp <= self.window_seconds]

    def check(self, key: str) -> None:
        now = time.monotonic()
        self._prune(key, now)
        hits = self._hits.setdefault(key, [])
        if len(hits) >= self.limit:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
        hits.append(now)


auth_rate_limiter = SlidingWindowRateLimiter(limit=10, window_seconds=60)
sale_rate_limiter = SlidingWindowRateLimiter(limit=60, window_seconds=60)


def mask_identifier(value: str | None) -> str | None:
    if not value:
        return None
    digest = hashlib.sha256(f"{IDENTIFIER_HASH_SECRET}:{value}".encode("utf-8")).hexdigest()
    return digest


def _encode_token(payload: dict, expires_delta: timedelta) -> str:
    complete_payload = {
        **payload,
        "exp": datetime.now(tz=UTC) + expires_delta,
        "iat": datetime.now(tz=UTC),
        "iss": "pos-lv3-api",
    }
    return jwt.encode(complete_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_access_token(subject: str, scopes: Iterable[str]) -> str:
    return _encode_token(
        {
            "sub": subject,
            "type": "access",
            "scope": " ".join(scopes),
        },
        timedelta(minutes=ACCESS_TOKEN_EXPIRES_MINUTES),
    )


def create_refresh_token(subject: str, scopes: Iterable[str]) -> str:
    return _encode_token(
        {
            "sub": subject,
            "type": "refresh",
            "scope": " ".join(scopes),
        },
        timedelta(minutes=REFRESH_TOKEN_EXPIRES_MINUTES),
    )


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    token_type = payload.get("type")
    if token_type != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    return payload


def get_access_payload(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")
    return decode_token(credentials.credentials, expected_type="access")


def require_scopes(*scopes: str):
    scope_set = set(scopes)

    def dependency(payload: dict = Depends(get_access_payload)) -> dict:
        token_scopes = set(payload.get("scope", "").split())
        if scope_set and not scope_set.issubset(token_scopes):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient scope")
        return payload

    return dependency


def verify_credentials(username: str, password: str) -> str:
    expected_user = DEMO_USERNAME
    if DEMO_PASSWORD_HASH:
        provided_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        if not (compare_digest(username, expected_user) and compare_digest(provided_hash, DEMO_PASSWORD_HASH)):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    else:
        if not (compare_digest(username, expected_user) and compare_digest(password, DEMO_PASSWORD)):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return username


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        seed_items(session)
        logger.info("Database ready with initial seed items")


@app.get("/healthz", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(status="ok")


@app.post("/auth/login", response_model=TokenOut)
def login(login_request: LoginRequest, request: Request) -> JSONResponse:
    client_host = request.client.host if request.client else "unknown"
    auth_rate_limiter.check(client_host)
    subject = verify_credentials(login_request.username, login_request.password)
    scopes = DEFAULT_TOKEN_SCOPES
    access_token = create_access_token(subject, scopes)
    refresh_token = create_refresh_token(subject, scopes)
    response = JSONResponse(
        TokenOut(access_token=access_token, expires_in=ACCESS_TOKEN_EXPIRES_SECONDS).dict()
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=REFRESH_TOKEN_EXPIRES_SECONDS,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path=REFRESH_COOKIE_PATH,
    )
    return response


@app.post("/auth/refresh", response_model=TokenOut)
def refresh_token(request: Request) -> JSONResponse:
    client_host = request.client.host if request.client else "unknown"
    auth_rate_limiter.check(client_host)
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")
    payload = decode_token(raw_token, expected_type="refresh")
    subject = payload.get("sub")
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    scopes = tuple(scope for scope in payload.get("scope", "").split() if scope) or DEFAULT_TOKEN_SCOPES
    access_token = create_access_token(subject, scopes)
    new_refresh_token = create_refresh_token(subject, scopes)
    response = JSONResponse(
        TokenOut(access_token=access_token, expires_in=ACCESS_TOKEN_EXPIRES_SECONDS).dict()
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        value=new_refresh_token,
        max_age=REFRESH_TOKEN_EXPIRES_SECONDS,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path=REFRESH_COOKIE_PATH,
    )
    return response


@app.post("/auth/logout", response_model=MessageOut)
def logout() -> JSONResponse:
    response = JSONResponse(MessageOut(message="logged out").dict())
    response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)
    return response


@app.get("/items/{code}", response_model=ItemOut)
def get_item(
    code: str,
    db: Session = Depends(get_db),
    _: dict = Depends(require_scopes("items:read")),
) -> ItemOut:
    if not code.isdigit() or len(code) != 13:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid item code")
    item = db.get(Item, code)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return ItemOut(code=item.code, name=item.name, unit_price=item.unit_price)


@app.get("/items", response_model=ItemListOut)
def search_items(
    q: str | None = None,
    db: Session = Depends(get_db),
    _: dict = Depends(require_scopes("items:read")),
) -> ItemListOut:
    stmt = select(Item).limit(50)
    if q:
        like_pattern = f"%{q}%"
        stmt = stmt.where(or_(Item.code.ilike(like_pattern), Item.name.ilike(like_pattern)))
    items = db.scalars(stmt).all()
    return ItemListOut(items=[ItemOut(code=item.code, name=item.name, unit_price=item.unit_price) for item in items])


@app.post("/sales", response_model=SaleOut)
def create_sale(
    sale_in: SaleIn,
    request: Request,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_scopes("sales:write")),
) -> SaleOut:
    client_host = request.client.host if request.client else "unknown"
    sale_rate_limiter.check(client_host)

    tax_out_calc = 0
    sale_lines: list[SaleLine] = []
    actor = payload.get("sub", "unknown")
    sale: Sale | None = None

    with db.begin():
        codes = {line.code for line in sale_in.lines}
        items_by_code = {
            item.code: item for item in db.scalars(select(Item).where(Item.code.in_(codes)))
        }

        for line in sale_in.lines:
            item = items_by_code.get(line.code)
            if item is None:
                if not ALLOW_CUSTOM_ITEMS:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Code {line.code} is not registered",
                    )
            else:
                if item.name != line.name or item.unit_price != line.unit_price:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Line for {line.code} does not match master data",
                    )
            line_total = line.unit_price * line.qty
            tax_out_calc += line_total
            sale_lines.append(
                SaleLine(
                    code=line.code,
                    name=line.name,
                    unit_price=line.unit_price,
                    qty=line.qty,
                    line_total=line_total,
                )
            )

        tax_calc = round(tax_out_calc * 0.1)
        tax_in_calc = tax_out_calc + tax_calc

        if (
            sale_in.tax_out != tax_out_calc
            or sale_in.tax != tax_calc
            or sale_in.tax_in != tax_in_calc
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Totals do not match server calculation",
            )

        sale = Sale(
            tax_out=tax_out_calc,
            tax=tax_calc,
            tax_in=tax_in_calc,
            device_id=mask_identifier(sale_in.device_id),
            cashier_id=mask_identifier(sale_in.cashier_id),
            created_by=actor,
        )
        sale.lines.extend(sale_lines)
        db.add(sale)

    assert sale is not None
    db.refresh(sale)

    logger.info(
        "Recorded sale %s | actor=%s | lines=%d | tax_in=%s",
        sale.id,
        actor,
        len(sale.lines),
        sale.tax_in,
    )

    return SaleOut(
        id=sale.id,
        created_at=sale.created_at,
        tax_out=sale.tax_out,
        tax=sale.tax,
        tax_in=sale.tax_in,
        device_id=None,
        cashier_id=None,
        created_by=actor,
        lines=[
            SaleLineOut(
                code=line.code,
                name=line.name,
                unit_price=line.unit_price,
                qty=line.qty,
                line_total=line.line_total,
            )
            for line in sale.lines
        ],
    )


@app.get("/sales/{sale_id}", response_model=SaleOut)
def get_sale(
    sale_id: str,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_scopes("sales:read")),
) -> SaleOut:
    sale = db.get(Sale, sale_id)
    if not sale or sale.created_by != payload.get("sub"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")
    return SaleOut(
        id=sale.id,
        created_at=sale.created_at,
        tax_out=sale.tax_out,
        tax=sale.tax,
        tax_in=sale.tax_in,
        device_id=None,
        cashier_id=None,
        created_by=sale.created_by,
        lines=[
            SaleLineOut(
                code=line.code,
                name=line.name,
                unit_price=line.unit_price,
                qty=line.qty,
                line_total=line.line_total,
            )
            for line in sale.lines
        ],
    )


@app.get("/sales", response_model=SaleSummaryOut)
def summarize_sales(
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_scopes("sales:read")),
) -> SaleSummaryOut:
    stmt = select(
        func.count(Sale.id),
        func.coalesce(func.sum(Sale.tax_out), 0),
        func.coalesce(func.sum(Sale.tax), 0),
        func.coalesce(func.sum(Sale.tax_in), 0),
    ).where(Sale.created_by == payload.get("sub"))
    if date_from:
        try:
            start = datetime.fromisoformat(date_from)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date_from") from exc
        stmt = stmt.where(Sale.created_at >= start)
    if date_to:
        try:
            end = datetime.fromisoformat(date_to)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date_to") from exc
        stmt = stmt.where(Sale.created_at <= end)
    count, tax_out_sum, tax_sum, tax_in_sum = db.execute(stmt).one()
    return SaleSummaryOut(count=int(count), tax_out=int(tax_out_sum), tax=int(tax_sum), tax_in=int(tax_in_sum))


@app.delete("/sales/{sale_id}", response_model=MessageOut)
def delete_sale(
    sale_id: str,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_scopes("sales:write")),
) -> MessageOut:
    sale = db.get(Sale, sale_id)
    if not sale or sale.created_by != payload.get("sub"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")
    db.delete(sale)
    db.commit()
    return MessageOut(message="Sale deleted")
