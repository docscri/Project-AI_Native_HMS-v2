create table if not exists waitlist (
    id integer primary key,
    clinic_id integer not null references clinics(id),
    patient_id integer not null references patients(id),
    doctor_id integer not null references members(id),
    date text not null,
    session_start text,
    status text not null default 'waiting' check (status in ('waiting', 'booked', 'removed')),
    visit_id integer,
    added_by integer,
    created_at text not null default current_timestamp
);
create index if not exists waitlist_day on waitlist (doctor_id, date, status);
alter table visits add column follow_up_of integer;
