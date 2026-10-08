begin;
-- Source: china-travel-food research/regression_set.json (v3): explicit aliases for 晴川.
-- No two-character fuzzy match, no LLM-generated aliases, no change to verification/payment.
create table crowd_observation.task_aliases (
 store_name text not null, term text not null check(length(term) between 2 and 120),source text not null,
 primary key(store_name,term)
);
alter table crowd_observation.task_aliases enable row level security;
revoke all on crowd_observation.task_aliases from public,anon,authenticated;
insert into crowd_observation.task_aliases values
 ('晴川sushi（午市）','晴川日本料理','china-travel-food/research/regression_set.json:v3'),
 ('晴川sushi（午市）','晴川寿司','china-travel-food/research/regression_set.json:v3');
create function crowd_observation.terms(p_store text,p_terms jsonb) returns jsonb language sql stable set search_path='' as $$
 select case when exists(select from crowd_observation.task_aliases where store_name=p_store) then
  (select jsonb_agg(term order by term) from (select jsonb_array_elements_text(p_terms) term union select term from crowd_observation.task_aliases where store_name=p_store) a)
 else p_terms end
$$;
revoke all on function crowd_observation.terms(text,jsonb) from public,anon,authenticated;
create function crowd_observation.task_terms() returns trigger language plpgsql security definer set search_path='' as $$ begin
 new.anchor_terms:=crowd_observation.terms(new.store_name,new.anchor_terms);return new;
end $$;
revoke all on function crowd_observation.task_terms() from public,anon,authenticated;
create trigger crowd_observation_task_terms before insert or update of store_name,anchor_terms on crowd_v4.tasks for each row execute function crowd_observation.task_terms();
update crowd_v4.tasks set anchor_terms=crowd_observation.terms(store_name,anchor_terms)
 where store_name in(select store_name from crowd_observation.task_aliases);
-- Normalize operator payload too, preserving publish idempotence after trigger enrichment.
do $$ declare def text; needle text:=E'begin\n';begin
 def:=pg_get_functiondef('public.crowd_v4_admin(text,jsonb)'::regprocedure);
 if position(needle in def)=0 then raise exception 'admin_anchor_missing';end if;
 def:=overlay(def placing needle||$body$ if p_action='publish' and jsonb_typeof(p_payload->'anchor_terms')='array' then
 p_payload:=jsonb_set(p_payload,'{anchor_terms}',crowd_observation.terms(p_payload->>'store_name',p_payload->'anchor_terms'));end if;
$body$ from position(needle in def) for length(needle));execute def;
 def:=pg_get_functiondef('crowd_observation.guard_internal(text,bigint,text)'::regprocedure);
 if position($s$'observations',1$s$ in def)=0 then raise exception 'guard_anchor_missing';end if;
 execute replace(def,$s$'observations',1$s$,$s$'observations',1,'relevance_revision',1$s$);
end $$;

-- One diagnostic summary per participant: no title/body/URL/cookie is stored here.
create table crowd_observation.submission_status (
 user_id uuid primary key references crowd_v4.participants(user_id), request uuid not null,
 task_id bigint, error text, parser_version text, title_chars int,body_chars int,
 anchor_terms jsonb,updated_at timestamptz not null default now()
);
alter table crowd_observation.submission_status enable row level security;
revoke all on crowd_observation.submission_status from public,anon,authenticated;
alter function public.crowd_v4_submit(uuid,bigint,uuid,jsonb) set schema crowd_observation;
alter function crowd_observation.crowd_v4_submit(uuid,bigint,uuid,jsonb) rename to submit_internal;
revoke all on function crowd_observation.submit_internal(uuid,bigint,uuid,jsonb) from public,anon,authenticated;
create function public.crowd_v4_submit(p_request uuid,p_task bigint,p_lease uuid,p_record jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$ declare result jsonb;begin
 result:=crowd_observation.submit_internal(p_request,p_task,p_lease,p_record);
 if p_request is not null then
  insert into crowd_observation.submission_status(user_id,request,task_id,error,parser_version,title_chars,body_chars,anchor_terms)
  values(auth.uid(),p_request,p_task,result->>'error',left(p_record#>>'{evidence,parser_version}',20),length(p_record#>>'{standard,title}'),length(p_record#>>'{evidence,text}'),
    (select anchor_terms from crowd_v4.tasks where id=p_task and claimed_by=auth.uid()))
  on conflict(user_id) do update set request=excluded.request,task_id=excluded.task_id,error=excluded.error,parser_version=excluded.parser_version,
   title_chars=excluded.title_chars,body_chars=excluded.body_chars,anchor_terms=excluded.anchor_terms,updated_at=now();
 end if;
 return result;
end $$;
revoke all on function public.crowd_v4_submit(uuid,bigint,uuid,jsonb) from public,anon;
grant execute on function public.crowd_v4_submit(uuid,bigint,uuid,jsonb) to authenticated;
insert into crowd_v4.audit(action,payload) values('relevance_aliases',jsonb_build_object('store_name','晴川sushi（午市）','source','research/regression_set.json:v3','bare_name_accepted',false));
commit;
