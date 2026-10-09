-- Isolated server ACK ledger; load receiver and budget fixtures first.
create schema capture_checkpoint;
revoke all on schema capture_checkpoint from public,anon,authenticated;
create table capture_checkpoint.pages (
  owner_scope text not null, run_id uuid not null, sequence integer not null check(sequence between 1 and 1000),
  page_id uuid not null, manifest_hash text not null check(manifest_hash ~ '^[a-f0-9]{64}$'),
  previous_page_hash text, cursor_ref text, reported_coverage text not null check(reported_coverage in ('complete','partial')),
  manifest jsonb not null, received_at timestamptz not null default clock_timestamp(),
  primary key(owner_scope,run_id,sequence),unique(owner_scope,run_id,page_id),
  foreign key(owner_scope,run_id) references capture_budget.runs,
  check((sequence=1 and previous_page_hash is null) or (sequence>1 and previous_page_hash ~ '^[a-f0-9]{64}$'))
);
create table capture_checkpoint.items (
  owner_scope text not null,run_id uuid not null,sequence integer not null,item_index integer not null check(item_index between 0 and 19),
  capture_id uuid,envelope_hash text,item_ref text,error_code text,
  primary key(owner_scope,run_id,sequence,item_index),unique(owner_scope,run_id,capture_id),
  foreign key(owner_scope,run_id,sequence) references capture_checkpoint.pages,
  check((capture_id is not null and envelope_hash ~ '^[a-f0-9]{64}$' and item_ref is null and error_code is null)
    or(capture_id is null and envelope_hash is null and item_ref is not null and error_code is not null))
);
create table capture_checkpoint.watermarks (
  owner_scope text not null,run_id uuid not null,binding_hash text not null,
  acknowledged_sequence integer not null default 0,cursor_ref text,last_page_hash text,
  reported_coverage text not null,blocked_reason text,updated_at timestamptz not null default clock_timestamp(),
  primary key(owner_scope,run_id),foreign key(owner_scope,run_id) references capture_budget.runs
);
create table capture_checkpoint.recovery_grants (
  grant_id uuid primary key,owner_scope text not null,actor_ref text not null,
  source_run_id uuid not null,target_run_id uuid not null,
  source_binding_hash text not null check(source_binding_hash ~ '^[a-f0-9]{64}$'),
  target_binding_hash text not null check(target_binding_hash ~ '^[a-f0-9]{64}$'),
  issued_at timestamptz not null default clock_timestamp(),expires_at timestamptz not null,revoked boolean not null default false,
  foreign key(owner_scope,actor_ref) references capture_receiver.actors,
  foreign key(owner_scope,source_run_id) references capture_budget.runs,
  foreign key(owner_scope,target_run_id) references capture_budget.runs,
  check(source_run_id<>target_run_id and expires_at>issued_at)
);
create function capture_checkpoint.freeze_record() returns trigger
language plpgsql security invoker set search_path=pg_catalog as $$
begin
  if tg_table_name='recovery_grants' and tg_op='UPDATE' and to_jsonb(new)-'revoked'=to_jsonb(old)-'revoked' then return new; end if;
  raise exception 'immutable_checkpoint_record';
end; $$;
create trigger freeze_page before update or delete on capture_checkpoint.pages for each row execute function capture_checkpoint.freeze_record();
create trigger freeze_item before update or delete on capture_checkpoint.items for each row execute function capture_checkpoint.freeze_record();
create trigger freeze_grant before update or delete on capture_checkpoint.recovery_grants for each row execute function capture_checkpoint.freeze_record();
alter table capture_checkpoint.pages enable row level security;
alter table capture_checkpoint.items enable row level security;
alter table capture_checkpoint.watermarks enable row level security;
alter table capture_checkpoint.recovery_grants enable row level security;
revoke all on all tables in schema capture_checkpoint from public,anon,authenticated;
revoke all on all functions in schema capture_checkpoint from public,anon,authenticated;
