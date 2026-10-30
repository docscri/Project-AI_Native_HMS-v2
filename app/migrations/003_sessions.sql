-- Tokens restart in each session.

alter table clinics add column sessions text;
alter table schedule_overrides add column sessions text;
alter table visits add column session_start text;

update visits set session_start = coalesce(
    (select o.start from schedule_overrides o where o.doctor_id = visits.doctor_id and o.date = visits.date and o.is_off = 0),
    (select c.start from clinics c where c.id = visits.clinic_id))
where session_start is null;

drop index if exists visits_token;
create unique index if not exists visits_session_token on visits (doctor_id, date, session_start, token)
    where token is not null and status not in ('cancelled', 'no_show');
