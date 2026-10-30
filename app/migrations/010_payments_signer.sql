-- One row per payment/refund so totals can't be corrupted.
create table if not exists payments (
    id integer primary key,
    clinic_id integer not null references clinics(id),
    visit_id integer not null references visits(id),
    kind text not null check (kind in ('payment', 'refund')),
    amount integer not null check (amount >= 0),
    method text,
    receipt_no integer,
    reason text,
    at text not null,
    by_member integer
);
create index if not exists payments_visit on payments (visit_id);
create index if not exists payments_when on payments (clinic_id, at);
insert into payments (clinic_id, visit_id, kind, amount, method, receipt_no, at)
    select clinic_id, id, 'payment', coalesce(amount_paid, 0), payment_method, receipt_no, paid_at from visits where paid_at is not null;
insert into payments (clinic_id, visit_id, kind, amount, reason, at)
    select clinic_id, id, 'refund', refund_amount, refund_reason, refunded_at from visits where refund_amount > 0 and refunded_at is not null;
-- Signer may differ from the visit's doctor.
alter table notes add column signed_by integer;
update notes set signed_by = doctor_id where status = 'signed';
