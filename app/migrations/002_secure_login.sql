
create table if not exists sessions (
    token_hash text primary key,
    member_id integer not null references members(id) on delete cascade,
    created_at text not null,
    expires_at text not null
);
create index if not exists sessions_member on sessions (member_id);

create table if not exists password_resets (
    token_hash text primary key,
    member_id integer not null references members(id) on delete cascade,
    expires_at text not null,
    used_at text
);

alter table members add column failed_logins integer not null default 0;
alter table members add column locked_until text;
alter table members add column invite_expires_at text;
