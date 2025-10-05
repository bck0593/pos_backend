from typing import List, Optional

from sqlalchemy import (
    CHAR,
    TIMESTAMP,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Product(Base):
    __tablename__ = "product"

    prd_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(25), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("code", name="uq_product_code"),
        CheckConstraint("length(code) > 0", name="ck_product_code_non_empty"),
    )


class Trade(Base):
    __tablename__ = "trade"

    trd_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    datetime: Mapped[str] = mapped_column(TIMESTAMP, server_default=func.now())
    emp_cd: Mapped[str] = mapped_column(CHAR(10), nullable=False)
    store_cd: Mapped[str] = mapped_column(CHAR(5), nullable=False)
    pos_no: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    total_amt: Mapped[int] = mapped_column(Integer, nullable=False)
    ttl_amt_ex_tax: Mapped[int] = mapped_column(Integer, nullable=False)

    details: Mapped[List["TradeDetail"]] = relationship(
        back_populates="trade", cascade="all, delete-orphan"
    )


class TradeDetail(Base):
    __tablename__ = "trade_detail"

    trd_id: Mapped[int] = mapped_column(Integer, ForeignKey("trade.trd_id"), primary_key=True)
    dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prd_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("product.prd_id"), nullable=True)
    prd_code: Mapped[str] = mapped_column(CHAR(13))
    prd_name: Mapped[str] = mapped_column(String(50))
    prd_price: Mapped[int] = mapped_column(Integer)
    tax_cd: Mapped[str] = mapped_column(CHAR(2))

    trade: Mapped["Trade"] = relationship(back_populates="details")
    product: Mapped[Optional["Product"]] = relationship()
