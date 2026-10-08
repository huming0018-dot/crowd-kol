-- Read-only. Compare lanes explicitly; never add legacy accepted to v4 verified.
select jsonb_build_object(
 'observed_at',now(),
 'legacy',jsonb_build_object(
   'proofs',(select count(*) from public.crowd_proofs),
   'accepted',(select count(*) from public.crowd_proofs where gate_status='accepted'),
   'accepted_24h',(select count(*) from public.crowd_proofs where gate_status='accepted' and coalesce(accepted_at,created_at)>=now()-interval '24 hours'),
   'paused',(select value from public.crowd_config where key='global_pause')),
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
      'phase',state->>'phase','updated_at',updated_at,'stale',updated_at<now()-interval '10 minutes')) from crowd_v4.diagnostics where enabled))
) as health;
