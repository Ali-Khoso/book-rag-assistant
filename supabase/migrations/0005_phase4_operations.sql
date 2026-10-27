-- Phase 4: durable limits, bounded ingestion retries, and deletion recovery.
-- Run after 0004. Operational tables/RPCs are backend-only.
begin;

alter table public.documents drop constraint if exists documents_status_check;
alter table public.documents add constraint documents_status_check
  check (status in ('queued', 'processing', 'ready', 'failed', 'deleting'));
alter table public.documents
  add column if not exists file_size_bytes bigint not null default 0 check (file_size_bytes >= 0),
  add column if not exists upload_completed boolean not null default true,
  add column if not exists processing_attempts integer not null default 0,
  add column if not exists processing_max_attempts integer not null default 3,
  add column if not exists processing_next_attempt_at timestamptz default now(),
  add column if not exists delete_requested_at timestamptz,
  add column if not exists deletion_attempts integer not null default 0,
  add column if not exists deletion_next_attempt_at timestamptz,
  add column if not exists deletion_claim_id uuid,
  add column if not exists deletion_claimed_at timestamptz,
  add column if not exists deletion_error text;

-- Include already uploaded files in storage quotas when Storage metadata exists.
do $$ begin
  if to_regclass('storage.objects') is not null then
    update public.documents d set file_size_bytes = (o.metadata->>'size')::bigint
    from storage.objects o
    where o.bucket_id = 'books-private' and o.name = d.storage_key and d.file_size_bytes = 0
      and o.metadata->>'size' ~ '^[0-9]{1,18}$';
  end if;
end $$;

create index if not exists documents_due_retry_idx on public.documents (processing_next_attempt_at)
  where status = 'queued';
create index if not exists documents_due_deletion_idx on public.documents (deletion_next_attempt_at)
  where status = 'deleting';

create table if not exists public.usage_windows (
  user_id uuid not null references public.users(id) on delete cascade,
  action text not null,
  period text not null check (period in ('minute', 'day')),
  window_start timestamptz not null,
  request_count integer not null default 0,
  primary key (user_id, action, period, window_start)
);
create table if not exists public.usage_operations (
  user_id uuid not null references public.users(id) on delete cascade,
  action text not null,
  operation_id uuid not null,
  created_at timestamptz not null default now(),
  primary key (user_id, action, operation_id)
);
create table if not exists public.worker_heartbeats (
  id uuid primary key,
  state text not null check (state in ('idle', 'processing', 'waiting_for_database', 'stopped')),
  seen_at timestamptz not null default now()
);
alter table public.usage_windows enable row level security;
alter table public.usage_operations enable row level security;
alter table public.worker_heartbeats enable row level security;
grant all on public.usage_windows,public.usage_operations,public.worker_heartbeats to service_role;

-- A pending deletion becomes inaccessible immediately, even if Storage is down.
drop policy if exists "users can read own documents" on public.documents;
create policy "users can read own documents" on public.documents for select to authenticated
  using (user_id = (select auth.uid()) and status <> 'deleting');
drop policy if exists "users can read own chunks" on public.chunks;
create policy "users can read own chunks" on public.chunks for select to authenticated
  using (user_id = (select auth.uid()) and exists (
    select 1 from public.documents d where d.id = document_id and d.user_id = (select auth.uid()) and d.status <> 'deleting'));
drop policy if exists "users can read own conversations" on public.conversations;
create policy "users can read own conversations" on public.conversations for select to authenticated
  using (user_id = (select auth.uid()) and exists (
    select 1 from public.documents d where d.id = document_id and d.user_id = (select auth.uid()) and d.status <> 'deleting'));

-- Limits are shared by every API instance. Retries use the minute budget but
-- repeated operation UUIDs do not consume the daily budget again.
create or replace function public.phase4_consume_usage(
  p_user_id uuid, p_action text, p_minute_limit integer, p_daily_limit integer,
  p_operation_id uuid default null)
returns jsonb language plpgsql security invoker set search_path = public, extensions as $$
declare minute_start timestamptz := date_trunc('minute', now());
  day_start timestamptz := date_trunc('day', now() at time zone 'UTC') at time zone 'UTC';
  minute_count integer; day_count integer; repeated boolean := false;
