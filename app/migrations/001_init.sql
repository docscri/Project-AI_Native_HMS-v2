-- One clinic, its people, patients and visits. Money is integer rupees.

create table if not exists clinics (
    id integer primary key,
    name text not null default '',
    phone text not null default '',
    address text not null default '',
    fee integer not null default 300,
    days text not null default '[1,2,3,4,5,6]',          -- weekdays, 0 = Sunday
    start text not null default '09:00',
    "end" text not null default '12:00',
    limit_by text not null default 'patients' check (limit_by in ('patients', 'minutes')),
    limit_value integer not null default 30,
    token_timing text not null default 'booking' check (token_timing in ('booking', 'arrival')),
    uhid_prefix text not null default 'CL',
    next_uhid integer not null default 1,
    onboarded integer not null default 0,
    created_at text not null default current_timestamp
);

create table if not exists members (
    id integer primary key,
    clinic_id integer not null references clinics(id),
    kind text not null check (kind in ('doctor', 'staff')),
    is_owner integer not null default 0,
    is_admin integer not null default 0,
    name text not null,
    email text not null unique,
    phone text not null default '',
    password_hash text,
    token text unique,
    invite_code text unique,
    speciality text,
    designation text,
    fee_override integer,
    screens text not null default '[]',
    status text not null default 'invited' check (status in ('invited', 'active', 'inactive')),
    created_at text not null default current_timestamp
);

create table if not exists schedule_overrides (
    id integer primary key,
    clinic_id integer not null references clinics(id),
    doctor_id integer not null references members(id),
    date text not null,
    is_off integer not null default 0,
    start text,
    "end" text,
    limit_by text,
    limit_value integer,
    unique (doctor_id, date)
);

create table if not exists patients (
    id integer primary key,
    clinic_id integer not null references clinics(id),
    uhid text not null,
    name text not null,
    dob text,
    sex text,
    phone text not null default '',
    created_at text not null default current_timestamp,
    unique (clinic_id, uhid)
);

create table if not exists visits (
    id integer primary key,
    clinic_id integer not null references clinics(id),
    patient_id integer not null references patients(id),
    doctor_id integer not null references members(id),
    date text not null,
    token integer,
    status text not null check (status in ('booked', 'waiting', 'with_doctor', 'done', 'cancelled', 'no_show')),
    is_walk_in integer not null default 0,
    fee integer not null,
    payment_method text check (payment_method in ('cash', 'upi', 'card')),
    paid_at text,
    arrived_at text,
    started_at text,
    completed_at text,
    cancel_reason text,
    transcript text not null default '[]',
    brief text,
    created_at text not null default current_timestamp,
    check (status not in ('waiting', 'with_doctor', 'done') or paid_at is not null)
);
create unique index if not exists visits_token on visits (doctor_id, date, token)
    where token is not null and status not in ('cancelled', 'no_show');

create table if not exists documents (
    id integer primary key,
    clinic_id integer not null references clinics(id),
    patient_id integer not null references patients(id),
    visit_id integer references visits(id),
    filename text not null,
    path text not null,
    mime text,
    ai_status text not null default 'processing' check (ai_status in ('processing', 'ready', 'failed')),
    extracted text,
    created_at text not null default current_timestamp
);

create table if not exists notes (
    id integer primary key,
    clinic_id integer not null references clinics(id),
    patient_id integer not null references patients(id),
    visit_id integer not null unique references visits(id),
    doctor_id integer not null references members(id),
    content text not null,          -- {"soap": {"S","O","A","P"}, "rx": [{medicine, dose, duration, instructions}]}
    citations text not null default '{}',
    status text not null default 'draft' check (status in ('draft', 'signed')),
    signed_at text,
    created_at text not null default current_timestamp,
    updated_at text not null default current_timestamp
);

create table if not exists events (
    id integer primary key,
    clinic_id integer not null,
    actor_id integer,
    entity text not null,
    entity_id integer,
    action text not null,
    data text,
    at text not null default current_timestamp
);
