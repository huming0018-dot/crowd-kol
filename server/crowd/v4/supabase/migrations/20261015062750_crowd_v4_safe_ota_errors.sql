-- Fixed OTA codes only. No new fields, no widened non-OTA health errors, no credential text.
begin;
do $migration$
declare definition text; old text := $old$'invalid_signature','hash_mismatch','permission_change','replayed_release','recovery_required','busy','operation_failed','invalid_manifest','invalid_url','wrong_extension','update_failed'$old$; replacement text := $new$'invalid_signature','hash_mismatch','permission_change','replayed_release','recovery_required','busy','operation_failed','invalid_manifest','invalid_url','wrong_extension','update_failed','ota_network_dns','ota_network_connect','ota_network_timeout','ota_network_tls','ota_network_http','ota_network_transfer','ota_io_permission','ota_io_missing','ota_io_space','ota_io_failed','ota_package_tool_failed','ota_service_failed','ota_process_terminated','ota_process_launch_failed','ota_unknown_exit','too_large','unsafe_archive','invalid_package','lock_failed','swap_failed','process_check_failed','handshake_mismatch','version_mismatch'$new$;
begin
 select pg_get_functiondef('public.crowd_v4_diagnostics(text,bigint,jsonb)'::regprocedure) into definition;
 if definition is null or (length(definition)-length(replace(definition,old,'')))/length(old)<>1 then raise exception 'ota_diagnostic_anchor_mismatch'; end if;
 execute replace(definition,old,replacement);
end $migration$;
do $migration$
declare definition text; old text := $old$'invalid_signature','hash_mismatch','permission_change','replayed_release','recovery_required','busy','operation_failed','invalid_manifest','invalid_url','wrong_extension','update_failed'$old$; replacement text := $new$'invalid_signature','hash_mismatch','permission_change','replayed_release','recovery_required','busy','operation_failed','invalid_manifest','invalid_url','wrong_extension','update_failed','ota_network_dns','ota_network_connect','ota_network_timeout','ota_network_tls','ota_network_http','ota_network_transfer','ota_io_permission','ota_io_missing','ota_io_space','ota_io_failed','ota_package_tool_failed','ota_service_failed','ota_process_terminated','ota_process_launch_failed','ota_unknown_exit','too_large','unsafe_archive','invalid_package','lock_failed','swap_failed','process_check_failed','handshake_mismatch','version_mismatch'$new$;
begin
 select pg_get_functiondef((select p.oid from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='crowd_v4' and p.proname='participant_health_projection')) into definition;
 if definition is null or (length(definition)-length(replace(definition,old,'')))/length(old)<>1 then raise exception 'ota_diagnostic_anchor_mismatch'; end if;
 execute replace(definition,old,replacement);
end $migration$;
do $migration$
declare definition text; old text := $old$(e->>'error_code' is not null and crowd_v4.participant_health_error(e->>'error_code') is distinct from e->>'error_code')$old$; replacement text := $new$(e->>'error_code' is not null and crowd_v4.participant_health_error(e->>'error_code') is distinct from e->>'error_code' and not (e->>'step'='ota' and e->>'error_code'=any(array['ota_network_dns','ota_network_connect','ota_network_timeout','ota_network_tls','ota_network_http','ota_network_transfer','ota_io_permission','ota_io_missing','ota_io_space','ota_io_failed','ota_package_tool_failed','ota_service_failed','ota_process_terminated','ota_process_launch_failed','ota_unknown_exit','ota_signature_invalid','ota_hash_mismatch','ota_permission_change','ota_replayed_release','ota_recovery_required','ota_handshake_mismatch','ota_version_mismatch','ota_busy','ota_invalid_package','ota_invalid_url','ota_wrong_extension','ota_unknown','ota_io_failed'])))$new$;
begin
 select pg_get_functiondef('public.crowd_v4_step_events(uuid,jsonb)'::regprocedure) into definition;
 if definition is null or (length(definition)-length(replace(definition,old,'')))/length(old)<>1 then raise exception 'ota_diagnostic_anchor_mismatch'; end if;
 execute replace(definition,old,replacement);
end $migration$;
commit;