begin
  if p_action not in ('read','upload','search','ask','retry','delete')
     or p_minute_limit < 1 or p_daily_limit < 1 then raise exception 'invalid_limit'; end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || ':' || p_action, 40));
  select coalesce(max(request_count),0) into minute_count from public.usage_windows
    where user_id=p_user_id and action=p_action and period='minute' and window_start=minute_start;
  select coalesce(max(request_count),0) into day_count from public.usage_windows
    where user_id=p_user_id and action=p_action and period='day' and window_start=day_start;
  if p_operation_id is not null then
    repeated := exists(select 1 from public.usage_operations where user_id=p_user_id
      and action=p_action and operation_id=p_operation_id and created_at >= day_start);
  end if;
  if minute_count >= p_minute_limit then
    return jsonb_build_object('allowed',false,'retry_after',greatest(1,ceil(extract(epoch from minute_start+interval '1 minute'-now()))::integer));
  end if;
  if not repeated and day_count >= p_daily_limit then
    return jsonb_build_object('allowed',false,'retry_after',greatest(1,ceil(extract(epoch from day_start+interval '1 day'-now()))::integer));
  end if;
  insert into public.usage_windows values(p_user_id,p_action,'minute',minute_start,1)
    on conflict(user_id,action,period,window_start) do update set request_count=usage_windows.request_count+1;
  if not repeated then
    insert into public.usage_windows values(p_user_id,p_action,'day',day_start,1)
      on conflict(user_id,action,period,window_start) do update set request_count=usage_windows.request_count+1;
    if p_operation_id is not null then
      insert into public.usage_operations(user_id,action,operation_id) values(p_user_id,p_action,p_operation_id)
        on conflict(user_id,action,operation_id) do update set created_at=now();
    end if;
  end if;
  return jsonb_build_object('allowed',true,'retry_after',0);
end $$;

-- Reserve a quota slot before uploading. Incomplete reservations cannot be
-- processed; the cleanup worker recovers abandoned uploads after 15 minutes.
create or replace function public.phase4_reserve_upload(
  p_user_id uuid,p_document_id uuid,p_filename text,p_size bigint,
  p_max_books integer,p_max_bytes bigint,p_max_attempts integer)
returns setof public.documents language plpgsql security invoker set search_path = public, extensions as $$
declare book_count integer; stored_bytes bigint;
begin
  if p_size < 1 or p_max_books < 1 or p_max_bytes < 1 or p_max_attempts not between 1 and 10 then
    raise exception 'invalid_reservation'; end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text,41));
  select count(*),coalesce(sum(file_size_bytes),0) into book_count,stored_bytes
    from public.documents where user_id=p_user_id;
  if book_count >= p_max_books then raise exception 'book_quota_exceeded'; end if;
  if stored_bytes+p_size > p_max_bytes then raise exception 'storage_quota_exceeded'; end if;
  return query insert into public.documents(id,user_id,filename,storage_key,status,file_size_bytes,
      upload_completed,processing_max_attempts)
    values(p_document_id,p_user_id,left(p_filename,180),p_user_id::text || '/' || p_document_id::text || '.pdf',
      'queued',p_size,false,p_max_attempts) returning *;
end $$;

create or replace function public.phase4_complete_upload(p_user_id uuid,p_document_id uuid)
returns boolean language plpgsql security invoker set search_path = public, extensions as $$
begin
  update public.documents set upload_completed=true,processing_next_attempt_at=now()
    where id=p_document_id and user_id=p_user_id and status='queued' and not upload_completed;
  return found;
end $$;

create or replace function public.phase4_queue_retry(p_user_id uuid,p_document_id uuid)
returns setof public.documents language plpgsql security invoker set search_path = public, extensions as $$
begin
  return query update public.documents set status='queued',processing_error=null,
    processing_stage='Waiting to process',processing_run_id=null,chunk_count=0,
    processing_attempts=0,processing_next_attempt_at=now()
    where id=p_document_id and user_id=p_user_id and status in ('failed','ready') and upload_completed returning *;
end $$;

