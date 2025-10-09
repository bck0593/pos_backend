# POS Lv3 Backend

FastAPI implementation of the Level 3 POS API with layered JWT authentication (access + refresh), rate limiting, and hardened defaults.

## Prerequisites

- Python 3.11+
- (Optional) virtual environment

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env  # adjust values before running
```

Key environment variables:

- `DATABASE_URL` — defaults to SQLite (switchable to MySQL/Postgres)
- `CORS_ORIGINS` — comma-separated list of allowed frontend origins (no wildcard)
- `JWT_SECRET`, `JWT_ALGORITHM` — token signing configuration
- `ACCESS_TOKEN_EXPIRES_MINUTES`, `REFRESH_TOKEN_EXPIRES_MINUTES`
- `REFRESH_COOKIE_NAME`, `REFRESH_COOKIE_PATH`, `COOKIE_SECURE`, `COOKIE_SAMESITE`
- `DEFAULT_TOKEN_SCOPES` — space separated scopes granted at login
- `DEMO_USERNAME`, `DEMO_PASSWORD` (or `DEMO_PASSWORD_HASH` for sha256 hash)
- `ALLOW_CUSTOM_ITEMS` — whether unknown product codes are accepted when payload matches master data
- `IDENTIFIER_HASH_SECRET` — salt for hashing device / cashier identifiers

## Running

```bash
uvicorn app.main:app --reload
```

On startup the API creates tables and seeds the shared item master defined in `seed_items.py`.

## Authentication Flow

- `POST /auth/login` — accepts `{ "username", "password" }`, returns a short-lived access token and sets an HTTP-only refresh token cookie.
- `POST /auth/refresh` — rotates the refresh token and returns a new access token (requires the refresh cookie).
- `POST /auth/logout` — clears the refresh token cookie.

The frontend stores the access token in memory only and sends it via `Authorization: Bearer` headers. Refresh tokens never leave the HTTP-only cookie.

## Protected Endpoints

- `GET /items`, `GET /items/{code}` — require `items:read` scope
- `POST /sales`, `GET /sales*`, `DELETE /sales/{id}` — require appropriate `sales:*` scopes
- All `/sales` submissions are re-calculated server side (tax-out, tax, tax-in) and persist with hashed device/cashier identifiers.

## Security Features

- CORS locked to configured origins, credentials enabled
- Sliding-window rate limiting for authentication and sales endpoints
- Access tokens (default 10 minutes) + refresh tokens (default 3 days) with rotation
- UUID-based sale identifiers (unguessable)
- Input validation for EAN-13 product codes, quantities, and prices
- Optional hashing of device/cashier identifiers prior to persistence
- Structured audit logging for sale creation
- HTTPS/TLS required in production (ensure reverse proxy terminates TLS)
- No API base URL is logged or exposed in generated responses

## Response & Error Format

Errors are returned as `{"detail": "..."}` with sanitized messages. Frontend should map generic user-facing messages without leaking backend context.
