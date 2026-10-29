# V1 Spec — AI-native clinic system

Target: solo doctors and small clinics in India (Kerala first). This spec is the
agreed V1 scope for onboarding, operations, patients, consultation,
administration and the data model. It supersedes the hospital-scale model in
the current migrations; see `complexity-audit-2026-10-27.md`.

## Principles

- AI captures and drafts; people confirm. Nothing clinical is final until the
  doctor signs.
- Every AI-generated line links to its source (transcript segment or document).
- One visit record carries the whole journey: booking, queue, payment, consultation.
- Build only what removes a click, a call or a form for doctor or staff.

## Screens and access

Four screens: **Operations** (includes billing), **Patients**, **Consultation**,
**Administration**.

| Who | Access |
|---|---|
| Owner | Everything |
| Admin access = yes | Can edit clinic details, clinic rules, schedules and members |
| Any member | Only the screens assigned to them |

## 1. Onboarding (4 steps)

### Step 1 — Create owner account
Name · Email · Phone · Password. The first person becomes **Owner** with full
access. A solo doctor owner is also a doctor.

### Step 2 — Clinic details
Clinic name · Phone · Address. Everything else is editable later.

### Step 3 — Clinic rules (defaults for every doctor)
- Default consultation fee
- Working days and timings (one or more sessions per day, e.g. 9–12 and 5–8)
- Default booking mode: **Session** (capacity) or **Slot** (minutes per patient)
- Token assignment: **At booking** or **At arrival**

Payment is always collected after arrival; it is not configurable.

### Step 4 — Add members (optional, can skip)

| Field | Doctor | Staff |
|---|---|---|
| Name, email, phone | ✓ | ✓ |
| Speciality (fixed list) | ✓ | — |
| Designation (Receptionist, Nurse, IT, …) | — | ✓ |
| Consultation fee: clinic default or override | ✓ | — |
| Screen permissions | ✓ | ✓ |
| Admin access yes/no | ✓ | ✓ |
| Send invitation | ✓ | ✓ |

Invited member opens the link → sets password → joins with the assigned access.

## 2. Operations

**Flow:** Schedule doctors → Book patient → Arrival + payment → Waiting → With doctor → Done

### 2.1 Main screen
```
┌ Sunrise Clinic   [◀ 28 Oct ▶]   [Register] [New Booking] [Doctor Schedules] ┐
│ Dr. Anjali   9 AM–12 PM · Session · 18/30                                   │
│ Booked 8 · Waiting 6 · With doctor 1 · Done 3                               │
│ Dr. Rahul    5–8 PM · Slot (10 min) · 12/18                                 │
│ Booked 5 · Waiting 4 · With doctor 1 · Done 2                               │
└─────────────────────────────────────────────────────────────────────────────┘
```
Only doctors available on the selected date are shown. Clicking a doctor opens
that doctor's queue.

### 2.2 Doctor queue — four columns
```
Booked                     │ Waiting              │ With Doctor │ Done
UHID · Name · 9:30   📎 2  │ T5 · Name · ✓ Paid 📎│ T4 · Name   │ T1 · Name
Token (if at booking)      │ waiting 12 min       │             │
[Arrived] [Resched] [✕]    │                      │             │
```

| Column | Shows | Actions |
|---|---|---|
| Booked | UHID, name, time/session, token only if at booking, 📎 | Arrived, Reschedule, Cancel, 📎 Upload |
| Waiting | Token, name, payment status, waiting since, 📎 | 📎 Upload |
| With Doctor | Token, name | — |
| Done | Token, name | — |

Waiting is always ordered by token. The doctor moves a patient to With Doctor
from Consultation; signing completes the visit (Done).

### 2.3 New booking
`Patient (search or register) → Date → Doctor → Available session/slot → Confirm`
- Only bookable within the doctor's schedule (capacity or free slots).
- Token assigned at confirmation if the rule is **at booking**; otherwise empty.
- Staff tells the patient the token (if any) and expected time.

### 2.4 Walk-in
A patient at the counter without a booking.
`New Booking → Patient → Doctor → [Walk-in] → Pay → Token → Waiting`
- Date is today; no slot picking.
- Allowed only if the doctor works today and the session has room. Counts
  toward capacity.
- Slot mode: takes the next free slot, or joins the line after the last slot.
- Token is always given at this point.
- Never appears in Booked. If the patient does not pay, nothing is created.

### 2.5 Arrival
`[Arrived] → Fee ₹ (Cash | UPI | Card) → Paid → Token (if at arrival) → Waiting`
- Payment is available only after arrival and is **required** before Waiting.
- No unpaid or waived path in V1.

### 2.6 Document upload
One place only: **📎 on the patient's card** in Booked and Waiting.
- Tap → camera or file (photo/PDF) → uploaded. No form.
- File attaches to the patient and the visit.
- AI reads it in the background; the result appears in the doctor's brief.
- After the consultation starts, the doctor uploads from Consultation.

### 2.7 Doctor schedules
`[Doctor Schedules] → Doctor → Calendar → Date → Configure → Save`
- Default: clinic working days/timings apply to every doctor.
- A date can be overridden: Available/Off · Start–End · Session or Slot ·
  Capacity or slot minutes. Multiple sessions per date are allowed.