create or replace function public.phase4_claim_next(p_run_id uuid,p_model text)
returns setof public.documents language plpgsql security invoker set search_path = public, extensions as $$
declare target public.documents;
begin
  -- Crashed jobs also have a finite attempt budget.
  for target in select * from public.documents
    where status='processing' and coalesce(processing_updated_at,created_at) < now()-interval '15 minutes'
      and processing_attempts >= processing_max_attempts for update skip locked loop
    delete from public.chunks where document_id=target.id and user_id=target.user_id;
    update public.documents set status='failed',chunk_count=0,processing_stage='Processing failed',
      processing_error='Processing stopped too many times. Use Retry to start a fresh attempt.' where id=target.id;
  end loop;
  select * into target from public.documents where upload_completed and processing_attempts < processing_max_attempts
    and ((status='queued' and processing_next_attempt_at <= now())
      or (status='processing' and coalesce(processing_updated_at,created_at) < now()-interval '15 minutes'))
    order by created_at for update skip locked limit 1;
  if not found then return; end if;
  delete from public.chunks where document_id=target.id and user_id=target.user_id;
  update public.documents set status='processing',processing_run_id=p_run_id,processing_attempts=processing_attempts+1,
    processing_error=null,processing_stage='Reading PDF',processing_updated_at=now(),processed_at=null,
    chunk_count=0,page_count=null,embedding_model=p_model,processing_next_attempt_at=null
    where id=target.id returning * into target;
  return next target;
end $$;

-- Keep older application instances from claiming incomplete reservations.
create or replace function public.phase2_claim_next(p_run_id uuid,p_model text)
returns setof public.documents language sql security invoker set search_path = public, extensions as $$
  select * from public.phase4_claim_next(p_run_id,p_model);
$$;

create or replace function public.phase4_record_failure(
  p_document_id uuid,p_user_id uuid,p_run_id uuid,p_error text,p_retryable boolean)
returns boolean language plpgsql security invoker set search_path = public, extensions as $$
declare target public.documents; retry boolean;
begin
  select * into target from public.documents where id=p_document_id and user_id=p_user_id
    and status='processing' and processing_run_id=p_run_id for update;
  if not found then return false; end if;
  delete from public.chunks where document_id=p_document_id and user_id=p_user_id;
  retry := p_retryable and target.processing_attempts < target.processing_max_attempts;
  update public.documents set status=case when retry then 'queued' else 'failed' end,
    processing_error=left(p_error,500),processing_stage=case when retry then 'Retry scheduled' else 'Processing failed' end,
    chunk_count=0,processing_updated_at=now(),processing_run_id=null,
    processing_next_attempt_at=case when retry then now()+make_interval(secs=>least(300,power(2,target.processing_attempts)::integer*5)) else null end
    where id=p_document_id;
  return true;
end $$;

create or replace function public.phase4_request_deletion(p_user_id uuid,p_document_id uuid)
returns boolean language plpgsql security invoker set search_path = public, extensions as $$
begin
  update public.documents set status='deleting',delete_requested_at=coalesce(delete_requested_at,now()),
    processing_run_id=null,deletion_next_attempt_at=now(),deletion_error=null
    where id=p_document_id and user_id=p_user_id;
  return found;
end $$;

create or replace function public.phase4_claim_deletion(p_claim_id uuid,p_max_attempts integer default 8)
returns setof public.documents language plpgsql security invoker set search_path = public, extensions as $$
declare target public.documents;
begin
  -- Upload crashes are handled through the same durable deletion path.
  update public.documents set status='deleting',delete_requested_at=now(),deletion_next_attempt_at=now()
    where not upload_completed and status='queued' and created_at < now()-interval '15 minutes';
  update public.documents set deletion_claim_id=null,deletion_claimed_at=null,deletion_next_attempt_at=null,
    deletion_error='Private file cleanup stopped repeatedly. An operator must retry cleanup.'
    where status='deleting' and deletion_attempts >= p_max_attempts
      and deletion_claim_id is not null and deletion_claimed_at < now()-interval '5 minutes';
  select * into target from public.documents where status='deleting' and deletion_attempts < p_max_attempts
    and deletion_next_attempt_at <= now()
    and (deletion_claim_id is null or deletion_claimed_at < now()-interval '5 minutes')
    order by delete_requested_at for update skip locked limit 1;
  if not found then return; end if;
  update public.documents set deletion_claim_id=p_claim_id,deletion_claimed_at=now(),deletion_attempts=deletion_attempts+1
    where id=target.id returning * into target;
  return next target;
