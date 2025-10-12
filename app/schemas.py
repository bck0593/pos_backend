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


class PurchaseResult(BaseModel):
    total_amt: conint(ge=0)

    class Config:
        extra = "forbid"


class HealthOut(BaseModel):
    ok: bool

    class Config:
        extra = "forbid"
