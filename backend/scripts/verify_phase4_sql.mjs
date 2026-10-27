// Execute actual operational SQL in isolated Postgres, without hosted credentials.
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
const require = createRequire(new URL('../.cache/phase3-sql/package.json', import.meta.url));
const { PGlite } = require('@electric-sql/pglite');
const { vector } = require('@electric-sql/pglite-pgvector');
const db = new PGlite({ extensions: { vector } });
const q = (sql, args = []) => db.query(sql, args);
const scalar = async (sql, args = []) => (await q(sql, args)).rows[0].value;
const a = randomUUID(), b = randomUUID(), legacy = randomUUID();
const rpc = (name, args) => scalar(`select public.${name}(${args.map((_, i) => '$' + (i + 1)).join(',')}) as value`, args);

try {
  await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
    create schema auth; create schema storage; create schema extensions;
    create table auth.users(id uuid primary key);
    create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
    create table storage.buckets(id text primary key,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);
    create table storage.objects(bucket_id text,name text,metadata jsonb);
    grant usage on schema public,auth,extensions to authenticated,anon,service_role;`);
  for (const name of ['0001_phase1_schema.sql','0002_increase_pdf_upload_limit.sql','0003_phase2_retrieval.sql','0004_phase3_answers.sql']) {
    await db.exec(await readFile(new URL('../../supabase/migrations/' + name, import.meta.url), 'utf8'));
  }
  await q('insert into auth.users values ($1),($2)', [a,b]);
  await q("insert into public.documents(id,user_id,filename,storage_key,status) values($1,$2,'legacy.pdf',$3,'ready')", [legacy,a,`${a}/${legacy}.pdf`]);
  await q("insert into storage.objects values('books-private',$1,'{\"size\":1234}')", [`${a}/${legacy}.pdf`]);
  const migration = await readFile(new URL('../../supabase/migrations/0005_phase4_operations.sql', import.meta.url), 'utf8');
  await db.exec(migration); await db.exec(migration);
  assert.equal(await scalar('select file_size_bytes::int as value from public.documents where id=$1',[legacy]),1234);
  console.log('PASS: migration 0005 applies and reruns; existing Storage bytes are backfilled.');

  const operation = randomUUID();
  assert.equal((await rpc('phase4_consume_usage',[a,'ask',2,1,operation])).allowed,true);
  assert.equal((await rpc('phase4_consume_usage',[a,'ask',2,1,operation])).allowed,true);
  let denied = await rpc('phase4_consume_usage',[a,'ask',2,1,operation]);
  assert.equal(denied.allowed,false); assert(denied.retry_after > 0 && denied.retry_after <= 60);
  await q("delete from public.usage_windows where period='minute'");
  denied = await rpc('phase4_consume_usage',[a,'ask',2,1,randomUUID()]);
  assert.equal(denied.allowed,false); assert(denied.retry_after > 60);
  assert.equal((await rpc('phase4_consume_usage',[b,'ask',2,1,operation])).allowed,true);
  console.log('PASS: minute/day limits persist, duplicate UUIDs avoid daily double charging, owners are isolated.');

  const book = randomUUID();
  const reservation = (await q('select * from public.phase4_reserve_upload($1,$2,$3,$4,$5,$6,$7)',[a,book,'pending.pdf',1000,2,3000,3])).rows[0];
  assert.equal(reservation.upload_completed,false);
  await assert.rejects(rpc('phase4_reserve_upload',[a,randomUUID(),'excess.pdf',1,2,99999,3]),/book_quota_exceeded/);
  await assert.rejects(rpc('phase4_reserve_upload',[b,randomUUID(),'large.pdf',3001,20,3000,3]),/storage_quota_exceeded/);
  assert.equal((await q("select * from public.phase4_claim_next($1,'test-model')",[randomUUID()])).rows.length,0);
  assert.equal(await rpc('phase4_complete_upload',[a,book]),true);
  let run = randomUUID();
  let claimed = (await q("select * from public.phase4_claim_next($1,'test-model')",[run])).rows[0];
  assert.equal(claimed.id,book); assert.equal(claimed.processing_attempts,1);
  assert.equal(await rpc('phase4_record_failure',[book,a,run,'Temporary outage',true]),true);
  assert.equal(await scalar('select status as value from public.documents where id=$1',[book]),'queued');
  assert.equal((await q("select * from public.phase4_claim_next($1,'test-model')",[randomUUID()])).rows.length,0);
  await q("update public.documents set processing_next_attempt_at=now()-interval '1 second' where id=$1",[book]);
  run = randomUUID(); claimed = (await q("select * from public.phase4_claim_next($1,'test-model')",[run])).rows[0];
  assert.equal(claimed.processing_attempts,2);
  await rpc('phase4_record_failure',[book,a,run,'Invalid PDF',false]);
  assert.equal(await scalar('select status as value from public.documents where id=$1',[book]),'failed');
  await rpc('phase4_queue_retry',[a,book]);
  run = randomUUID(); await q("select * from public.phase4_claim_next($1,'test-model')",[run]);
  await q("update public.documents set processing_attempts=processing_max_attempts,processing_updated_at=now()-interval '16 minutes' where id=$1",[book]);
  assert.equal((await q("select * from public.phase4_claim_next($1,'test-model')",[randomUUID()])).rows.length,0);
  assert.equal(await scalar('select status as value from public.documents where id=$1',[book]),'failed');
  console.log('PASS: reservations cannot be processed early; transient backoff, permanent failure, and crashed-attempt limits work.');

  const activeRun=randomUUID(), chunk=randomUUID();
  await q("update public.documents set status='ready',processing_run_id=$2,page_count=2,embedding_model='test-model' where id=$1",[book,activeRun]);
  const text='Jupiter is the largest planet in our solar system.';
  await q("insert into public.chunks(id,document_id,user_id,content,page_start,page_end,chunk_index,processing_run_id,embedding_model,embedding) values($1,$2,$3,$4,1,1,0,$5,'test-model',$6::extensions.vector)",[chunk,book,a,text,activeRun,JSON.stringify([1,...Array(255).fill(0)])]);
  const request=randomUUID();
  const claim=await rpc('phase4_begin_turn',[a,book,request,'Which planet?',null,1]);
  assert.equal((await rpc('phase4_begin_turn',[a,legacy,randomUUID(),'Concurrent?',null,1])).state,'busy');
  const payload={status:'answered',method:'model',content:text+' [1]',statements:[{text,citation_ranks:[1]}]};
  const answer=await rpc('phase3_finish_turn',[a,book,request,JSON.stringify(payload),JSON.stringify([{source_kind:'passage',chunk_id:chunk,quote:text}])]);
  assert.equal(answer.answer.citations[0].page_start,1);
  assert.equal(await rpc('phase4_request_deletion',[b,book]),false);
  assert.equal(await rpc('phase4_request_deletion',[a,book]),true);
  await db.exec('grant select on all tables in schema public to authenticated; set role authenticated;');
  await q("select set_config('request.jwt.claim.sub',$1,false)",[a]);
  assert.equal((await q('select id from public.documents where id=$1',[book])).rows.length,0);
  assert.equal((await q('select id from public.chunks where document_id=$1',[book])).rows.length,0);
  assert.equal((await q('select id from public.conversations where document_id=$1',[book])).rows.length,0);
  assert.equal((await q('select id from public.messages where conversation_id=$1',[claim.conversation_id])).rows.length,0);
  assert.equal((await q('select id from public.message_citations where document_id=$1',[book])).rows.length,0);
  for(const table of ['usage_windows','usage_operations','worker_heartbeats']) assert.equal((await q(`select * from public.${table}`)).rows.length,0);
  await assert.rejects(rpc('phase4_consume_usage',[a,'ask',2,1,randomUUID()]),/permission denied/);
  await db.exec('reset role;');
  console.log('PASS: per-owner inference concurrency; deletion immediately hides the book, chunks, chats, and citations through RLS.');

  let deletion=randomUUID();
  let cleanup=(await q('select * from public.phase4_claim_deletion($1,2)',[deletion])).rows[0];
  assert.equal(cleanup.id,book);
  assert.equal((await q('select * from public.phase4_claim_deletion($1,2)',[randomUUID()])).rows.length,0);
  await rpc('phase4_fail_deletion',[a,book,deletion,2]);
  await q("update public.documents set deletion_next_attempt_at=now()-interval '1 second' where id=$1",[book]);
  deletion=randomUUID(); await q('select * from public.phase4_claim_deletion($1,2)',[deletion]);
  await rpc('phase4_fail_deletion',[a,book,deletion,2]);
  assert.equal((await rpc('phase4_health',[])).cleanup_blocked,1);
  assert.equal(await scalar('select count(*)::int as value from public.documents where id=$1',[book]),1);
  await q('update public.documents set deletion_attempts=0,deletion_next_attempt_at=now() where id=$1',[book]);
  deletion=randomUUID(); await q('select * from public.phase4_claim_deletion($1,2)',[deletion]);
  assert.equal(await rpc('phase4_finish_deletion',[a,book,randomUUID()]),false);
  assert.equal(await rpc('phase4_finish_deletion',[a,book,deletion]),true);
  for(const [table,column,id] of [['chunks','document_id',book],['conversations','document_id',book],['messages','conversation_id',claim.conversation_id],['message_citations','document_id',book],['chat_requests','document_id',book]]) {
    assert.equal((await q(`select * from public.${table} where ${column}=$1`,[id])).rows.length,0);
  }
  console.log('PASS: cleanup leases, bounded retries, blocked-cleanup metrics, operator recovery, and cascading purge.');

  const abandoned=randomUUID(); await rpc('phase4_reserve_upload',[b,abandoned,'abandoned.pdf',100,20,10000,3]);
  await q("update public.documents set created_at=now()-interval '16 minutes' where id=$1",[abandoned]);
  const recovered=(await q('select * from public.phase4_claim_deletion($1,8)',[randomUUID()])).rows[0];
  assert.equal(recovered.id,abandoned);
  assert.equal((await rpc('phase4_health',[])).worker,false);
  await rpc('phase4_heartbeat',[randomUUID(),'idle']);
  assert.equal((await rpc('phase4_health',[])).worker,true);
  await q("update public.worker_heartbeats set seen_at=now()-interval '1 minute'");
  assert.equal((await rpc('phase4_health',[])).worker,false);
  await rpc('phase4_housekeeping',[]);
  console.log('PASS: abandoned uploads become cleanup jobs; readiness distinguishes fresh and expired worker heartbeats.');
} finally { await db.close(); }
