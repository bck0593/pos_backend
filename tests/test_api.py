import os
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_posapp.db")
os.environ.setdefault("CORS_ORIGINS", "http://testserver")

from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Product, Transaction  # noqa: E402

TEST_DB_PATH = Path("test_posapp.db")


def setup_module() -> None:
    engine.dispose()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


def teardown_module() -> None:
    engine.dispose()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


def yen_round(value: int | float | Decimal) -> int:
    if isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, int):
        decimal_value = Decimal(value)
    else:
        decimal_value = Decimal(str(value))
    return int(decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def test_healthz() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_product_lookup() -> None:
    with TestClient(app) as client:
        product_response = client.get("/api/products/4901234567890")
        assert product_response.status_code == 200
        product_json = product_response.json()
        assert product_json["code"] == "4901234567890"

        missing_response = client.get("/api/products/0000000000000")
        assert missing_response.status_code == 200
        assert missing_response.json() is None


def test_purchase_aggregates_lines_and_persists_totals() -> None:
    with TestClient(app) as client:
        with SessionLocal() as session:
            if session.get(Product, "1234567890128") is None:
                session.add(
                    Product(
                        code="1234567890128",
                        name="テスト商品",
                        unit_price=123,
                    )
                )
                session.commit()

        payload = {
            "lines": [
                {"code": "4901234567890", "qty": 2},
                {"code": "4901234567890", "qty": 3},
                {"code": "4969757165713", "qty": 4},
                {"code": "1234567890128", "qty": 3},
            ]
        }
        response = client.post("/api/purchase", json=payload)
        assert response.status_code == 201
        body = response.json()
        assert body["transaction_id"]
        assert len(body["lines"]) == 3

        expected_ex_tax = 28500 * 5 + 200 * 4 + 123 * 3
        expected_tax = yen_round(Decimal(expected_ex_tax) * Decimal("0.10"))
        expected_total = expected_ex_tax + expected_tax

        assert body["ttl_amt_ex_tax"] == expected_ex_tax
        assert body["tax_amt"] == expected_tax
        assert body["total_amt"] == expected_total

        quantities = {line["code"]: line["qty"] for line in body["lines"]}
        assert quantities["4901234567890"] == 5
        assert quantities["4969757165713"] == 4
        assert quantities["1234567890128"] == 3

        with SessionLocal() as session:
            count = session.scalar(select(func.count(Transaction.id))) or 0
            assert count == 1
            transaction = session.execute(
                select(Transaction).order_by(Transaction.created_at.desc())
            ).scalars().first()
            assert transaction is not None
            assert transaction.ttl_amt_ex_tax == expected_ex_tax
            assert transaction.tax_amt == expected_tax
            assert transaction.total_amt == expected_total
            assert transaction.clerk_cd == "9999999999"
            assert transaction.store_cd == "30"
            assert transaction.pos_id == "90"
            detail_quantities = {detail.product_code: detail.quantity for detail in transaction.details}
            assert detail_quantities["4901234567890"] == 5
            assert detail_quantities["4969757165713"] == 4
            assert detail_quantities["1234567890128"] == 3
            assert all(detail.tax_cd == "10" for detail in transaction.details)
