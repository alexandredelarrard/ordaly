-- Placeholder: persist PDF parse jobs when the pipeline writes to Postgres.
-- Columns should match your future migration (e.g. id, path, sender, status, created_at).
INSERT INTO document_parse_jobs (file_path, sender_email, status, created_at)
VALUES (:file_path, :sender_email, 'received', NOW())
RETURNING id;
