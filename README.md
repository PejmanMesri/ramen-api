# Ramen API

FastAPI backend for **Ramen** — a study-abroad application platform
(universities catalog, subscriptions, Zarinpal payments, applications).

Deployed on [Koyeb](https://www.koyeb.com) (Docker) with a [Neon](https://neon.tech)
Postgres database. Frontend lives at <https://pejmanmesri.github.io/ramen-web/>.

## Required environment variables

| Key | Value |
|-----|-------|
| `DATABASE_URL` | Neon Postgres DSN (`postgresql+asyncpg://…`) |
| `JWT_SECRET_KEY` | ≥32-byte random secret |
| `BACKEND_CORS_ORIGINS` | `["https://pejmanmesri.github.io"]` |
| `ZARINPAL__CALLBACK_URL` | `https://pejmanmesri.github.io/ramen-web/payment-result` |

Optional: `ADMIN_USERNAME` / `ADMIN_PASSWORD` (seeded super-admin), `ZARINPAL__MERCHANT_ID`,
`ZARINPAL__MODE`. Alembic migrations run automatically at boot.
