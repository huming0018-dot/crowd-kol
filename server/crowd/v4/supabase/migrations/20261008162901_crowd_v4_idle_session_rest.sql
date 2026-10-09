begin;
-- A completed idle interval is already a session rest. Control polling does
-- not move next_action, so it cannot manufacture activity or redraw the rest.
-- This runs only after existing cooldown, global pause and action-gap checks.
do $$ declare def text; needle text := $s$   if s.session_count>=20 or (s.session_count>0 and s.session_started+interval '20 minutes'<=t) then$s$;
begin
 def:=pg_get_functiondef('crowd_observation.guard_internal(text,bigint,text)'::regprocedure);
 if position(needle in def)=0 then raise exception 'idle_session_anchor_missing'; end if;
 def:=replace(def,needle,$s$   if s.session_count>0 and s.next_action+interval '30 minutes'<=t then
    s.session_count:=0; s.session_started:=t;
   end if;
$s$ || needle);
 execute def;
end $$;
commit;
