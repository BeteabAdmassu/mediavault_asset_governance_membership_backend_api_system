# MediaVault API

A MediaVault Asset Governance and Membership system backend API.

## Quick Start

```bash
docker compose up
```

## CI Flow

```bash
git clone <repo-url>
cd repo/
docker compose build
docker compose up -d
./run-tests.sh
```

Note: `run-tests.sh` is self-sufficient — no prior `pip install` is needed.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FIELD_ENCRYPTION_KEY` | **Yes** | — | Base64-encoded 32-byte AES key for encrypting sensitive fields. App refuses to start without it. |
| `DATABASE_URL` | No | `sqlite:///data/mediavault.db` | SQLAlchemy database URL |
| `LOG_LEVEL` | No | `INFO` | Logging level (DEBUG/INFO/WARNING/ERROR/CRITICAL) |
| `LOG_FILE` | No | — | Path to log file for rotation |

## API Examples

### Health Check

```bash
curl http://localhost:5000/healthz
```

Response:
```json
{"status": "ok", "db": "connected"}
```

### Auth

```bash
# Register
curl -X POST http://localhost:5000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "email": "alice@example.com", "password": "Secret123!"}'

# Login
curl -X POST http://localhost:5000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "Secret123!"}'

# Logout
curl -X POST http://localhost:5000/auth/logout \
  -H "Authorization: Bearer <token>"
```

### Risk

```bash
# Evaluate risk for a user action
curl -X POST http://localhost:5000/risk/evaluate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"event_type": "login", "ip": "1.2.3.4"}'
```

### Membership

```bash
# Get current user's membership
curl http://localhost:5000/membership/me \
  -H "Authorization: Bearer <token>"

# Accrue points
curl -X POST http://localhost:5000/membership/accrue \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin-token>" \
  -d '{"user_id": 1, "amount": 100, "currency": "points", "reason": "purchase", "idempotency_key": "order-123"}'
```

### Marketing

```bash
# List campaigns
curl http://localhost:5000/marketing/campaigns \
  -H "Authorization: Bearer <admin-token>"

# Validate incentives / coupon
curl -X POST http://localhost:5000/marketing/validate-incentives \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"coupon_code": "SAVE10", "order_total_cents": 5000}'
```

### Assets

```bash
# Create an asset (admin/moderator)
curl -X POST http://localhost:5000/assets \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin-token>" \
  -d '{"title": "My Image", "asset_type": "image", "category_id": 1, "source": "internal", "copyright": "CC0"}'

# List assets
curl http://localhost:5000/assets \
  -H "Authorization: Bearer <token>"
```

### Profiles

```bash
# Get a user's profile
curl http://localhost:5000/profiles/1 \
  -H "Authorization: Bearer <token>"

# Follow a user
curl -X POST http://localhost:5000/profiles/1/follow \
  -H "Authorization: Bearer <token>"
```

### Policies

```bash
# Create a policy (admin)
curl -X POST http://localhost:5000/policies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin-token>" \
  -d '{"policy_type": "access", "name": "Default Access", "semver": "1.0.0", "effective_from": "2025-01-01T00:00:00", "rules_json": "{}"}'

# Activate a policy (admin)
curl -X POST http://localhost:5000/policies/1/activate \
  -H "Authorization: Bearer <admin-token>"

# Resolve applicable policy
curl -X POST http://localhost:5000/policies/resolve \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"policy_type": "access"}'
```

### Compliance

```bash
# Submit a data export request
curl -X POST http://localhost:5000/compliance/export-request \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"reason": "personal data export"}'

# Submit a deletion request
curl -X POST http://localhost:5000/compliance/deletion-request \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"reason": "right to be forgotten"}'
```

### Admin

```bash
# List users (admin)
curl http://localhost:5000/admin/users \
  -H "Authorization: Bearer <admin-token>"

# List audit logs (admin)
curl http://localhost:5000/admin/audit-logs \
  -H "Authorization: Bearer <admin-token>"
```

### API Documentation

Visit `http://localhost:5000/docs` for the interactive Swagger UI.

The OpenAPI spec is available at `http://localhost:5000/openapi.json`.

## Known Limitations

- Single-machine SQLite deployment; not horizontally scalable.
- No JWT; sessions stored in DB — horizontal scaling requires a shared session store.
- All operations are offline; no third-party integrations (email, SMS, payment processors).
- WAL mode is SQLite-only; switching to PostgreSQL requires removing the WAL pragma setup.
- Rate limiting uses in-memory storage by default; counters reset on restart and are not shared across processes.
- File uploads are not supported; assets store metadata only, not binary content.
- No background job processing; compliance deletion and data export requests must be processed manually or by a separate worker.
