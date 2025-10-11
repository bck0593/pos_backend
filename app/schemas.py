from datetime import datetime
from typing import List

from pydantic import BaseModel, conint, constr, field_validator

EAN13 = constr(pattern=r"^\d{13}$")


class ProductOut(BaseModel):
    code: EAN13
    name: constr(min_length=1, max_length=255)
    unit_price: conint(ge=0)

    class Config:
        extra = "forbid"


class PurchaseLineIn(BaseModel):
    code: EAN13
    qty: conint(ge=1, le=999)

    class Config:
        extra = "forbid"


class PurchaseLineOut(BaseModel):
    code: EAN13
    name: constr(min_length=1, max_length=255)
    unit_price: conint(ge=0)
    qty: conint(ge=1, le=999)
    line_total: conint(ge=0)
    tax_cd: constr(min_length=2, max_length=2)

    class Config:
        extra = "forbid"


class PurchaseIn(BaseModel):
    lines: List[PurchaseLineIn]

    @field_validator("lines")
    @classmethod
    def ensure_lines_not_empty(cls, value: List[PurchaseLineIn]) -> List[PurchaseLineIn]:
        if not value:
            raise ValueError("lines must not be empty")
        return value

    class Config:
        extra = "forbid"


class PurchaseOut(BaseModel):
    transaction_id: str
    created_at: datetime
    ttl_amt_ex_tax: int
    tax_amt: int
    total_amt: int
    clerk_cd: str
    store_cd: str
    pos_id: str
    lines: List[PurchaseLineOut]

    class Config:
        extra = "forbid"


class HealthOut(BaseModel):
    status: str

    class Config:
        extra = "forbid"
