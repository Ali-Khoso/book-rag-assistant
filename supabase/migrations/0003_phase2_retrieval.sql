-- Phase 2: processing status, retry, and owner-scoped vector storage/search.
-- Run once after 0001 and 0002. All processing RPCs are backend-only.
begin;

-- Processing status and retry: a run ID prevents old workers writing after retry.
alter table public.documents
  add column if not exists processing_error text,
  add column if not exists processing_stage text,
  add column if not exists processing_run_id uuid,
  add column if not exists processing_updated_at timestamptz,
  add column if not exists processed_at timestamptz,
  add column if not exists chunk_count integer not null default 0,
  add column if not exists embedding_model text;

alter table public.chunks
  add column if not exists processing_run_id uuid,
  add column if not exists embedding_model text;

-- The default local model and the optional hosted provider both use 256 dimensions.
-- Phase 1 did not create embeddings; incompatible existing vectors stop this
-- migration rather than silently deleting or changing an existing index.
alter table public.chunks alter column embedding type extensions.vector(256);
create index if not exists chunks_embedding_hnsw_idx
  on public.chunks using hnsw (embedding extensions.vector_cosine_ops);
create index if not exists documents_processing_queue_idx
  on public.documents (status, created_at);

-- Claim one job atomically. A crashed worker's lease expires after 15 minutes.
create or replace function public.phase2_claim_next(p_run_id uuid, p_model text)
returns setof public.documents
language plpgsql security invoker set search_path = public, extensions
as $$
declare target public.documents;
begin
  select * into target from public.documents
  where status = 'queued'
     or (status = 'processing' and processing_updated_at < now() - interval '15 minutes')
  order by created_at for update skip locked limit 1;
  if not found then return; end if;
  delete from public.chunks where document_id = target.id and user_id = target.user_id;
  update public.documents set status = 'processing', processing_run_id = p_run_id,
    processing_error = null, processing_stage = 'Reading PDF',
    processing_updated_at = now(), processed_at = null, chunk_count = 0,
    page_count = null, embedding_model = p_model
  where id = target.id returning * into target;
  return next target;
end;
$$;

create or replace function public.phase2_progress(
  p_document_id uuid, p_user_id uuid, p_run_id uuid, p_stage text)
returns boolean language plpgsql security invoker set search_path = public, extensions
as $$
begin
  update public.documents set processing_stage = left(p_stage, 120), processing_updated_at = now()
  where id = p_document_id and user_id = p_user_id
    and status = 'processing' and processing_run_id = p_run_id;
  return found;
end;
$$;

-- Vector storage: lock and check the lease before every batch, including retries.
create or replace function public.phase2_append_chunks(
  p_document_id uuid, p_user_id uuid, p_run_id uuid, p_chunks jsonb)
returns integer language plpgsql security invoker set search_path = public, extensions
as $$
declare model_name text; inserted_count integer;
begin
  select embedding_model into model_name from public.documents
  where id = p_document_id and user_id = p_user_id
    and status = 'processing' and processing_run_id = p_run_id for update;
  if not found then raise exception 'Processing lease expired'; end if;
  if jsonb_array_length(p_chunks) > 128 then raise exception 'Chunk batch too large'; end if;
  insert into public.chunks
    (document_id, user_id, content, embedding, page_start, page_end, chunk_index,
     processing_run_id, embedding_model)
  select p_document_id, p_user_id, item->>'content',
    (item->'embedding')::text::extensions.vector(256),
    (item->>'page_start')::integer, (item->>'page_end')::integer,
    (item->>'chunk_index')::integer, p_run_id, model_name
  from jsonb_array_elements(p_chunks) item;
  get diagnostics inserted_count = row_count;
  update public.documents set chunk_count = chunk_count + inserted_count,
    processing_updated_at = now() where id = p_document_id;
  return inserted_count;
end;
$$;

create or replace function public.phase2_finish(
  p_document_id uuid, p_user_id uuid, p_run_id uuid,
  p_page_count integer, p_expected_chunks integer)
