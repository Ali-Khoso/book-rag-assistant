-- Phase 3: grounded answers, immutable citation snapshots, and private history.
-- Run after 0003. Existing Phase 2 books and their indexes are retained.
begin;

-- Book metadata is evidence for title/author questions, not a filename guess.
alter table public.documents
  add column if not exists title text,
  add column if not exists author text,
  add column if not exists metadata_checked boolean not null default false;

alter table public.conversations
  add column if not exists document_id uuid references public.documents(id) on delete cascade,
  add column if not exists updated_at timestamptz not null default now(),
  add column if not exists active_request_id uuid,
  add column if not exists active_request_at timestamptz;
alter table public.messages
  add column if not exists sequence_number integer,
  add column if not exists answer_status text,
  add column if not exists answer_payload jsonb;
with numbered as (
  select id, row_number() over (partition by conversation_id order by created_at, id) as position
  from public.messages where sequence_number is null
)
update public.messages m set sequence_number = numbered.position
from numbered where m.id = numbered.id;
create unique index if not exists messages_conversation_sequence_idx
  on public.messages (conversation_id, sequence_number);
create index if not exists conversations_book_updated_idx
  on public.conversations (user_id, document_id, updated_at desc);

-- Reprocessing deletes old chunks. Preserve the source text/page snapshot so
-- old conversations remain verifiable; deleting a book still removes its chats.
alter table public.message_citations drop constraint if exists message_citations_pkey;
alter table public.message_citations add column if not exists id uuid not null default gen_random_uuid();
alter table public.message_citations add constraint message_citations_pkey primary key (id);
alter table public.message_citations alter column chunk_id drop not null;
alter table public.message_citations drop constraint if exists message_citations_chunk_id_fkey;
alter table public.message_citations add constraint message_citations_chunk_id_fkey
  foreign key (chunk_id) references public.chunks(id) on delete set null;
alter table public.message_citations
  add column if not exists document_id uuid references public.documents(id) on delete cascade,
  add column if not exists source_kind text,
  add column if not exists source_filename text,
  add column if not exists page_start integer,
  add column if not exists page_end integer,
  add column if not exists excerpt text,
  add column if not exists quote text;
update public.message_citations s set document_id = c.document_id,
  source_kind = 'passage', source_filename = d.filename,
  page_start = c.page_start, page_end = c.page_end, excerpt = c.content
from public.chunks c join public.documents d on d.id = c.document_id
where s.chunk_id = c.id and s.document_id is null;

drop policy if exists "users can read own message citations" on public.message_citations;
create policy "users can read own message citations" on public.message_citations
  for select to authenticated using (exists (
    select 1 from public.messages m
    join public.conversations v on v.id = m.conversation_id
    join public.documents d on d.id = message_citations.document_id
    where m.id = message_id and v.user_id = (select auth.uid())
      and d.user_id = (select auth.uid()) and v.document_id = d.id
  ));

-- Idempotency and a conversation lease prevent duplicate or interleaved turns.
create table if not exists public.chat_requests (
  id uuid primary key,
  user_id uuid not null references public.users(id) on delete cascade,
  document_id uuid not null references public.documents(id) on delete cascade,
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  processing_run_id uuid,
  question text not null,
  state text not null check (state in ('pending', 'completed', 'failed')),
  started_at timestamptz not null default now(),
  response jsonb
);
alter table public.chat_requests enable row level security;
-- No browser policies: requests are accessible only through the verified API.

create or replace function public.phase3_begin_turn(
  p_user_id uuid, p_document_id uuid, p_request_id uuid,
  p_question text, p_conversation_id uuid default null)
returns jsonb language plpgsql security invoker set search_path = public, extensions
as $$
declare book public.documents; request_row public.chat_requests;
  conversation public.conversations;
