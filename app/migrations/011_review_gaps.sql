-- Stale transcript saves are refused.
alter table visits add column dictation_rev integer not null default 0;
-- Keep the signer's name if the account is removed.
alter table notes add column signed_by_name text;
update notes set signed_by_name = (select name from members where members.id = notes.signed_by) where signed_by is not null;
-- Restore payments lost by old undo-arrival so balances aren't negative.
insert into payments (clinic_id, visit_id, kind, amount, reason, at)
    select v.clinic_id, v.id, 'payment', -b.held, 'Reconstructed: original payment not recorded', coalesce(v.refunded_at, v.date)
    from visits v join (select visit_id, sum(case when kind = 'payment' then amount else -amount end) as held
                        from payments group by visit_id) b on b.visit_id = v.id
    where b.held < 0;
