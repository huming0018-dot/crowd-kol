-- Read only. Opt-in snapshots only, never arbitrary page content or credentials.
select d.updated_at,d.updated_at<now()-interval '10 minutes' as stale,
 d.state->>'version' as client_version,d.state->>'update_state' as update_state,
 d.state->>'phase' as phase,d.state->>'error' as error,
 d.state->>'document_kind' as document_kind,d.state->>'pending_kind' as pending_kind,
 event->>'id' as attempt_or_request_id,event->>'stage' as stage,
 to_timestamp((event->>'at')::bigint) as event_at,
 ordinal as order_in_snapshot
from crowd_v4.diagnostics d
left join lateral jsonb_array_elements(coalesce(d.state->'trace','[]'::jsonb)) with ordinality as e(event,ordinal) on true
where d.enabled
order by d.updated_at desc,ordinal;
