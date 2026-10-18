-- Read-only. Compare lanes explicitly; never add legacy accepted to v4 verified.
select jsonb_build_object(
 'observed_at',now(),
 'legacy',jsonb_build_object(
   'proofs',(select count(*) from public.crowd_proofs),
   'accepted',(select count(*) from public.crowd_proofs where gate_status='accepted'),
   'accepted_24h',(select count(*) from public.crowd_proofs where gate_status='accepted' and coalesce(accepted_at,created_at)>=now()-interval '24 hours'),
   'paused',(select value from public.crowd_config where key='global_pause')),
 'observations',jsonb_build_object(
   'notes',(select count(*) from crowd_observation.notes),
   'authors',(select count(*) from crowd_observation.authors),
   'snapshots',(select jsonb_object_agg(kind,n) from (select kind,count(*) n from crowd_observation.snapshots group by kind) q),
   'recent_submissions',(select jsonb_agg(q) from (select task_id,error,parser_version,title_chars,body_chars,anchor_terms,updated_at from crowd_observation.submission_status order by updated_at desc limit 10) q)),
 'v4',jsonb_build_object(
   'received',(select count(*) from crowd_v4.proofs),
   'verified',(select count(*) from crowd_v4.proofs where status='verified'),
   'received_24h',(select count(*) from crowd_v4.proofs where received_at>=now()-interval '24 hours'),
   'paused',(select paused from crowd_v4.policy where singleton),
   'task_ready',(select count(*) from crowd_v4.tasks where received<target and ((status='open' and available_at<=now()) or (status='leased' and lease_until<now()))),
   'task_deferred',(select count(*) from crowd_v4.tasks where status='open' and available_at>now()),
   'next_task_retry',(select min(available_at) from crowd_v4.tasks where status='open' and available_at>now()),
   'task_states',(select jsonb_object_agg(status,n) from (select status,count(*) n from crowd_v4.tasks group by status) t),
   'diagnostics',(select jsonb_agg(jsonb_build_object('version',state->>'version','error',state->>'error',
      'phase',state->>'phase','nav_stage',state->>'nav_stage','nav_error',state->>'nav_error',
      'document_kind',state->>'document_kind','pending_kind',state->>'pending_kind',
      'update_state',state->>'update_state','last_node',state->'trace'->-1,
      'previous_nav_stage',state->>'prev_nav_stage','previous_nav_error',state->>'prev_nav_error',
      'page_failures',state->'page_failures','last_tick_age_s',state->'last_tick_age_s','next_in_s',state->'next_in_s','updated_at',updated_at,'stale',updated_at<now()-interval '10 minutes')) from crowd_v4.diagnostics where enabled))
) as health;
