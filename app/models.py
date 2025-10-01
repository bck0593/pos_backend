from sqlalchemy import (
    Column, Integer, String, ForeignKey, CheckConstraint, DateTime, func, UniqueConstraint
)
from sqlalchemy.orm import relationship
from .database import Base

# 商品マスタ
class Product(Base):
    __tablename__ = "products"
    prd_id = Column(Integer, primary_key=True, autoincrement=True)            # PRD_ID
    code = Column(String(13), nullable=False, unique=True, index=True)        # CODE (char 13)
    name = Column(String(50), nullable=False)                                  # NAME (varchar 50)
    price = Column(Integer, nullable=False)                                    # PRICE (int)
    __table_args__ = (
        CheckConstraint("length(code) = 13", name="ck_products_code_len_13"),
    )

# 取引ヘッダ
class Transaction(Base):
    __tablename__ = "transactions"
    trd_id = Column(Integer, primary_key=True, autoincrement=True)             # TRD_ID
    datetime = Column(DateTime, nullable=False, server_default=func.now())     # DATETIME
    emp_cd = Column(String(10), nullable=False, server_default="9999999999")   # EMP_CD
    store_cd = Column(String(5), nullable=False, server_default="30")          # STORE_CD
    pos_no = Column(String(3), nullable=False, server_default="90")            # POS_NO
    total_amt = Column(Integer, nullable=False, default=0)                     # TOTAL_AMT (int)

    items = relationship("TransactionItem", back_populates="transaction", cascade="all, delete-orphan")

# 取引明細
class TransactionItem(Base):
    __tablename__ = "transaction_items"
    dtl_id = Column(Integer, primary_key=True, autoincrement=True)             # DTL_ID
    trd_id = Column(Integer, ForeignKey("transactions.trd_id"), nullable=False)# TRD_ID(FK)
    prd_id = Column(Integer, ForeignKey("products.prd_id"), nullable=False)    # PRD_ID(FK)

    prd_code = Column(String(13), nullable=False)                               # PRD_CODE
    prd_name = Column(String(50), nullable=False)                               # PRD_NAME
    prd_price = Column(Integer, nullable=False)                                 # PRD_PRICE (int)
    qty = Column(Integer, nullable=False, default=1)                            # ★数量（実務上必須）

    transaction = relationship("Transaction", back_populates="items")
