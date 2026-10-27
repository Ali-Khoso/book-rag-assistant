// Database behavior checks in isolated Postgres/WASM, without hosted credentials.
// Supabase Auth/Storage schemas are minimal fixtures; live checks remain separate.
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";

const require = createRequire(new URL("../.cache/phase3-sql/package.json", import.meta.url));
const { PGlite } = require("@electric-sql/pglite");
const { vector } = require("@electric-sql/pglite-pgvector");
const db = new PGlite({ extensions: { vector } });
const query = (sql, params = []) => db.query(sql, params);
const scalar = async (sql, params = []) => (await query(sql, params)).rows[0].value;
const owner = randomUUID(), other = randomUUID(), book = randomUUID(), otherBook = randomUUID();
const run = randomUUID(), chunk = randomUUID(), foreign = randomUUID();
const quote = "Plants release oxygen as a byproduct.";
const payload = { status: "answered", method: "model", content: quote + " [1]", statements: [{ text: quote, citation_ranks: [1] }] };
const begin = (request, question, conversation = null, user = owner, document = book) => scalar(
  "select public.phase3_begin_turn($1::uuid,$2::uuid,$3::uuid,$4,$5::uuid) as value", [user, document, request, question, conversation]);
const finish = (request, source, answer = payload) => scalar(
  "select public.phase3_finish_turn($1::uuid,$2::uuid,$3::uuid,$4::jsonb,$5::jsonb) as value", [owner, book, request, JSON.stringify(answer), JSON.stringify([source])]);
const abort = (request) => scalar("select public.phase3_abort_turn($1::uuid,$2::uuid) as value", [owner, request]);

try {
  await db.exec(`
    create role anon; create role authenticated; create role service_role bypassrls;
    create schema auth; create schema storage; create schema extensions;
    create table auth.users (id uuid primary key);
    create function auth.uid() returns uuid language sql stable as
      $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
    create table storage.buckets (id text primary key, name text, public boolean,
      file_size_limit bigint, allowed_mime_types text[]);
    grant usage on schema public, auth, extensions to anon, authenticated, service_role;
  `);
  const migrations = ["0001_phase1_schema.sql", "0002_increase_pdf_upload_limit.sql", "0003_phase2_retrieval.sql", "0004_phase3_answers.sql"];
  for (const name of migrations) {
    await db.exec(await readFile(new URL("../../supabase/migrations/" + name, import.meta.url), "utf8"));
  }
  await db.exec(await readFile(new URL("../../supabase/migrations/0004_phase3_answers.sql", import.meta.url), "utf8"));
  console.log("PASS: migrations 0001–0004 apply; Phase 3 migration reruns safely.");
  await query("insert into auth.users (id) values ($1::uuid),($2::uuid)", [owner, other]);
  for (const [document, user] of [[book, owner], [otherBook, other]]) {
    await query("insert into public.documents (id,user_id,filename,storage_key,status,page_count,chunk_count,embedding_model,processing_run_id,title,author,metadata_checked) values ($1::uuid,$2::uuid,'book.pdf',$3,'ready',3,1,'test-model',$4::uuid,'Field Notes','Ada Reader',true)", [document, user, `${user}/${document}.pdf`, run]);
  }
  for (const [id, document, user] of [[chunk, book, owner], [foreign, otherBook, other]]) {
    await query("insert into public.chunks (id,document_id,user_id,content,page_start,page_end,chunk_index,processing_run_id,embedding_model,embedding) values ($1::uuid,$2::uuid,$3::uuid,$4,3,3,0,$5::uuid,'test-model',$6::extensions.vector)", [id, document, user, quote, run, JSON.stringify([1, ...Array(255).fill(0)])]);
  }
  const request = randomUUID();
  const claim = await begin(request, "Which gas?");
  assert.equal(claim.state, "started");
  const source = { source_kind: "passage", chunk_id: chunk, quote };
  const response = await finish(request, source);
  assert.equal(response.answer.citations[0].page_start, 3);
  assert.equal(response.answer.citations[0].excerpt, quote);
  assert.deepEqual((await begin(request, "Which gas?")).response, response);
  assert.equal(await scalar("select count(*)::int as value from public.messages"), 2);
  await assert.rejects(begin(request, "Which gas?", null, other, otherBook), /request_conflict/);
  console.log("PASS: atomic turn, stored page provenance, exact idempotency, and foreign request reuse denial.");

  for (const badSource of [{ ...source, chunk_id: foreign }, { ...source, quote: "This is a made-up quotation." }]) {
    const id = randomUUID(); await begin(id, "Reject bad source", claim.conversation_id);
    await assert.rejects(finish(id, badSource), /invalid_source/);
    await abort(id);
  }
  const metadataId = randomUUID(); await begin(metadataId, "What is the title?", claim.conversation_id);
  const metadata = await finish(metadataId, { source_kind: "metadata", chunk_id: null, quote: "Field Notes" },
    { status: "answered", method: "metadata", content: "The title is Field Notes. [1]", statements: [{ text: "The title is Field Notes.", citation_ranks: [1] }] });
  assert.equal(metadata.answer.citations[0].page_start, null);
  assert.equal(metadata.answer.citations[0].source_kind, "metadata");
  console.log("PASS: foreign/fabricated citations rejected; metadata citations have no invented page.");

  const pending = randomUUID(); await begin(pending, "In progress", claim.conversation_id);
  assert.equal((await begin(randomUUID(), "Concurrent question", claim.conversation_id)).state, "busy");
  await abort(pending);
  const changed = randomUUID(); await begin(changed, "Generation changed", claim.conversation_id);
  await query("update public.documents set processing_run_id=$1::uuid where id=$2::uuid", [randomUUID(), book]);
  await assert.rejects(finish(changed, source), /book_changed/);
  await abort(changed);
  await query("update public.documents set processing_run_id=$1::uuid where id=$2::uuid", [run, book]);
  console.log("PASS: concurrent conversation lease and changed-index answer rejection.");

  await db.exec("grant select on all tables in schema public to authenticated; set role authenticated;");
  await query("select set_config('request.jwt.claim.sub',$1,false)", [other]);
  for (const table of ["conversations", "messages", "message_citations", "chat_requests"]) {
    assert.equal((await query(`select * from public.${table}`)).rows.length, 0);
  }
  await assert.rejects(begin(randomUUID(), "Forged owner"), /permission denied/);
  await db.exec("reset role;");
  console.log("PASS: second-user RLS and browser execution denial for privileged chat RPCs.");

  await query("delete from public.chunks where document_id=$1::uuid", [book]);
  const snapshot = (await query("select chunk_id,excerpt,page_start from public.message_citations where message_id=$1::uuid", [response.message_id])).rows[0];
  assert.equal(snapshot.chunk_id, null); assert.equal(snapshot.excerpt, quote); assert.equal(snapshot.page_start, 3);
  await db.exec("set role authenticated;"); await query("select set_config('request.jwt.claim.sub',$1,false)", [owner]);
  assert.equal((await query("select * from public.message_citations")).rows.length, 2);
  await db.exec("reset role;");
  await query("delete from public.documents where id=$1::uuid", [book]);
  for (const table of ["conversations", "messages", "message_citations", "chat_requests"]) {
    assert.equal((await query(`select * from public.${table}`)).rows.length, 0);
  }
  console.log("PASS: reprocessing retains readable source snapshots; book deletion cascades to all chat records.");
} finally {
  await db.close();
}