begin
  -- Serialize a request UUID across books before checking its owner/contents.
  -- Two simultaneous first attempts must not overwrite each other's request row.
  perform pg_advisory_xact_lock(hashtextextended(p_request_id::text, 0));
  select * into book from public.documents
    where id = p_document_id and user_id = p_user_id for update;
  if not found then raise exception 'book_not_found'; end if;
  if book.status <> 'ready' then raise exception 'book_not_ready'; end if;
  if length(trim(p_question)) < 1 or length(p_question) > 2000 then raise exception 'invalid_question'; end if;
  select * into request_row from public.chat_requests where id = p_request_id for update;
  if found then
    if request_row.user_id <> p_user_id or request_row.document_id <> p_document_id
       or request_row.question <> p_question
       or (p_conversation_id is not null and request_row.conversation_id <> p_conversation_id) then
      raise exception 'request_conflict';
    end if;
    if request_row.state = 'completed' then
      return jsonb_build_object('state', 'completed', 'response', request_row.response);
    end if;
    if request_row.state = 'pending' and request_row.started_at > now() - interval '5 minutes' then
      return jsonb_build_object('state', 'busy');
    end if;
    p_conversation_id := request_row.conversation_id;
  end if;
  if p_conversation_id is null then
    insert into public.conversations (user_id, document_id, title)
      values (p_user_id, p_document_id, left(p_question, 80)) returning * into conversation;
  else
    select * into conversation from public.conversations
      where id = p_conversation_id and user_id = p_user_id and document_id = p_document_id for update;
    if not found then raise exception 'conversation_not_found'; end if;
  end if;
  if conversation.active_request_id is not null
     and conversation.active_request_id <> p_request_id
     and conversation.active_request_at > now() - interval '5 minutes' then
    return jsonb_build_object('state', 'busy');
  end if;
  update public.conversations set active_request_id = p_request_id, active_request_at = now()
    where id = conversation.id;
  insert into public.chat_requests
    (id, user_id, document_id, conversation_id, processing_run_id, question, state)
  values (p_request_id, p_user_id, p_document_id, conversation.id, book.processing_run_id, p_question, 'pending')
  on conflict (id) do update set state = 'pending', started_at = now(), response = null,
    processing_run_id = excluded.processing_run_id;
  return jsonb_build_object('state', 'started', 'conversation_id', conversation.id,
    'processing_run_id', book.processing_run_id);
end;
$$;

-- Store both messages and independently verified source snapshots in one commit.
create or replace function public.phase3_finish_turn(
  p_user_id uuid, p_document_id uuid, p_request_id uuid,
  p_payload jsonb, p_sources jsonb)
returns jsonb language plpgsql security invoker set search_path = public, extensions
as $$
declare book public.documents; request_row public.chat_requests; conversation public.conversations;
  source jsonb; statement jsonb; reference jsonb; passage public.chunks;
  source_rank integer := 0; sources jsonb := '[]'::jsonb; source_quote text;
  normalized_quote text; source_excerpt text; source_kind text;
  source_chunk uuid; source_start integer; source_end integer;
  user_message uuid := gen_random_uuid(); answer_message uuid := gen_random_uuid();
  next_sequence integer; answer_data jsonb; result jsonb;
