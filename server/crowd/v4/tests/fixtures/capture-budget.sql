-- Isolated detail-action budget prototype; requires capture-receiver.sql first.
-- Not a production migration, public RPC or replacement for crowd_v4_guard.
create schema capture_budget;
revoke all on schema capture_budget from public, anon, authenticated;

create table capture_budget.buckets (
  bucket_id uuid primary key,
  kind text not null check(kind in ('task','account','device_exit','platform')),
  owner_scope text not null,
  subject_ref text not null,
  platform text not null,
  max_detail_attempts integer not null check(max_detail_attempts between 0 and 60),
  max_requests integer not null check(max_requests between 0 and 60),
  used_detail_attempts integer not null default 0 check(used_detail_attempts>=0),
  used_requests integer not null default 0 check(used_requests>=0),
  active_slots integer not null default 0 check(active_slots between 0 and 1),
  max_concurrency integer not null default 1 check(max_concurrency=1),
  min_interval_seconds integer not null default 30 check(min_interval_seconds between 30 and 3600),
  next_allowed_at timestamptz not null default '-infinity',
  blocked_until timestamptz not null default '-infinity',
  paused boolean not null default false,
  window_start timestamptz not null default clock_timestamp(),
  window_end timestamptz not null,
  unique(kind,owner_scope,subject_ref,platform),
  check(used_detail_attempts<=max_detail_attempts and used_requests<=max_requests),
  check(kind<>'task' or max_detail_attempts<=2),
  check(window_end>window_start)
);
create table capture_budget.tasks (
  owner_scope text not null,
  task_id uuid not null,
  task_ref jsonb not null,
  platform text not null,
  allowed_targets jsonb not null,
  task_bucket_id uuid not null references capture_budget.buckets,
  platform_bucket_id uuid not null references capture_budget.buckets,
  current_run_id uuid not null,
  lease_epoch bigint not null check(lease_epoch between 1 and 9007199254740991),
  cancelled boolean not null default false,
  paused boolean not null default false,
  expires_at timestamptz not null,
  primary key(owner_scope,task_id),
  unique(owner_scope,task_ref),
  check(jsonb_typeof(task_ref)='object'),
  check(jsonb_typeof(allowed_targets)='array' and jsonb_array_length(allowed_targets) between 1 and 20)
);
create table capture_budget.sessions (
  owner_scope text not null,
  session_ref text not null,
  actor_ref text not null,
  platform text not null,
  account_ref text not null,
  device_exit_ref text not null,
  account_bucket_id uuid not null references capture_budget.buckets,
  device_bucket_id uuid not null references capture_budget.buckets,
  credential_epoch bigint not null check(credential_epoch between 1 and 9007199254740991),
  active boolean not null default false,
  primary key(owner_scope,session_ref),
  foreign key(owner_scope,actor_ref) references capture_receiver.actors
);
create table capture_budget.runs (
  owner_scope text not null,
  run_id uuid not null,
  task_id uuid not null,
  actor_ref text not null,
  session_ref text not null,
  lease_epoch bigint not null check(lease_epoch between 1 and 9007199254740991),
  credential_epoch bigint not null check(credential_epoch between 1 and 9007199254740991),
  lease_until timestamptz not null,
  source_kind text not null check(source_kind in ('rendered_public_dom','platform_api','authorized_export')),
  parser_version text not null check(parser_version ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
  normalization_version text not null check(normalization_version='capture-v1'),
  requested_fields text[] not null,
  paused boolean not null default false,
  primary key(owner_scope,run_id),
  foreign key(owner_scope,actor_ref) references capture_receiver.actors,
  foreign key(owner_scope,task_id) references capture_budget.tasks,
  foreign key(owner_scope,session_ref) references capture_budget.sessions,
  check(cardinality(requested_fields) between 1 and 8 and array_position(requested_fields,null) is null),
  check(requested_fields <@ array['title','body','published_at','metrics.likes','metrics.collects','metrics.comments','metrics.shares','metrics.views'])
);
create table capture_budget.actions (
  owner_scope text not null,
  request_id uuid not null,
  actor_ref text not null,
  run_id uuid not null,
  request_hash text not null check(request_hash ~ '^[a-f0-9]{64}$'),
  target_ref jsonb not null,
  admission_id uuid not null,
  bucket_ids uuid[] not null check(cardinality(bucket_ids)=4),
  jitter_seconds integer not null check(jitter_seconds between 0 and 15),
  reserved_at timestamptz not null,
  dispatch_until timestamptz not null,
  state text not null check(state in ('reserved','consumed','succeeded','failed','unknown','not_started')),
  consumed_at timestamptz,
  closed_at timestamptz,
  primary key(owner_scope,request_id),
  unique(owner_scope,admission_id),
  foreign key(owner_scope,run_id) references capture_budget.runs,
  foreign key(owner_scope,actor_ref) references capture_receiver.actors,
  check(dispatch_until>reserved_at),
  check((state in ('reserved','not_started'))=(consumed_at is null))
);

-- Operational flags/epochs can change; historical binding identities cannot be repointed.
create function capture_budget.freeze_configuration() returns trigger
language plpgsql security invoker set search_path=pg_catalog as $$
declare mutable text[];
begin
  mutable:=case tg_table_name
    when 'tasks' then array['current_run_id','lease_epoch','cancelled','paused','expires_at']
    when 'runs' then array['lease_until','paused']
    when 'sessions' then array['credential_epoch','active'] end;
  if tg_op='UPDATE' and to_jsonb(new)-mutable=to_jsonb(old)-mutable then return new; end if;
  raise exception 'immutable_budget_binding';
end;
$$;
create trigger freeze_task before update or delete on capture_budget.tasks for each row execute function capture_budget.freeze_configuration();
create trigger freeze_run before update or delete on capture_budget.runs for each row execute function capture_budget.freeze_configuration();
create trigger freeze_session before update or delete on capture_budget.sessions for each row execute function capture_budget.freeze_configuration();

alter table capture_budget.buckets enable row level security;
alter table capture_budget.tasks enable row level security;
alter table capture_budget.sessions enable row level security;
alter table capture_budget.runs enable row level security;
alter table capture_budget.actions enable row level security;
revoke all on all tables in schema capture_budget from public, anon, authenticated;
revoke all on all functions in schema capture_budget from public, anon, authenticated;
-- No client grants/policies/functions. Only isolated database-owner tests can configure it.