returns boolean language plpgsql security invoker set search_path = public, extensions
as $$
declare actual_count integer; first_index integer; last_index integer;
begin
  perform 1 from public.documents where id = p_document_id and user_id = p_user_id
    and status = 'processing' and processing_run_id = p_run_id for update;
  if not found then return false; end if;
  select count(*), min(chunk_index), max(chunk_index)
    into actual_count, first_index, last_index from public.chunks
    where document_id = p_document_id and user_id = p_user_id and processing_run_id = p_run_id;
  if actual_count < 1 or actual_count <> p_expected_chunks
     or first_index <> 0 or last_index <> actual_count - 1 then
    raise exception 'Incomplete document index';
  end if;
  update public.documents set status = 'ready', processing_stage = 'Ready to search',
    page_count = p_page_count, chunk_count = actual_count, processing_error = null,
    processed_at = now(), processing_updated_at = now()
    where id = p_document_id;
  return true;
end;
$$;

create or replace function public.phase2_fail(
  p_document_id uuid, p_user_id uuid, p_run_id uuid, p_error text)
returns boolean language plpgsql security invoker set search_path = public, extensions
as $$
begin
  perform 1 from public.documents where id = p_document_id and user_id = p_user_id
    and status = 'processing' and processing_run_id = p_run_id for update;
  if not found then return false; end if;
  delete from public.chunks where document_id = p_document_id and user_id = p_user_id;
  update public.documents set status = 'failed', processing_error = left(p_error, 500),
    processing_stage = 'Processing failed', chunk_count = 0, processing_updated_at = now()
    where id = p_document_id;
  return true;
end;
$$;

-- Vector search: the API supplies the VERIFIED owner, never a browser user_id.
-- Exact cosine search within one owner's book avoids filtered ANN under-retrieval.
create or replace function public.phase2_search(
  p_user_id uuid, p_document_id uuid, p_query extensions.vector(256),
  p_model text, p_limit integer default 5)
returns table (id uuid, document_id uuid, content text, page_start integer,
  page_end integer, chunk_index integer, similarity double precision)
language sql stable security invoker set search_path = public, extensions
as $$
  with owned_chunks as materialized (
    select c.* from public.chunks c join public.documents d on d.id = c.document_id
    where c.user_id = p_user_id and c.document_id = p_document_id
      and d.user_id = p_user_id and d.status = 'ready'
      and d.embedding_model = p_model and c.embedding_model = p_model
      and c.processing_run_id = d.processing_run_id and c.embedding is not null
  )
  select c.id, c.document_id, c.content, c.page_start, c.page_end, c.chunk_index,
    (1 - (c.embedding <=> p_query))::double precision
  from owned_chunks c order by c.embedding <=> p_query, c.chunk_index
  limit greatest(1, least(p_limit, 10));
$$;

-- Ownership parameters are safe only on server-only RPCs. Keep existing RLS.
revoke all on function public.phase2_claim_next(uuid, text) from public, anon, authenticated;
revoke all on function public.phase2_progress(uuid, uuid, uuid, text) from public, anon, authenticated;
revoke all on function public.phase2_append_chunks(uuid, uuid, uuid, jsonb) from public, anon, authenticated;
revoke all on function public.phase2_finish(uuid, uuid, uuid, integer, integer) from public, anon, authenticated;
revoke all on function public.phase2_fail(uuid, uuid, uuid, text) from public, anon, authenticated;
revoke all on function public.phase2_search(uuid, uuid, extensions.vector, text, integer) from public, anon, authenticated;
grant execute on function public.phase2_claim_next(uuid, text) to service_role;
grant execute on function public.phase2_progress(uuid, uuid, uuid, text) to service_role;
grant execute on function public.phase2_append_chunks(uuid, uuid, uuid, jsonb) to service_role;
grant execute on function public.phase2_finish(uuid, uuid, uuid, integer, integer) to service_role;
grant execute on function public.phase2_fail(uuid, uuid, uuid, text) to service_role;
grant execute on function public.phase2_search(uuid, uuid, extensions.vector, text, integer) to service_role;

notify pgrst, 'reload schema';
commit;
