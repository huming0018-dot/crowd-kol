-- Isolated M1 prototype. Not a production migration or an exposed API.
create schema capture_receiver;
revoke all on schema capture_receiver from public, anon, authenticated;

create table capture_receiver.actors (
  owner_scope text not null,
  actor_ref text not null,
  enabled boolean not null default false,
  primary key (owner_scope, actor_ref),
  check (owner_scope ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
  check (actor_ref ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')
);

create table capture_receiver.admissions (
  owner_scope text not null,
  admission_id uuid not null,
  actor_ref text not null,
  binding jsonb not null,
  parser_version text not null check (parser_version ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
  normalization_version text not null check (normalization_version = 'capture-v1'),
  requested_fields text[] not null,
  issued_at timestamptz not null default clock_timestamp(),
  accept_until timestamptz not null,
  revoked boolean not null default false,
  primary key (owner_scope, admission_id),
  foreign key (owner_scope, actor_ref) references capture_receiver.actors,
  check (jsonb_typeof(binding) = 'object'),
  check (binding->>'owner_scope' is not null and binding->>'owner_scope' = owner_scope),
  check (binding->>'actor_ref' is not null and binding->>'actor_ref' = actor_ref),
  check (binding->>'admission_id' is not null and binding->>'admission_id' = admission_id::text),
  check (accept_until > issued_at),
  check (cardinality(requested_fields) between 1 and 8 and array_position(requested_fields, null) is null),
  check (requested_fields <@ array['title','body','published_at','metrics.likes','metrics.collects','metrics.comments','metrics.shares','metrics.views'])
);

create table capture_receiver.captures (
  owner_scope text not null,
  capture_id uuid not null,
  actor_ref text not null,
  admission_id uuid not null,
  run_id uuid not null,
  lease_epoch bigint not null check (lease_epoch >= 1),
  credential_epoch bigint not null check (credential_epoch >= 1),
  envelope_hash text not null check (envelope_hash ~ '^[a-f0-9]{64}$'),
  envelope jsonb not null,
  parser_version text not null,
  normalization_version text not null,
  requested_fields text[] not null,
  received_at timestamptz not null,
  receipt jsonb not null,
  primary key (owner_scope, capture_id),
  unique (owner_scope, admission_id),
  foreign key (owner_scope, actor_ref) references capture_receiver.actors,
  foreign key (owner_scope, admission_id) references capture_receiver.admissions,
  check (jsonb_typeof(envelope) = 'object' and jsonb_typeof(receipt) = 'object'),
  check (envelope->>'envelope_hash' is not null and envelope->>'envelope_hash' = envelope_hash),
  check (envelope->>'capture_id' is not null and envelope->>'capture_id' = capture_id::text),
  check (receipt->>'status' is not null and receipt->>'status' = 'received'),
  check (receipt->>'capture_id' is not null and receipt->>'capture_id' = capture_id::text)
);

-- Only revocation may change an admission; historical bindings and versions stay fixed.
create function capture_receiver.freeze_record() returns trigger
language plpgsql security invoker set search_path = pg_catalog as $$
begin
  if tg_table_name = 'admissions' and tg_op = 'UPDATE'
     and (to_jsonb(new) - 'revoked') = (to_jsonb(old) - 'revoked') then
    return new;
  end if;
  raise exception 'immutable_capture_record';
end;
$$;
create trigger freeze_admission before update or delete on capture_receiver.admissions
for each row execute function capture_receiver.freeze_record();
create trigger freeze_capture before update or delete on capture_receiver.captures
for each row execute function capture_receiver.freeze_record();

alter table capture_receiver.actors enable row level security;
alter table capture_receiver.admissions enable row level security;
alter table capture_receiver.captures enable row level security;
revoke all on all tables in schema capture_receiver from public, anon, authenticated;
revoke all on all functions in schema capture_receiver from public, anon, authenticated;
-- No grants and no client RLS policies. Tests run as the isolated database owner.
-- Production roles, retention/deletion and migrations require a separate review.
