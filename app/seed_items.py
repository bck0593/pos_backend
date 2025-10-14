from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Product

ITEM_ROWS: Iterable[dict[str, object]] = (
    {"code": "4901234567890", "name": "\u4e07\u5e74\u7b46 TECH ONE Signature 14K", "unit_price": 28500},
    {"code": "4902345678901", "name": "\u30dc\u30fc\u30eb\u30da\u30f3 TECH ONE Classic Black", "unit_price": 12800},
    {"code": "4903456789012", "name": "\u30b7\u30e3\u30fc\u30d7\u30da\u30f3\u30b7\u30eb TECH ONE Precision 0.5mm", "unit_price": 9800},
    {"code": "4904567890123", "name": "\u30ce\u30fc\u30c8\u30d6\u30c3\u30af TECH ONE Premium A5 \u4e0a\u8cea\u7d19", "unit_price": 6500},
    {"code": "4905678901234", "name": "\u30de\u30fc\u30ab\u30fc\u30bb\u30c3\u30c8 TECH ONE \u86cd\u514920\u8272\u30fb\u6cb9\u602710\u8272", "unit_price": 3200},
    {"code": "4906789012345", "name": "\u30da\u30f3\u30b1\u30fc\u30b9 \u30a4\u30bf\u30ea\u30a2\u30f3\u30ec\u30b6\u30fc \u30d6\u30e9\u30a6\u30f3", "unit_price": 8900},
    {"code": "4907890123456", "name": "\u30c7\u30b9\u30af\u30de\u30c3\u30c8 \u900f\u660e 60\u00d740cm \u30c0\u30fc\u30af\u30d6\u30e9\u30a6\u30f3", "unit_price": 15800},
    {"code": "4908901234567", "name": "\u30da\u30fc\u30d1\u30fc\u30a6\u30a7\u30a4\u30c8 \u7af9\u88fd \u3059\u3079\u308a\u6b62\u3081\u30c7\u30b6\u30a4\u30f3", "unit_price": 7400},
    {"code": "4909012345678", "name": "\u30ab\u30c3\u30bf\u30fc\uff0f\u30aa\u30fc\u30d7\u30ca\u30fc \u30b9\u30c6\u30f3\u30ec\u30b9\u88fd \u3059\u3079\u308a\u6b62\u3081\u30b0\u30ea\u30c3\u30d7", "unit_price": 4200},
    {"code": "4910123456789", "name": "\u30a4\u30f3\u30af\u30dc\u30c8\u30eb TECH ONE \u30d6\u30e9\u30c3\u30af 50ml", "unit_price": 2800},
    {"code": "4911234567890", "name": "\u4e07\u5e74\u7b46\u30b1\u30fc\u30b9 1\u672c\u7528 \u672c\u9769\u30dc\u30c3\u30af\u30b9", "unit_price": 5600},
    {"code": "4530966704651", "name": "\u30d6\u30c3\u30af\u30b9\u30bf\u30f3\u30c9 \u7af9\u88fd \u30a2\u30f3\u30c6\u30a3\u30fc\u30af\u8abf", "unit_price": 11200},
    {"code": "4969757165713", "name": "\u304a\u301c\u3044\u304a\u8336\uff08\u7dd1\u8336\uff09", "unit_price": 200},
)


def seed_items(session: Session, *, force: bool = False) -> None:
    """
    Insert or refresh the master products.
    When ``force`` is True, extra rows that are not in ``ITEM_ROWS`` will be removed.
    """
    desired_codes = {row["code"] for row in ITEM_ROWS}
    existing = {product.code: product for product in session.scalars(select(Product))}
    inserted_or_updated = False

    for row in ITEM_ROWS:
        product = existing.get(row["code"])
        if product:
            if (
                force
                or product.name != row["name"]
                or product.unit_price != row["unit_price"]
            ):
                product.name = row["name"]  # type: ignore[assignment]
                product.unit_price = row["unit_price"]  # type: ignore[assignment]
                inserted_or_updated = True
        else:
            session.add(Product(**row))
            inserted_or_updated = True

    if force:
        for code, product in existing.items():
            if code not in desired_codes:
                session.delete(product)
                inserted_or_updated = True

    if inserted_or_updated:
        session.commit()
