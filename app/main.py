import logging
import os
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import Product, Transaction, TransactionDetail
from .schemas import HealthOut, ProductOut, PurchaseIn, PurchaseResult
from .seed_items import seed_items

load_dotenv()

logger = logging.getLogger("pos.lv3")
logging.basicConfig(level=logging.INFO)

# Allow all origins during initial verification; override via CORS_ORIGINS env variable when hardening.
raw_cors_origins = os.getenv("CORS_ORIGINS")
ALLOWED_ORIGINS = (
    [origin.strip() for origin in raw_cors_origins.split(",") if origin.strip()]
    if raw_cors_origins
    else ["*"]
)
ALLOW_CREDENTIALS = "*" not in ALLOWED_ORIGINS

CLERK_CODE = os.getenv("CLERK_CODE", "9999999999")
STORE_CODE = os.getenv("STORE_CODE", "30")
POS_ID = os.getenv("POS_ID", "90")
TAX_PERCENT = Decimal(os.getenv("TAX_PERCENT", "10"))
TAX_RATE = TAX_PERCENT / Decimal("100")
TAX_CODE = os.getenv("TAX_CODE", "10")

app = FastAPI(title="Tech0 POS Lv3 API", version="1.4.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        seed_items(session)
    logger.info("Database ready with initial seed items")


def yen_round(value: Decimal | int | float) -> int:
    if isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, int):
        decimal_value = Decimal(value)
    else:
        decimal_value = Decimal(str(value))
    return int(decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@app.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(ok=True)


@app.get("/api/products/{code}", response_model=ProductOut)
def get_product(code: str, db: Session = Depends(get_db)) -> ProductOut:
    product = db.get(Product, code)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return ProductOut(code=product.code, name=product.name, unit_price=product.unit_price)


@app.post("/api/purchases", response_model=PurchaseResult, status_code=status.HTTP_201_CREATED)
def create_purchase(payload: PurchaseIn, db: Session = Depends(get_db)) -> PurchaseResult:
    aggregated: Dict[str, int] = {}
    ordered_codes: List[str] = []
    for line in payload.lines:
        if line.code not in aggregated:
            ordered_codes.append(line.code)
            aggregated[line.code] = line.qty
        else:
            aggregated[line.code] += line.qty

    if not aggregated:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No purchase lines supplied")

    stmt = select(Product).where(Product.code.in_(ordered_codes))
    products = {product.code: product for product in db.execute(stmt).scalars()}
    missing_codes = [code for code in ordered_codes if code not in products]
    if missing_codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PRODUCT_NOT_FOUND", "codes": missing_codes},
        )

    ttl_amt_ex_tax = 0
    details: List[TransactionDetail] = []
    for code in ordered_codes:
        product = products[code]
        qty = aggregated[code]
        line_total = product.unit_price * qty
        ttl_amt_ex_tax += line_total
        details.append(
            TransactionDetail(
                product_code=product.code,
                product_name=product.name,
                unit_price=product.unit_price,
                quantity=qty,
                line_total=line_total,
                tax_cd=TAX_CODE,
            )
        )

    tax_amt = yen_round(Decimal(ttl_amt_ex_tax) * TAX_RATE)
    total_amt = ttl_amt_ex_tax + tax_amt

    transaction = Transaction(
        ttl_amt_ex_tax=ttl_amt_ex_tax,
        tax_amt=tax_amt,
        total_amt=total_amt,
        clerk_cd=CLERK_CODE,
        store_cd=STORE_CODE,
        pos_id=POS_ID,
    )
    transaction.details.extend(details)
    db.add(transaction)
    db.commit()
    db.refresh(transaction)

    logger.info(
        "Recorded transaction %s lines=%d total_amt=%s",
        transaction.id,
        len(transaction.details),
        transaction.total_amt,
    )
    return PurchaseResult(total_amt=transaction.total_amt)