begin
  select * into book from public.documents
    where id = p_document_id and user_id = p_user_id for update;
  if not found then raise exception 'book_not_found'; end if;
  select * into request_row from public.chat_requests
    where id = p_request_id and user_id = p_user_id and document_id = p_document_id for update;
  if not found then raise exception 'request_not_found'; end if;
  if request_row.state = 'completed' then return request_row.response; end if;
  select * into conversation from public.conversations
    where id = request_row.conversation_id and user_id = p_user_id and document_id = p_document_id for update;
  if not found or request_row.state <> 'pending' or conversation.active_request_id is distinct from p_request_id then
    raise exception 'request_expired';
  end if;
  if book.status <> 'ready' or book.processing_run_id is distinct from request_row.processing_run_id then
    raise exception 'book_changed';
  end if;
  if jsonb_typeof(p_payload) is distinct from 'object'
     or jsonb_typeof(p_payload->'statements') is distinct from 'array'
     or jsonb_typeof(p_sources) is distinct from 'array' then
    raise exception 'invalid_answer';
  end if;
  if coalesce(p_payload->>'status', '') not in ('answered', 'insufficient_evidence')
     or coalesce(p_payload->>'method', '') not in ('metadata', 'model')
     or coalesce(length(p_payload->>'content'), 0) < 1
     or length(p_payload->>'content') > 15000 or jsonb_array_length(p_sources) > 15
     or jsonb_array_length(p_payload->'statements') > 4 then
    raise exception 'invalid_answer';
  end if;
  for source in select value from jsonb_array_elements(p_sources) loop
    source_rank := source_rank + 1;
    source_kind := source->>'source_kind'; source_quote := source->>'quote';
    normalized_quote := lower(regexp_replace(trim(source_quote), '\s+', ' ', 'g'));
    if source_kind = 'passage' then
      select * into passage from public.chunks where id = (source->>'chunk_id')::uuid
        and document_id = p_document_id and user_id = p_user_id
        and processing_run_id = book.processing_run_id;
      if not found or source_quote is null or length(normalized_quote) < 12 or length(normalized_quote) > 600
         or strpos(lower(regexp_replace(passage.content, '\s+', ' ', 'g')), normalized_quote) = 0 then
        raise exception 'invalid_source';
      end if;
      source_chunk := passage.id; source_start := passage.page_start;
      source_end := passage.page_end; source_excerpt := passage.content;
    elsif source_kind = 'metadata' then
      if source_quote is null or length(source_quote) < 1
         or (source_quote is distinct from book.title and source_quote is distinct from book.author) then
        raise exception 'invalid_source';
      end if;
      source_chunk := null; source_start := null; source_end := null;
      source_excerpt := concat_ws(E'\n', 'PDF title: ' || book.title, 'PDF author: ' || book.author);
    else raise exception 'invalid_source';
    end if;
    sources := sources || jsonb_build_array(jsonb_build_object(
      'rank', source_rank, 'source_kind', source_kind, 'chunk_id', source_chunk,
      'document_id', book.id, 'filename', book.filename, 'page_start', source_start,
      'page_end', source_end, 'excerpt', source_excerpt, 'quote', source_quote));
  end loop;
  if p_payload->>'status' = 'answered' and source_rank = 0 then raise exception 'invalid_source'; end if;
  if p_payload->>'status' = 'insufficient_evidence' and source_rank <> 0 then raise exception 'invalid_source'; end if;
  if (p_payload->>'status' = 'answered' and jsonb_array_length(p_payload->'statements') = 0)
     or (p_payload->>'status' = 'insufficient_evidence' and jsonb_array_length(p_payload->'statements') <> 0) then
    raise exception 'invalid_answer';
  end if;
  for statement in select value from jsonb_array_elements(p_payload->'statements') loop
    if jsonb_array_length(statement->'citation_ranks') < 1 then raise exception 'invalid_source'; end if;
    for reference in select value from jsonb_array_elements(statement->'citation_ranks') loop
      if reference::integer < 1 or reference::integer > source_rank then raise exception 'invalid_source'; end if;
    end loop;
  end loop;
  select coalesce(max(sequence_number), 0) + 1 into next_sequence
    from public.messages where conversation_id = conversation.id;
  answer_data := p_payload || jsonb_build_object('citations', sources);
  insert into public.messages (id, conversation_id, role, content, sequence_number)
    values (user_message, conversation.id, 'user', request_row.question, next_sequence);
  insert into public.messages (id, conversation_id, role, content, sequence_number, answer_status, answer_payload)
    values (answer_message, conversation.id, 'assistant', p_payload->>'content', next_sequence + 1,
      p_payload->>'status', answer_data);
  insert into public.message_citations
    (message_id, chunk_id, rank, document_id, source_kind, source_filename, page_start, page_end, excerpt, quote)
  select answer_message, (item->>'chunk_id')::uuid, (item->>'rank')::integer, book.id,
    item->>'source_kind', book.filename, (item->>'page_start')::integer,
    (item->>'page_end')::integer, item->>'excerpt', item->>'quote'
  from jsonb_array_elements(sources) item;
  update public.conversations set updated_at = now(), active_request_id = null, active_request_at = null
    where id = conversation.id;
  result := jsonb_build_object('conversation_id', conversation.id, 'request_id', p_request_id,
    'user_message_id', user_message, 'message_id', answer_message, 'document_id', book.id,
    'question', request_row.question, 'created_at', now(), 'answer', answer_data);
  update public.chat_requests set state = 'completed', response = result where id = p_request_id;
  return result;
end;
$$;

create or replace function public.phase3_abort_turn(p_user_id uuid, p_request_id uuid)
returns boolean language plpgsql security invoker set search_path = public, extensions
as $$
declare target uuid;
begin
  update public.chat_requests set state = 'failed' where id = p_request_id
    and user_id = p_user_id and state = 'pending' returning conversation_id into target;
  if not found then return false; end if;
  update public.conversations set active_request_id = null, active_request_at = null
    where id = target and user_id = p_user_id and active_request_id = p_request_id;
  return true;
end;
$$;

revoke all on function public.phase3_begin_turn(uuid, uuid, uuid, text, uuid) from public, anon, authenticated;
revoke all on function public.phase3_finish_turn(uuid, uuid, uuid, jsonb, jsonb) from public, anon, authenticated;
revoke all on function public.phase3_abort_turn(uuid, uuid) from public, anon, authenticated;
grant execute on function public.phase3_begin_turn(uuid, uuid, uuid, text, uuid) to service_role;
grant execute on function public.phase3_finish_turn(uuid, uuid, uuid, jsonb, jsonb) to service_role;
grant execute on function public.phase3_abort_turn(uuid, uuid) to service_role;
notify pgrst, 'reload schema';
commit;
