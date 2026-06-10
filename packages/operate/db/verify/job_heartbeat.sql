-- Verify qrp_core:job_heartbeat on pg

SELECT heartbeat_at FROM qrp.job WHERE FALSE;
