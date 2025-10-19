import logging
import os
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import Product, Transaction, TransactionDetail
from .schemas import HealthOut, ProductOut, PurchaseIn, PurchaseResult
from .seed_items import seed_items

# ===== Stripe =====
import stripe

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

# Stripe keys
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")  # sk_test_...
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
else:
    logger.warning("STRIPE_SECRET_KEY is not set. /api/checkout/session will fail until it's provided.")

WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")  # whsec_...

app = FastAPI(title="Tech0 POS Lv3 API", version="1.5.0")
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


# ========= 共通ロジック：取引登録（DBコミット込み） =========
def register_transaction_with_codes(db: Session, code_qty_pairs: Dict[str, int]) -> PurchaseResult:
    """
    code→数量 の辞書を受け取り、商品確認・金額計算・Transaction/Details を作成してコミットする。
    返り値は PurchaseResult（total_amt）。
    """
    # 入力チェック
    aggregated: Dict[str, int] = {}
    ordered_codes: List[str] = []

    for code, qty in code_qty_pairs.items():
        if code not in aggregated:
            ordered_codes.append(code)
            aggregated[code] = int(qty)
        else:
            aggregated[code] += int(qty)

    if not aggregated:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No purchase lines supplied")

    # 商品取得 & 存在チェック
    stmt = select(Product).where(Product.code.in_(ordered_codes))
    products = {product.code: product for product in db.execute(stmt).scalars()}
    missing_codes = [code for code in ordered_codes if code not in products]
    if missing_codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PRODUCT_NOT_FOUND", "codes": missing_codes},
        )

    # 金額計算 & 明細生成
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

    # 取引保存
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


# ==================== 既存エンドポイント ====================
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
    # PurchaseIn: lines: List[{code:str, qty:int}]
    code_qty: Dict[str, int] = {}
    for line in payload.lines:
        code_qty[line.code] = code_qty.get(line.code, 0) + int(line.qty)

    return register_transaction_with_codes(db, code_qty)


# ==================== Stripe: Checkout セッション作成 ====================
class CheckoutItem(BaseModel):
    code: str
    qty: int


class CreateCheckoutReq(BaseModel):
    """
    POSのカートから {code, qty} の配列と、成功/キャンセルURLのベースになる origin を受け取る。
    価格は **DBから引く**（フロントから渡さない）ことで改ざんを防止する。
    """
    items: List[CheckoutItem]
    origin: str  # e.g. https://your-frontend.example


@app.post("/api/checkout/session")
def create_checkout_session(body: CreateCheckoutReq, db: Session = Depends(get_db)):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe secret key not configured")

    # 集計
    code_qty: Dict[str, int] = {}
    order_codes: List[str] = []
    for it in body.items:
        if it.code not in code_qty:
            order_codes.append(it.code)
            code_qty[it.code] = int(it.qty)
        else:
            code_qty[it.code] += int(it.qty)

    if not code_qty:
        raise HTTPException(status_code=400, detail="No items")

    # DBから商品取得（価格はDBを信頼ソースにする）
    stmt = select(Product).where(Product.code.in_(order_codes))
    products = {p.code: p for p in db.execute(stmt).scalars()}
    missing = [c for c in order_codes if c not in products]
    if missing:
        raise HTTPException(status_code=400, detail={"code": "PRODUCT_NOT_FOUND", "codes": missing})

    # Stripe line_items 構築
    line_items = []
    for code in order_codes:
        p = products[code]
        qty = code_qty[code]
        if qty <= 0:
            continue
        line_items.append(
            {
                "quantity": qty,
                "price_data": {
                    "currency": "jpy",
                    "unit_amount": int(p.unit_price),  # 1円単位
                    "product_data": {"name": f"{p.name} ({p.code})"},
                },
            }
        )

    if not line_items:
        raise HTTPException(status_code=400, detail="No valid line items")

    # Webhookで復元できるよう POSの明細を metadata に詰める
    meta_payload = ";".join([f"{c}:{code_qty[c]}" for c in order_codes])

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            ui_mode="hosted",
            line_items=line_items,
            success_url=f"{body.origin}/success?sid={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{body.origin}/cancel",
            metadata={"pos_lines": meta_payload},
            automatic_tax={"enabled": True},
        )
        return {"id": session.id, "url": session.url}
    except Exception as e:
        logger.exception("Stripe checkout session creation failed")
        raise HTTPException(status_code=400, detail=str(e))


# ==================== Stripe: Webhook ====================
@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    if not WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Stripe webhook secret not configured")

    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload=payload, sig_header=sig, secret=WEBHOOK_SECRET)
    except Exception as e:
        logger.warning("Stripe webhook signature verification failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))

    if event["type"] == "checkout.session.completed":
        session_obj = event["data"]["object"]
        meta = (session_obj.get("metadata") or {}).get("pos_lines", "")
        # "code:qty;code:qty;..." を辞書へ
        code_qty: Dict[str, int] = {}
        for pair in filter(None, meta.split(";")):
            try:
                code, qty_s = pair.split(":")
                code_qty[code] = code_qty.get(code, 0) + int(qty_s)
            except Exception:
                continue

        if code_qty:
            # DB登録（このトランザクションは「決済成功」のみ保存）
            with Session(engine) as db:
                try:
                    _ = register_transaction_with_codes(db, code_qty)
                except HTTPException as he:
                    logger.error("Failed to register transaction from webhook: %s", he.detail)
                except Exception as e:
                    logger.exception("Unexpected error while registering transaction from webhook: %s", e)

    return {"ok": True}
