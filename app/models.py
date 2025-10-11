from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Product(Base):
    __tablename__ = "products"

    code: Mapped[str] = mapped_column(String(13), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (Index("ix_transactions_created_at", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ttl_amt_ex_tax: Mapped[int] = mapped_column(Integer, nullable=False)
    tax_amt: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amt: Mapped[int] = mapped_column(Integer, nullable=False)
    clerk_cd: Mapped[str] = mapped_column(String(16), nullable=False)
    store_cd: Mapped[str] = mapped_column(String(16), nullable=False)
    pos_id: Mapped[str] = mapped_column(String(16), nullable=False)

    details: Mapped[list["TransactionDetail"]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="TransactionDetail.id",
    )


class TransactionDetail(Base):
    __tablename__ = "transaction_details"
    __table_args__ = (Index("ix_transaction_details_transaction_id", "transaction_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    transaction_id: Mapped[str] = mapped_column(String(36), ForeignKey("transactions.id", ondelete="CASCADE"))
    product_code: Mapped[str] = mapped_column(String(13), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total: Mapped[int] = mapped_column(Integer, nullable=False)
    tax_cd: Mapped[str] = mapped_column(String(2), nullable=False, default="10")

    transaction: Mapped[Transaction] = relationship(back_populates="details")
