begin;
-- No additional diagnostic data: distinguish explicit login help from a real
-- platform gate and backend authentication failure. Older reports remain valid.
do $$ declare def text; needle text:=$s$'login_required','captcha'$s$; begin
 def:=pg_get_functiondef('public.crowd_v4_diagnostics(text,bigint,jsonb)'::regprocedure);
 if position(needle in def)=0 then raise exception 'diagnostics_error_anchor_missing'; end if;
 -- Only replace the error allowlist; gate still means a rendered platform gate.
 def:=replace(def,$s$'wrong_note','login_required','captcha'$s$,
                     $s$'wrong_note','login_required','backend_login_required','user_login','captcha'$s$);
 if position($s$'backend_login_required'$s$ in def)=0 then raise exception 'diagnostics_error_anchor_missing'; end if;
 execute def;
end $$;
commit;
