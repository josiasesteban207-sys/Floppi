# FLOPPI 1.2.2 - Expired Job Recovery

The API now checks for backtest jobs whose worker lease has expired. This is
for historical DEMO simulations only; recovery never submits a financial
order or calls a broker.

## Recovery policy

- The API lifecycle starts a recovery loop immediately and repeats every 15
  seconds.
- Each pass is bounded to 100 expired leases. Supabase work runs through a
  service-role RPC; the memory DEMO implementation uses the same process-local
  repository.
- A recovered task below `max_attempts` returns to `pending`, clears the old
  worker/lease token, and receives exponential retry delay:
  `min(300 seconds, 5 * 2^(attempt_count - 1))`.
- A task at its attempt limit becomes `failed` and receives a completion
  timestamp and explicit error.
- Only rows still `running` with an expired lease are changed, so repeating
  recovery is idempotent.
- Completion and failure remain lease-token-owned. An old worker cannot
  complete the run after its lease has expired or recovery has cleared it.

When an eligible worker asks for work first, the capacity-aware atomic claim
RPC may take an already-expired lease directly. If the recovery loop handles it
first, the retry delay applies. Both paths serialize on the run row and retain
the existing attempt limit.

## Supabase migration

Apply `database/migrations/015_expired_job_recovery.sql` after migration 014.
It adds a partial index for expired running leases and the bounded
`recover_expired_backtest_runs` RPC. The RPC uses `FOR UPDATE SKIP LOCKED`,
clears lease ownership, applies backoff or final failure, and can be safely
called repeatedly.

RLS is not disabled and no anon/authenticated policy is added. RPC execution is
revoked from `public`, `anon`, and `authenticated`, and granted only to
`service_role`. Apply with an authorized Supabase administrator and verify
against the target database before deploying API 1.2.2.

## Recovery scenarios and limits

- Worker crash/disconnect: the current lease remains valid until expiry; after
  expiry, the claim path or periodic recovery makes it eligible for retry.
- API restart: persistent Supabase runs are examined when the recovery loop
  starts. `memory-demo` has no durable job state and cannot recover work lost
  when its process exits.
- Retryable worker failure: the existing failure endpoint uses the same
  capped exponential backoff and max-attempt policy.
- Duplicate/stale completion: the run status and lease token prevent an old
  worker from overwriting a recovered or completed run.
- Batch backlog: more than 100 expired runs are handled over subsequent loop
  iterations; recovery does not lock the entire queue.

Automated tests simulate expired leases, attempt exhaustion, stale completion,
and repeated recovery. They do not kill a live remote worker or validate the
RPC against a production Supabase project.
