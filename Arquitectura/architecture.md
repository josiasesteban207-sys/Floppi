# FLOPPI hybrid architecture decisions

## Cloud responsibilities
- API gateway and orchestration
- Supabase Auth and PostgreSQL
- User notification preferences and event history
- Mobile/web/Telegram API surface

## Main PC responsibilities (phase 1)
- Local inference and feature calculations
- Controlled experiments in a future isolated sandbox
- Outbound heartbeat to cloud API
- No inbound public port forwarding

## Availability
Cloud services remain reachable when the PC is off. Local compute tasks are queued
or marked unavailable until the PC reconnects. The cloud must not pretend that a
local analysis has run when the node is offline.

## Security gates before public launch
1. Supabase JWT verification in every user endpoint.
2. User identity derived from token, never from a URL parameter.
3. Per-user authorization and rate limiting.
4. HTTPS only; secrets in deployment secret manager.
5. Node credential rotation and per-node credentials.
6. CORS allowlist for exact production origins.
7. Audit logging and backup/restore tests.
8. Sandbox isolation, CPU/RAM/time limits and manual promotion approval.

## Trading boundary
Educational analytics, synthetic/historical data, backtesting and paper trading only.
No broker credentials, real-money order placement or autonomous live trading.
