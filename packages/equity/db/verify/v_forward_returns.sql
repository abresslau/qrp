-- Verify equity:v_forward_returns on pg

BEGIN;

SELECT composite_figi, window_id, as_of_date, fwd_end_date, fwd_pr, fwd_tr
  FROM equity.v_forward_returns WHERE false;

COMMIT;
