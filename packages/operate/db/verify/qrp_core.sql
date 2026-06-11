-- Verify qrp_core:qrp_core on pg
-- (Reworked by QH.5's deploy-all run: later changes renamed columns this change
-- created; what survives is asserted at its CURRENT name.)

-- The portfolio tables this change created were moved to the `portfolios` database by
-- `split_portfolios`; what survives here is the Operate job ledger.
SELECT job_id, op, args, status, exit_code, output, error, created_at, started_at,
       finished_at, heartbeat_at
  FROM qrp.job WHERE FALSE;
