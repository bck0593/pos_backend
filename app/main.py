# app/main.py
import os
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, relationship
from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, DateTime, func
from decimal import Decimal
from typing import List

from .database import Base, engine, get_db

# ─────────────────────────────────────────────────────────────
# モデル（DBテーブル定義）
# ─────────────────────────────────────────────────────────────
class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)  # 学習用にNumeric、計算はfloat寄せ

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    # PDF Lv1 準拠の列（既定値付き）
    datetime = Column(DateTime, nullable=False, server_default=func.now())
    emp_cd   = Column(String(10), nullable=False, server_default="9999999999")
    store_cd = Column(String(5),  nullable=False, server_default="30")
    pos_no   = Column(String(3),  nullable=False, server_default="90")

    total_amount = Column(Numeric(10, 2), nullable=False)
    items = relationship(
        "TransactionItem",
        back_populates="transaction",
        cascade="all, delete-orphan"
    )

class TransactionItem(Base):
    __tablename__ = "transaction_items"
    id = Column(Integer, primary_key=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    product_code = Column(String(50), nullable=False)
    product_name = Column(String(255), nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    quantity = Column(Integer, nullable=False)
    transaction = relationship("Transaction", back_populates="items")

# ─────────────────────────────────────────────────────────────
# スキーマ（Pydantic）
# ─────────────────────────────────────────────────────────────
from pydantic import BaseModel, Field

class ProductOut(BaseModel):
    code: str
    name: str
    unit_price: float

class PurchaseItem(BaseModel):
    product_code: str = Field(min_length=1)
    quantity: int = Field(ge=1)

class PurchaseRequest(BaseModel):
    # PDFに合わせた追加パラメータ（未指定時は既定値を使用）
    emp_cd: str | None = None
    store_cd: str | None = None
    pos_no: str | None = None
    items: List[PurchaseItem]

class PurchaseResponse(BaseModel):
    success: bool
    transaction_id: int
    total_amount: float

# ─────────────────────────────────────────────────────────────
# アプリ本体
# ─────────────────────────────────────────────────────────────
app = FastAPI(title="POS Lv1 API", version="1.0.0")

# 環境変数から許可オリジンを取得（未設定なら dev 用に localhost:3000）
# 許可オリジン（カンマ区切り）と、任意の正規表現を環境変数から読む
allowed_origins_env = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")
allowed_origins = [o.strip() for o in allowed_origins_env.split(",") if o.strip()]
allowed_origin_regex = os.getenv("CORS_ALLOW_ORIGIN_REGEX")  # 例: ^https://.*\.azurewebsites\.net$

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,          # 具体URLを列挙
    allow_origin_regex=allowed_origin_regex,# 任意：azurewebsites.net 配下包括許可
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    # テーブル作成
    Base.metadata.create_all(bind=engine)
    # 初回シード
    with next(get_db()) as db:
        if db.query(Product).count() == 0:
            db.add_all([
                Product(code="4900001", name="Mineral Water 500ml", unit_price=Decimal("100.00")),
                Product(code="4900002", name="Potato Chips",        unit_price=Decimal("150.00")),
                Product(code="4900003", name="Chocolate Bar",       unit_price=Decimal("120.00")),
            ])
            db.commit()

@app.get("/")
def root():
    # 開発しやすいよう /docs へ誘導
    return RedirectResponse("/docs")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/products", response_model=ProductOut | None)
def get_product(code: str, db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.code == code).first()
    if not p:
        return None
    return {"code": p.code, "name": p.name, "unit_price": float(p.unit_price)}

# ─────────────────────────────────────────────────────────────
# 購入API（PDF Lv1 準拠・堅牢版）
# ─────────────────────────────────────────────────────────────
@app.post("/purchase", response_model=PurchaseResponse)
def purchase(req: PurchaseRequest, db: Session = Depends(get_db)):
    # 0) バリデーション
    if not req.items:
        raise HTTPException(status_code=400, detail="items must not be empty")

    try:
        # 1) 取引ヘッダ 仮登録（PDFの既定値を適用。指定があれば上書き）
        tx = Transaction(
            total_amount=Decimal("0.00"),
            emp_cd=(req.emp_cd or "9999999999"),
            store_cd=(req.store_cd or "30"),
            pos_no=(req.pos_no or "90"),
        )
        db.add(tx)
        db.flush()  # tx.id を確保

        # 合計は float で計算して安定化（Numericでも受け入れられる）
        total = 0.0

        # 2) 明細登録＋合計計算
        for it in req.items:
            if it.quantity < 1:
                raise HTTPException(status_code=400, detail="quantity must be >= 1")

            p = db.query(Product).filter(Product.code == it.product_code).first()
            if not p:
                raise HTTPException(status_code=400, detail=f"Unknown product_code: {it.product_code}")

            unit_price = float(p.unit_price)
            line_total = unit_price * it.quantity
            total += line_total

            db.add(TransactionItem(
                transaction_id=tx.id,
                product_code=p.code,
                product_name=p.name,
                unit_price=unit_price,
                quantity=it.quantity
            ))

        # 3) 合計をヘッダに反映
        tx.total_amount = float(total)

        # 4) コミット
        db.commit()
        db.refresh(tx)

        # 5) 成功レスポンス（PDFの「成否(True/False), 合計金額」に合わせ success を追加）
        return {"success": True, "transaction_id": tx.id, "total_amount": float(tx.total_amount)}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        # 開発中は内容を返す（本番はログのみ推奨）
        raise HTTPException(status_code=500, detail=f"purchase failed: {e}")
