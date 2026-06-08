-- Verify sym:securities_review_queue on pg

-- Errors if the table or any expected column is absent.
SELECT review_id, source_key, source_input, candidates, status,
       detail, resolved_at, created_at, updated_at
  FROM securities_review_queue
 WHERE FALSE;
