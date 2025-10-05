from typing import List, Optional

from pydantic import BaseModel, Field


class ProductOut(BaseModel):
    code: str
    name: str
    price: int


class ProductEnvelope(BaseModel):
    product: Optional[ProductOut]


class PurchaseItem(BaseModel):
    product_code: str
    quantity: int = Field(ge=1)


class PurchaseRequest(BaseModel):
    emp_cd: str = "9999999999"
    store_cd: str = "30"
    pos_no: str = "090"
    items: List[PurchaseItem]


class PurchaseResponse(BaseModel):
    success: bool
    transaction_id: int
    total_amount: int
    total_amount_ex_tax: int
    tax_cd: str
    total_in_tax: int | None = None
    total_ex_tax: int | None = None
