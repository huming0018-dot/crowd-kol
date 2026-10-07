CREATE OR REPLACE FUNCTION public.crowd_settle(p_period text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_period_start date;
  v_period_end   date;
  v_result       jsonb;
begin
  -- 周期窗口：null → 本周一00:00 至今
  if p_period is null or p_period = '' then
    v_period_start := date_trunc('week', now())::date;
  else
    v_period_start := p_period::date;
  end if;
  v_period_end := (v_period_start + interval '7 days')::date;
  if v_period_end > now()::date then
    v_period_end := now()::date + 1;  -- 未满整周按今日截止
  end if;

  -- 聚合 accepted 证据（2026-10-07 起费率调整：note ¥2/条 → ¥0.01/10条；rating 单价不变）（只算真实落地：note 按唯一 note_id、rating 按参与者去重已由索引保证）
  with agg as (
    select
      p.participant_id,
      count(*) filter (where p.kind = 'note')    as eff_notes,
      count(*) filter (where p.kind = 'rating')  as eff_ratings
    from public.crowd_proofs p
    where p.gate_status = 'accepted'
      and coalesce(p.accepted_at, p.created_at) >= v_period_start
      and coalesce(p.accepted_at, p.created_at) <  v_period_end
    group by p.participant_id
    having count(*) > 0
  ),
  ups as (
    insert into public.crowd_settlements
      (participant_id, period, period_start, period_end,
       effective_notes, effective_ratings,
       unit_note, unit_rating, amount, status, settled_at)
    select
      a.participant_id,
      to_char(v_period_start, 'YYYY-MM-DD'),
      v_period_start, v_period_end,
      a.eff_notes, a.eff_ratings,
      coalesce((select unit_note   from public.crowd_settlements s
                where s.participant_id = a.participant_id order by s.settled_at desc nulls last limit 1), 0.001),
      coalesce((select unit_rating from public.crowd_settlements s
                where s.participant_id = a.participant_id order by s.settled_at desc nulls last limit 1), 1.00),
      a.eff_notes * 0.001 + a.eff_ratings * 1.00,
      'pending', now()
    from agg a
    on conflict (participant_id, period) do update set
      effective_notes  = excluded.effective_notes,
      effective_ratings = excluded.effective_ratings,
      amount           = excluded.amount,
      settled_at       = now(),
      status           = case when crowd_settlements.status = 'paid' then 'paid' else 'pending' end
    returning participant_id, period, effective_notes, effective_ratings, amount, status
  )
  select coalesce(jsonb_agg(to_jsonb(u) order by u.participant_id), '[]'::jsonb)
    into v_result
  from ups u;

  return jsonb_build_object('ok', true, 'period', to_char(v_period_start,'YYYY-MM-DD'),
                            'settled', v_result);
end;
$function$
