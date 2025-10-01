from pydantic import BaseModel, Field
from typing import List

class ProductOut(BaseModel):
    code: str
    name: str
    price: int

class PurchaseItem(BaseModel):
    product_code: str = Field(min_length=13, max_length=13)
    quantity: int = Field(ge=1)

class PurchaseRequest(BaseModel):
    items: List[PurchaseItem]

class PurchaseResponse(BaseModel):
    transaction_id: int
    total_amount: int