- Who can override: the doctor (own schedule) and staff with Operations access.
- Calendar shows default days normally and overridden dates highlighted.
- The schedule controls what can be booked.

### 2.8 Exceptions
- **Cancel:** only before arrival.
- **Reschedule:** only before arrival; moves the visit to another date,
  session or slot. Token is reassigned per the token rule.
- **No-show:** a booked patient not arrived by session end is marked
  automatically.

## 3. Booking and token rules

Two independent clinic settings:

| Setting | Options |
|---|---|
| Booking mode | Session (by count) · Slot (fixed minutes) |
| Token timing | At booking · At arrival |

Tokens are numbered **per doctor, per date**, starting at 1, never reused.

| Combination | Token given | Patient is told | Doctor sees patients in |
|---|---|---|---|
| Session + at booking | Booking order | "Token 7, come around 10:00" | Token order |
| Session + at arrival | Arrival order (after payment) | "Morning session, 9–12" | Arrival order |
| Slot + at booking | Slot order (9:00 = T1, 9:10 = T2…) | "Come at 9:20" | Slot order |
| Slot + at arrival | Arrival order (after payment) | "Come at 9:20" | Arrival order |

Walk-ins: next number at payment. With token at booking, a walk-in takes the
next unused number (slot mode: the next free slot's number, or after the last).

**Expected time**
- Slot mode: the slot time.
- Session mode: `session start + (patients ahead × average minutes)`, using
  the clinic's slot minutes as the average. With token at arrival the estimate
  uses the number already booked.

**Fee:** the doctor's override if set, otherwise the clinic default. Copied to
the visit when it is created; later fee changes do not affect it.

## 4. Visit status

```
booked ──Arrived──▶ (pay) ──▶ waiting ──Start──▶ with_doctor ──Sign──▶ done
  ├── cancelled  (before arrival only)
  └── no_show    (automatic at session end)
walk-in ──────────▶ (pay) ──▶ waiting
```

- `waiting` requires `paid_at`.
- `with_doctor` only from `waiting`; `done` only from `with_doctor`.
- Every status change writes an `events` row.

## 5. Patients

```
Search (name / phone / UHID) → Profile → Visit timeline → Note or document → PDF + Print
```
- Register: name, date of birth, sex, phone. UHID assigned automatically
  (`<clinic prefix>-<number>`).
- Profile: UHID, name, age, phone.
- Timeline: each visit with date, doctor, notes (SOAP, prescription, custom)
  and documents. Opening a note or document shows a PDF with Print.

## 6. Consultation (doctor workspace)

```
Left:   Today's patients (Waiting, by token) → [Next] / open
Centre: Brief → 🎙 Dictation → Notes (AI draft → edit → Sign)
Right:  Documents (newest first) · source of any line on tap
```
- **Brief:** AI summary of the latest documents and previous visits, key events
  and charts of numeric values. Cached on the visit; regenerated when new
  documents arrive.
- **Dictation:** live transcript of the consultation.
- **Notes:** AI drafts the note in the selected template plus the prescription,
  from the transcript and documents, with citations. Doctor edits and signs.
  Signed notes are immutable.
- Signing the visit's note completes the visit (Done). Prescription can be
  printed or sent on WhatsApp.

### Note templates by speciality
- Built-in SOAP templates per speciality; the doctor's speciality template is
  the default, and any template can be chosen from a dropdown.
- Examples:
  - General: Subjective · Objective · Assessment · Plan
  - Paediatrics: Subjective · Growth (wt, ht, HC, percentile) · Immunisation · Objective · Assessment · Plan
  - Gynaecology: Subjective · LMP / Obstetric history (G P L A) · Objective · Assessment · Plan
  - Orthopaedics: Subjective · Examination (site, ROM, tenderness) · Imaging · Assessment · Plan
  - Dermatology: Subjective · Lesion (site, type, size, distribution) · Objective · Assessment · Plan
- Clinic admins or doctors can copy a built-in template and edit its sections.
- One shared prescription template: medicine, dose, frequency, duration,
  instructions.

## 7. Administration

```
Clinic details · Clinic rules · Members · Note templates
```
- Members: add, edit, screens, admin access, fee override, deactivate,
  resend invite.
- The last active owner cannot be removed or deactivated.

## 8. Data model — 10 tables

Login is Supabase Auth (`auth.users`). Money is integer paise. All tables have
`clinic_id` and a row-level security rule: members see only their clinic's rows.

### `clinics`
| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| name, phone, address | text | |
| default_fee | integer | paise |
| booking_mode | `session` \| `slot` | |
| token_timing | `at_booking` \| `at_arrival` | |
| default_capacity | integer | session mode |
| default_slot_minutes | integer | slot mode; also the average for expected time |
| working_hours | jsonb | `{"mon":[{"start":"09:00","end":"12:00"}],"sun":[]}` |
| uhid_prefix | text | |
| next_uhid | integer | |
| created_at | timestamptz | |

### `members`
| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| clinic_id | uuid | |
| user_id | uuid, nullable | set when the invite is accepted |
| kind | `doctor` \| `staff` | |
| is_owner, is_admin | boolean | |
| name, email, phone | text | |
| speciality | text | doctors; fixed list (`general`, `paediatrics`, `gynaecology`, `orthopaedics`, `dermatology`, `ent`, `ophthalmology`, `dental`, …) |
| designation | text | staff |
| fee_override | integer, nullable | doctors |
| screens | text[] | `operations`, `patients`, `consultation`, `administration` |
| status | `invited` \| `active` \| `inactive` | |
| invited_at, joined_at | timestamptz | |

### `schedule_overrides`
| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| clinic_id, doctor_id | uuid | |
| date | date | unique with doctor_id |
| is_off | boolean | |
| sessions | jsonb | `[{"start":"09:00","end":"11:00","mode":"slot","slot_minutes":15}]` or `{"mode":"session","capacity":20}` |
| updated_by | uuid | |
| updated_at | timestamptz | |

### `patients`
| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| clinic_id | uuid | |
| uhid | text | unique per clinic |
| name | text | |
| dob | date | |
| sex | text | |
| phone | text | |
| created_by, created_at | | |

### `visits`
| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| clinic_id, patient_id, doctor_id | uuid | |
| date | date | |
| session_start, session_end | time | |
| mode | `session` \| `slot` | copied from the schedule |
| slot_time | time, nullable | slot mode |
| is_walk_in | boolean | |
| token | integer, nullable | unique per doctor + date |
| expected_time | time, nullable | |
| status | `booked` \| `waiting` \| `with_doctor` \| `done` \| `cancelled` \| `no_show` | |
| fee | integer | paise, copied at creation |
| payment_method | `cash` \| `upi` \| `card` | |
| paid_at, arrived_at, started_at, completed_at | timestamptz | |
| cancel_reason | text | |
| rescheduled_from | uuid, nullable | |
| brief | jsonb | cached AI brief |
| created_by, created_at | | |

### `documents`
| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| clinic_id, patient_id | uuid | |
| visit_id | uuid, nullable | |
| file_path, file_type | text | Supabase Storage |
| ai_status | `processing` \| `ready` \| `failed` | |
| extracted | jsonb | page text and findings, e.g. `{"Hb":7.2,"unit":"g/dL"}` |
| uploaded_by, created_at | | |

### `transcripts`
| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| clinic_id, visit_id | uuid | |
| status | `recording` \| `final` | |
| segments | jsonb | `[{"id":"s1","speaker":"doctor","text":"…","t":12.4}]` |
| created_at, finalized_at | timestamptz | |

### `notes`
| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| clinic_id, patient_id, visit_id | uuid | |
| template_id | uuid | → `note_templates` |
| type | `soap` \| `prescription` \| `custom` | |
| content | jsonb | sections, or medicines for a prescription |
| citations | jsonb | `[{"section":"plan","evidence_id":"s1"}]` |
| status | `draft` \| `signed` | signed is immutable |
| signed_by, signed_at | | |
| created_at, updated_at | timestamptz | |

### `note_templates`
| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| clinic_id | uuid, nullable | null = built-in |
| name | text | |
| speciality | text | same list as `members.speciality` |
| type | `soap` \| `prescription` \| `custom` | |
| sections | jsonb | `[{"key":"growth","label":"Growth","fields":["weight","height","hc"],"required":false}]` |
| is_active | boolean | |
| created_by, created_at | | |

### `events`
| Field | Type | Notes |
|---|---|---|
| id | bigint | |
| clinic_id | uuid | |
| actor_id | uuid | |
| entity, entity_id | text, uuid | e.g. `visit` |
| action | text | `booked`, `arrived`, `paid`, `started`, `signed`, `rescheduled`, `cancelled`, … |
| data | jsonb | what changed |
| at | timestamptz | |

### Constraints
- `visits`: unique (doctor_id, date, token); unique (doctor_id, date, slot_time)
  for active visits; `status in (waiting, with_doctor, done)` requires `paid_at`.
- `patients`: unique (clinic_id, uhid).
- `schedule_overrides`: unique (doctor_id, date).
- Token and UHID are allocated in one locked statement each.
- `notes`: no update once `status = signed`.

## 9. Architecture

One FastAPI app, Supabase (Postgres, Auth, Storage), Gemini and Deepgram
called directly. Business rules in Python; SQL only for constraints and the
token/UHID allocators.

```
backend/app/
  main.py · config.py · db.py · auth.py · ai.py · whatsapp.py · evidence.py
  features/
    onboarding/  admin/  schedules/  visits/  patients/
    documents/   brief/  dictation/  notes/
supabase/migrations/0001_baseline.sql
```

Each feature: `routes.py`, `service.py`, `models.py` (add `repo.py` only if
queries grow). No ontology engine, no provider interfaces, no job system.
Tests: end-to-end scenarios against a real Postgres, run in CI.

## Out of scope for V1

Locations, departments, partial payments, refunds, waivers, insurance,
inventory/pharmacy, lab integration, multi-branch, priority queue.
