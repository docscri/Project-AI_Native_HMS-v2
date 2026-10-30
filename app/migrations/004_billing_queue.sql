
alter table visits add column discount integer not null default 0;
alter table visits add column discount_reason text;
alter table visits add column amount_paid integer;
alter table visits add column receipt_no integer;
alter table visits add column refund_amount integer not null default 0;
alter table visits add column refund_reason text;
alter table visits add column refunded_at text;
alter table visits add column queue_order integer;
alter table visits add column late integer not null default 0;
alter table clinics add column next_receipt integer not null default 1;

update visits set amount_paid = fee where paid_at is not null and amount_paid is null;
update visits set queue_order = token where queue_order is null and token is not null;
