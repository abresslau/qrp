-- Verify sym:membership_proposal on pg

SELECT proposal_id, universe_id, raw_identifier, change, effective_date,
       effective_date_precision, source, first_seen, last_seen, seen_count,
       corroborating_sources, status, reason, decided_at, decided_by, detail,
       created_at, updated_at
  FROM membership_proposal
 WHERE FALSE;
