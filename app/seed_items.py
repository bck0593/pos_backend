from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Product

ITEM_ROWS: Sequence[dict[str, object]] = (
    {"code": "4901234567890", "name": "万年筆 TECH ONE Signature 14K", "unit_price": 28500},
    {"code": "4902345678901", "name": "ボールペン TECH ONE Classic Black", "unit_price": 12800},
    {"code": "4903456789012", "name": "シャープペンシル TECH ONE Precision 0.5mm", "unit_price": 9800},
    {"code": "4904567890123", "name": "ノートブック TECH ONE Premium A5 上質紙", "unit_price": 6500},
    {"code": "4905678901234", "name": "マーカーセット TECH ONE 蛍光20色・油性10色", "unit_price": 3200},
    {"code": "4906789012345", "name": "ペンケース イタリアンレザー ブラウン", "unit_price": 8900},
    {"code": "4907890123456", "name": "デスクマット 透明 60×40cm ダークブラウン", "unit_price": 15800},
    {"code": "4908901234567", "name": "ペーパーウェイト 竹製 すべり止めデザイン", "unit_price": 7400},
    {"code": "4909012345678", "name": "カッター／オープナー ステンレス製 すべり止めグリップ", "unit_price": 4200},
    {"code": "4910123456789", "name": "インクボトル TECH ONE ブラック 50ml", "unit_price": 2800},
    {"code": "4911234567890", "name": "万年筆ケース 1本用 本革ボックス", "unit_price": 5600},
    {"code": "4912345678901", "name": "ブックスタンド 竹製 アンティーク調", "unit_price": 11200},
    {"code": "4969757165713", "name": "お〜いお茶（緑茶）", "unit_price": 200},
)



def seed_items(session: Session, *, force: bool = False) -> None:
    existing_codes: set[str] = set(session.scalars(select(Product.code)))
    to_insert: list[Product] = []
    for row in ITEM_ROWS:
        if force or row["code"] not in existing_codes:
            to_insert.append(Product(**row))
    if to_insert:
        session.add_all(to_insert)
        session.commit()
