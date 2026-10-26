-- Allow larger books while retaining the private, PDF-only bucket.
-- Run after 0001_phase1_schema.sql. Also ensure the project's global
-- Storage file size limit allows at least 50 MiB (52,428,800 bytes).
update storage.buckets
set file_size_limit = 52428800
where id = 'books-private';
