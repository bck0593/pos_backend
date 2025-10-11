# POS Lv3 Backend

FastAPI implementation of the Tech0 Step4 POS Lv3 specification. The service exposes a very small surface area focused on:

- 商品マスタ検索 `GET /api/products/{code}`
- 取引登録 `POST /api/purchase`
- ヘルスチェック `GET /healthz`

The database schema follows the spec:

- `products` … マスタ（`code`, `name`, `unit_price`）
- `transactions` … `ttl_amt_ex_tax`, `tax_amt`, `total_amt`, `clerk_cd`, `store_cd`, `pos_id`
- `transaction_details` … 明細。`tax_cd` は常に `'10'`

## Prerequisites

- Python 3.11+

## Setup

```bash
pip install -r requirements.txt
cp .env .env.local  # or adjust the provided .env file
```

Environment variables (`backend/.env` already contains sensible defaults):

- `DATABASE_URL` — SQLite by default (`sqlite+pysqlite:///./posapp.db`)
- `CORS_ORIGINS` — comma separated list of allowed frontends
- `CLERK_CODE` / `STORE_CODE` / `POS_ID` — 固定識別子（仕様では 9999999999 / 30 / 90）
- `TAX_PERCENT` — 消費税率（デフォルト 10）
- `TAX_CODE` — 明細の税区分コード（デフォルト `10`）

## Running

```bash
uvicorn app.main:app --reload
```

起動時にテーブルを作成し、`seed_items.py` の商品マスタを自動登録します。

## API Outline

| Method & Path              | 説明                                            |
| -------------------------- | ----------------------------------------------- |
| `GET /healthz`             | 稼働確認 (`{"status": "ok"}`)                   |
| `GET /api/products/{code}` | 商品コードからマスタを返却。存在しない場合は `null` |
| `POST /api/purchase`       | 取引登録。サーバー側で税抜・税額・税込を再計算 |

`POST /api/purchase` へのリクエストは下記のような形式です：

```json
{
  "lines": [
    { "code": "4901234567890", "qty": 2 },
    { "code": "4906789012345", "qty": 1 }
  ]
}
```

レスポンス例：

```json
{
  "transaction_id": "8c9c7e35-0de9-4de3-8654-a2d4f8a4d4ad",
  "created_at": "2025-10-10T09:30:15.123456+00:00",
  "ttl_amt_ex_tax": 36000,
  "tax_amt": 3600,
  "total_amt": 39600,
  "clerk_cd": "9999999999",
  "store_cd": "30",
  "pos_id": "90",
  "lines": [
    {
      "code": "4901234567890",
      "name": "・・・",
      "unit_price": 18000,
      "qty": 2,
      "line_total": 36000,
      "tax_cd": "10"
    }
  ]
}
```

## Testing

Basic HTTP smoke tests are located under `backend/tests/test_api.py`. They use the in-memory SQLite database (`test_posapp.db`) and cover:

- プロダクト検索の成否
- 取引登録時の税込・税抜計算
- 登録レコード件数の検証

Run them with:

```bash
pytest backend/tests/test_api.py
```
