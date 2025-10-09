from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, constr, conint, validator

EAN13 = constr(pattern=r"^\d{13}$")


class LoginRequest(BaseModel):
    username: constr(min_length=1, max_length=64)
    password: constr(min_length=1, max_length=128)

    class Config:
        extra = "forbid"


class ItemOut(BaseModel):
    code: EAN13
    name: constr(min_length=1, max_length=255)
    unit_price: conint(ge=0)

    class Config:
        extra = "forbid"


class ItemListOut(BaseModel):
    items: List[ItemOut]

    class Config:
        extra = "forbid"


class SaleLineIn(BaseModel):
    code: EAN13
    name: constr(min_length=1, max_length=255)
    unit_price: conint(ge=0)
    qty: conint(ge=1, le=999)

    class Config:
        extra = "forbid"


class SaleLineOut(SaleLineIn):
    line_total: conint(ge=0)


class SaleIn(BaseModel):
    lines: List[SaleLineIn]
    tax_out: conint(ge=0)
    tax: conint(ge=0)
    tax_in: conint(ge=0)
    device_id: Optional[constr(min_length=1, max_length=128)] = None
    cashier_id: Optional[constr(min_length=1, max_length=128)] = None

    @validator("lines")
    def ensure_lines_not_empty(cls, value: List[SaleLineIn]) -> List[SaleLineIn]:
        if not value:
            raise ValueError("lines must not be empty")
        return value

    class Config:
        extra = "forbid"


class SaleOut(BaseModel):
    id: str
    created_at: datetime
    tax_out: int
    tax: int
    tax_in: int
    device_id: Optional[str]
    cashier_id: Optional[str]
    created_by: Optional[str] = None
    lines: List[SaleLineOut]

    class Config:
        extra = "forbid"


class SaleSummaryOut(BaseModel):
    count: int
    tax_out: int
    tax: int
    tax_in: int

    class Config:
        extra = "forbid"


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int

    class Config:
        extra = "forbid"


class HealthOut(BaseModel):
    status: str

    class Config:
        extra = "forbid"


class MessageOut(BaseModel):
    message: str

    class Config:
        extra = "forbid"
