-- Phase 1 schema. Run this in the Supabase SQL Editor for the hosted project.
-- The backend uses a server-only secret key, but every request is scoped to a
-- user ID returned by Supabase Auth. Browser-facing reads are protected by RLS.

create extension if not exists vector with schema extensions;

create table if not exists public.users (
  id uuid primary key references auth.users (id) on delete cascade,
  auth_subject text not null unique,
  created_at timestamptz not null default now()
);

create or replace function public.handle_new_auth_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.users (id, auth_subject)
  values (new.id, new.id::text)
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_auth_user();

create table if not exists public.documents (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users (id) on delete cascade,
  filename text not null check (char_length(filename) between 1 and 180),
  storage_key text not null unique,
  status text not null default 'queued'
    check (status in ('queued', 'processing', 'ready', 'failed')),
  page_count integer check (page_count is null or page_count > 0),
  created_at timestamptz not null default now(),
  unique (user_id, id)
);

create table if not exists public.chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null,
  user_id uuid not null references public.users (id) on delete cascade,
  content text not null,
  embedding extensions.vector,
  page_start integer check (page_start is null or page_start > 0),
  page_end integer check (page_end is null or page_end > 0),
  chunk_index integer not null check (chunk_index >= 0),
  created_at timestamptz not null default now(),
  foreign key (user_id, document_id)
    references public.documents (user_id, id) on delete cascade,
  unique (document_id, chunk_index),
  check (page_start is null or page_end is null or page_end >= page_start)
);

create table if not exists public.conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users (id) on delete cascade,
  title text not null default 'New conversation',
  created_at timestamptz not null default now(),
  unique (user_id, id)
);

create table if not exists public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null,
  role text not null check (role in ('user', 'assistant')),
  content text not null,
  created_at timestamptz not null default now(),
  foreign key (conversation_id) references public.conversations (id) on delete cascade,
  unique (conversation_id, id)
);

create table if not exists public.message_citations (
  message_id uuid not null references public.messages (id) on delete cascade,
  chunk_id uuid not null references public.chunks (id) on delete cascade,
  rank integer not null check (rank > 0),
  primary key (message_id, chunk_id),
  unique (message_id, rank)
);

create index if not exists documents_user_created_idx
  on public.documents (user_id, created_at desc);
create index if not exists chunks_user_document_idx
  on public.chunks (user_id, document_id);
create index if not exists conversations_user_created_idx
  on public.conversations (user_id, created_at desc);
create index if not exists messages_conversation_created_idx
  on public.messages (conversation_id, created_at);
create index if not exists message_citations_chunk_idx
  on public.message_citations (chunk_id);

alter table public.users enable row level security;
alter table public.documents enable row level security;
alter table public.chunks enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;
alter table public.message_citations enable row level security;

-- Phase 1 browser clients only need owner-scoped reads. Writes go through FastAPI,
-- which verifies the access token and derives user_id from Supabase Auth.
drop policy if exists "users can read own profile" on public.users;
create policy "users can read own profile"
  on public.users for select to authenticated
  using ((select auth.uid()) = id);

drop policy if exists "users can read own documents" on public.documents;
create policy "users can read own documents"
  on public.documents for select to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "users can read own chunks" on public.chunks;
create policy "users can read own chunks"
  on public.chunks for select to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "users can read own conversations" on public.conversations;
create policy "users can read own conversations"
  on public.conversations for select to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "users can read own messages" on public.messages;
create policy "users can read own messages"
  on public.messages for select to authenticated
  using (
    exists (
      select 1 from public.conversations c
      where c.id = conversation_id and c.user_id = (select auth.uid())
    )
  );

drop policy if exists "users can read own message citations" on public.message_citations;
create policy "users can read own message citations"
  on public.message_citations for select to authenticated
  using (
    exists (
      select 1
      from public.messages m
      join public.conversations c on c.id = m.conversation_id
      join public.chunks k on k.id = chunk_id
      where m.id = message_id
        and c.user_id = (select auth.uid())
        and k.user_id = (select auth.uid())
    )
  );

-- Store books privately. No browser Storage policies are created: Phase 1 files
-- are uploaded and deleted only by the authenticated FastAPI backend.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('books-private', 'books-private', false, 6291456, array['application/pdf'])
on conflict (id) do update
set public = false,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;