end $$;

create or replace function public.phase4_finish_deletion(p_user_id uuid,p_document_id uuid,p_claim_id uuid)
returns boolean language plpgsql security invoker set search_path = public, extensions as $$
begin
  delete from public.documents where id=p_document_id and user_id=p_user_id
    and status='deleting' and deletion_claim_id=p_claim_id;
  return found;
end $$;

create or replace function public.phase4_fail_deletion(p_user_id uuid,p_document_id uuid,p_claim_id uuid,p_max_attempts integer default 8)
returns boolean language plpgsql security invoker set search_path = public, extensions as $$
begin
  update public.documents set deletion_error='Private file cleanup will be retried. An operator must check repeated failures.',
    deletion_claim_id=null,deletion_claimed_at=null,
    deletion_next_attempt_at=case when deletion_attempts < p_max_attempts
      then now()+make_interval(secs=>least(3600,power(2,least(deletion_attempts,10))::integer*10)) else null end
    where id=p_document_id and user_id=p_user_id and status='deleting' and deletion_claim_id=p_claim_id;
  return found;
end $$;

create or replace function public.phase4_begin_turn(p_user_id uuid,p_document_id uuid,p_request_id uuid,
  p_question text,p_conversation_id uuid default null,p_concurrent_limit integer default 1)
returns jsonb language plpgsql security invoker set search_path = public, extensions as $$
begin
  if p_concurrent_limit not between 1 and 10 then raise exception 'invalid_limit'; end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text,42));
  if (select count(*) from public.chat_requests where user_id=p_user_id and state='pending'
      and started_at > now()-interval '5 minutes' and id <> p_request_id) >= p_concurrent_limit then
    return jsonb_build_object('state','busy');
  end if;
  return public.phase3_begin_turn(p_user_id,p_document_id,p_request_id,p_question,p_conversation_id);
end $$;

create or replace function public.phase4_heartbeat(p_worker_id uuid,p_state text)
returns boolean language plpgsql security invoker set search_path = public, extensions as $$
begin
  insert into public.worker_heartbeats(id,state,seen_at) values(p_worker_id,p_state,now())
    on conflict(id) do update set state=excluded.state,seen_at=now();
  return true;
end $$;

create or replace function public.phase4_health()
returns jsonb language sql security invoker set search_path = public, extensions as $$
  select jsonb_build_object('database',true,'worker',exists(select 1 from public.worker_heartbeats
    where seen_at > now()-interval '45 seconds' and state in ('idle','processing')),
    'queued',(select count(*) from public.documents where status='queued'),
    'failed',(select count(*) from public.documents where status='failed'),
    'cleanup_pending',(select count(*) from public.documents where status='deleting'),
    'cleanup_blocked',(select count(*) from public.documents where status='deleting' and deletion_next_attempt_at is null));
$$;

create or replace function public.phase4_housekeeping()
returns boolean language plpgsql security invoker set search_path = public, extensions as $$
begin
  delete from public.usage_windows where window_start < now()-interval '2 days';
  delete from public.usage_operations where created_at < now()-interval '2 days';
  delete from public.worker_heartbeats where seen_at < now()-interval '2 days';
  return true;
end $$;

-- Every new RPC is service-only, including monitoring and quota maintenance.
do $$ declare fn record; begin
  for fn in select p.oid::regprocedure as signature from pg_proc p
    join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.proname like 'phase4\_%' escape '\' loop
    execute format('revoke all on function %s from public, anon, authenticated',fn.signature);
    execute format('grant execute on function %s to service_role',fn.signature);
  end loop;
end $$;
revoke all on function public.phase2_claim_next(uuid,text) from public, anon, authenticated;
grant execute on function public.phase2_claim_next(uuid,text) to service_role;
notify pgrst, 'reload schema';
commit;
