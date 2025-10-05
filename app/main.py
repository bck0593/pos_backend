import os
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import Product, Trade, TradeDetail
from .schemas import ProductEnvelope, PurchaseRequest, PurchaseResponse

TAX_CODE = "10"
TAX_DIVISOR = Decimal("1.10")

app = FastAPI(title="POS Lv2 API", version="1.0.0")

allowed_origins_env = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")
allowed_origins = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        has_products = session.scalar(select(Product).limit(1)) is not None
        if not has_products:
            session.add_all(
                [
                    Product(code="4900000000001", name="サンプルドリンク", price=150),
                    Product(code="4900000000002", name="サンプルスナック", price=210),
                    Product(code="4900000000003", name="サンプルキャンディ", price=120),
                    Product(code="4969757165713",name="おえかきちょう",price=110),
                ]
            )
            session.commit()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/products", response_model=ProductEnvelope)
def get_product(code: str, db: Session = Depends(get_db)) -> ProductEnvelope:
    product = db.scalar(select(Product).where(Product.code == code))
    if not product:
        return {"product": None}
    return {
        "product": {
            "code": product.code,
            "name": product.name,
            "price": product.price,
        }
    }


@app.post("/purchase", response_model=PurchaseResponse)
def purchase(req: PurchaseRequest, db: Session = Depends(get_db)) -> PurchaseResponse:
    if not req.items:
        raise HTTPException(status_code=400, detail="items must not be empty")

    codes = {item.product_code for item in req.items}
    products: Dict[str, Product] = {
        product.code: product
        for product in db.scalars(select(Product).where(Product.code.in_(codes)))
    }

    line_entries: List[tuple[Product, int]] = []
    total_in_tax = 0
    for item in req.items:
        product = products.get(item.product_code)
        if product is None:
            raise HTTPException(status_code=400, detail=f"Unknown product_code: {item.product_code}")
        if item.quantity < 1:
            raise HTTPException(status_code=400, detail="quantity must be >= 1")
        line_total = product.price * item.quantity
        total_in_tax += line_total
        line_entries.append((product, item.quantity))

    if total_in_tax <= 0:
        raise HTTPException(status_code=400, detail="total amount must be positive")

    total_ex_tax = int(
        (Decimal(total_in_tax) / TAX_DIVISOR).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )

    trade = Trade(
        emp_cd=req.emp_cd,
        store_cd=req.store_cd,
        pos_no=req.pos_no,
        total_amt=total_in_tax,
        ttl_amt_ex_tax=total_ex_tax,
    )
    db.add(trade)
    db.flush()

    detail_id = 1
    for product, quantity in line_entries:
        for _ in range(quantity):
            db.add(
                TradeDetail(
                    trd_id=trade.trd_id,
                    dtl_id=detail_id,
                    prd_id=product.prd_id,
                    prd_code=product.code,
                    prd_name=product.name,
                    prd_price=product.price,
                    tax_cd=TAX_CODE,
                )
            )
            detail_id += 1

    db.commit()
    db.refresh(trade)

    return PurchaseResponse(
        success=True,
        transaction_id=int(trade.trd_id),
        total_amount=trade.total_amt,
        total_amount_ex_tax=trade.ttl_amt_ex_tax,
        tax_cd=TAX_CODE,
        total_in_tax=trade.total_amt,
        total_ex_tax=trade.ttl_amt_ex_tax,
    )
