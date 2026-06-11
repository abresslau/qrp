-- Verify sym:membership_proposal on pg
-- (Reworked by QH.5's deploy-all run: later changes renamed columns this change
-- created; what survives is asserted at its CURRENT name.)

SELECT proposal_id, universe_id, raw_identifier, change, effective_date,
       effective_date_precision, source, first_seen_date, last_seen_date, seen_count,
       corroborating_sources, status, reason, decided_at, decided_by, detail,
       created_at, updated_at
  FROM membership_proposal
 WHERE FALSE;
