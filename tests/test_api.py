import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault('DATABASE_URL', 'sqlite:///./test_posapp.db')
os.environ.setdefault('CORS_ORIGINS', 'http://testserver')
os.environ.setdefault('JWT_SECRET', 'test-secret')
os.environ.setdefault('ALLOW_CUSTOM_ITEMS', 'false')

from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Sale  # noqa: E402

TEST_DB_PATH = Path('test_posapp.db')


def _login_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        '/auth/login',
        json={'username': 'demo', 'password': 'demo123'},
    )
    assert response.status_code == 200
    token = response.json()['access_token']
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture(autouse=True)
def clean_db():
    engine.dispose()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    yield
    engine.dispose()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_healthz(client: TestClient) -> None:
    response = client.get('/healthz')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


def test_get_item_success_and_not_found(client: TestClient) -> None:
    headers = _login_headers(client)

    ok_response = client.get('/items/4901234567890', headers=headers)
    assert ok_response.status_code == 200
    assert ok_response.json()['code'] == '4901234567890'

    missing_response = client.get('/items/0000000000001', headers=headers)
    assert missing_response.status_code == 404


def test_post_sale_persists_and_is_retrievable(client: TestClient) -> None:
    headers = _login_headers(client)

    items_response = client.get('/items', headers=headers)
    assert items_response.status_code == 200
    items = items_response.json()['items']
    assert len(items) >= 2
    first, second = items[0], items[1]

    sale_payload = {
        'lines': [
            {
                'code': first['code'],
                'name': first['name'],
                'unit_price': first['unit_price'],
                'qty': 2,
            },
            {
                'code': second['code'],
                'name': second['name'],
                'unit_price': second['unit_price'],
                'qty': 1,
            },
        ],
    }
    tax_out = first['unit_price'] * 2 + second['unit_price']
    tax = round(tax_out * 0.1)
    tax_in = tax_out + tax
    sale_payload.update({'tax_out': tax_out, 'tax': tax, 'tax_in': tax_in})

    create_response = client.post('/sales', json=sale_payload, headers=headers)
    assert create_response.status_code == 200
    created = create_response.json()
    assert created['tax_out'] == tax_out
    assert created['tax'] == tax
    assert created['tax_in'] == tax_in
    assert len(created['lines']) == 2

    sale_id = created['id']
    get_response = client.get(f'/sales/{sale_id}', headers=headers)
    assert get_response.status_code == 200
    fetched = get_response.json()
    assert fetched['id'] == sale_id
    assert fetched['tax_in'] == tax_in

    with SessionLocal() as session:
        db_sale = session.get(Sale, sale_id)
        assert db_sale is not None
        assert len(db_sale.lines) == 2


def test_transaction_rolls_back_on_invalid_item(client: TestClient) -> None:
    headers = _login_headers(client)
    invalid_payload = {
        'lines': [
            {
                'code': '9999999999999',
                'name': 'Fake Item',
                'unit_price': 100,
                'qty': 1,
            }
        ],
        'tax_out': 100,
        'tax': 10,
        'tax_in': 110,
    }

    with SessionLocal() as session:
        existing_sales = session.scalar(select(func.count(Sale.id))) or 0

    response = client.post('/sales', json=invalid_payload, headers=headers)
    assert response.status_code == 400

    with SessionLocal() as session:
        post_sales = session.scalar(select(func.count(Sale.id))) or 0
    assert post_sales == existing_sales
