-- Team: profile details, leave, attendance. Money: day close.
alter table members add column joined_on text;
alter table members add column emergency_contact text not null default '';
alter table members add column address text not null default '';
alter table members add column id_number text not null default '';
alter table members add column work_days text;        -- staff: JSON weekdays [0..6]; empty = clinic days
alter table members add column work_start text;       -- staff: usual start, e.g. 09:00
alter table members add column work_end text;

create table if not exists leave_requests (
    id integer primary key,
    clinic_id integer not null references clinics(id),
    member_id integer not null references members(id),
    start_date text not null,
    end_date text not null,
    type text not null default 'casual' check (type in ('casual', 'sick', 'earned', 'other')),
    reason text not null default '',
    status text not null default 'pending' check (status in ('pending', 'approved', 'rejected', 'cancelled')),
    decided_by integer,
    decided_at text,
    created_at text not null default current_timestamp
);
create index if not exists leave_member on leave_requests (member_id, start_date);

create table if not exists attendance (
    id integer primary key,
    clinic_id integer not null references clinics(id),
    member_id integer not null references members(id),
    date text not null,
    status text not null check (status in ('present', 'late', 'absent', 'half')),
    check_in text,
    check_out text,
    note text not null default '',
    edited_by integer,
    unique (member_id, date)
);

create table if not exists day_close (
    id integer primary key,
    clinic_id integer not null references clinics(id),
    date text not null,
    system_cash integer not null,
    counted_cash integer not null,
    note text not null default '',
    closed_by integer,
    closed_at text,
    unique (clinic_id, date)
);
