# Worker credential security (0.7.0)

## Credential model

Each worker is assigned a unique node ID and a high-entropy token. The worker
sends the token in `X-Node-Token` and its node ID in `X-Node-Id` (heartbeat
requests bind the token to the `node_id` in the payload). The API hashes the
presented token with SHA-256 and looks up an active credential row. The token
is never stored in the database. Because tokens are generated randomly with
high entropy, a fast cryptographic hash is appropriate for lookup; these are
not human passwords.

The API rejects credentials that are missing, too short, expired, revoked, or
bound to a different node. Successful authentication updates `last_used_at`.
Remote workers require HTTPS. Plain HTTP is allowed only for loopback local
DEMO development.

## Provision a worker

From the project root:

```powershell
python tools\provision_worker.py --node-id blacki --expires-in-days 90
```

The utility prints a raw token once and an SQL statement containing only its
SHA-256 hash. Copy the SQL into the Supabase SQL Editor, then place the token in
the environment of that specific worker:

```powershell
$env:FLOPPI_NODE_ID = "blacki"
$env:FLOPPI_NODE_TOKEN = "<one-time token>"
```

Do not paste the token into source files, screenshots, issue trackers, or chat.
If the token is lost, provision a replacement. The hash cannot be used to
recover the original token.

## Rotate a credential

1. Generate a new token for the same node ID.
2. Insert its generated SQL in Supabase.
3. Update that worker's `FLOPPI_NODE_TOKEN` environment variable and restart it.
4. Revoke the old row using its credential ID or old token hash:

```sql
update public.worker_credentials
set active = false, revoked_at = now()
where id = '<old-credential-uuid>';
```

A short overlap is possible while changing the worker configuration. Revoke
the old credential immediately after the new one is confirmed working.

## Revoke a lost or retired worker

```sql
update public.worker_credentials
set active = false, revoked_at = now()
where node_id = 'blacki' and active = true;
```

Revocation is checked on every authenticated worker request. An already-running
request may finish if revocation occurs concurrently; subsequent requests are
rejected.

## Local development without Supabase

Only when `APP_ENV=development` and Supabase is not configured, the API accepts
a per-node JSON map from `FLOPPI_WORKER_CREDENTIALS_JSON`, for example:

```powershell
$env:FLOPPI_WORKER_CREDENTIALS_JSON = '{"blacki":"<random-token-of-at-least-32-characters>"}'
```

This fallback contains raw tokens in process configuration and must never be
used in production. In production, worker authentication uses the
`worker_credentials` table and the server-side Supabase service role.

## Remaining operational gates

The migration and authentication logic are covered by local tests, but a real
Supabase deployment still needs an operator to apply migration 004 and verify
provisioning, heartbeat, queue claim, completion, expiry, and revocation with
separate test workers. Add rate limiting, credential-expiry monitoring, and
backup/restore procedures before any public deployment.
