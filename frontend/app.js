/* Clinic V1 — single-page frontend. Hash routes, one state object, event delegation on data-a. */
"use strict";

const S = { token: null, me: null, clinic: null, doctors: [], date: null, data: null, timer: null, rec: null };
try { S.token = localStorage.getItem("clinic.token"); } catch {}

/* ---------- helpers ---------- */
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const TODAY = iso(new Date());
const addDays = (s, n) => { const d = new Date(s + "T00:00"); d.setDate(d.getDate() + n); return iso(d); };
const niceDate = s => new Date(s + "T00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
const longDate = s => new Date(s.slice(0, 10) + "T00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
const initials = n => n.replace(/^Dr\.?\s*/i, "").split(/\s+/).map(w => w[0]).join("").slice(0, 2).toUpperCase();
const ageOf = dob => { if (!dob) return ""; const b = new Date(dob), t = new Date(); let a = t.getFullYear() - b.getFullYear(); if (t < new Date(t.getFullYear(), b.getMonth(), b.getDate())) a--; return a; };
const firstName = n => n.replace(/^Dr\.?\s*/i, "").trim().split(/\s+/)[0] || "User";
const STATUS = { booked: "Booked", waiting: "Waiting", with_doctor: "In consultation", done: "Done", no_show: "No-show", cancelled: "Cancelled" };
const pill = st => `<span class="pill s-${st}">${STATUS[st] || st}</span>`;
const toMin = t => { const [h, m] = t.split(":").map(Number); return h * 60 + m; };
function limitsOf(start, end, by, val) {
  const len = Math.max(1, toMin(end) - toMin(start)); val = Math.max(1, Number(val) || 1);
  return by === "minutes" ? { max: Math.max(1, Math.floor(len / val)), per: val } : { max: val, per: Math.round(len / val) };
}
const icon = {
  ops: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>',
  patients: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/></svg>',
  consult: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 12h4l2-5 4 10 2-5h6"/></svg>',
  admin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/></svg>',
  mic: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
};

async function api(path, opts = {}) {
  const headers = { ...(S.token ? { Authorization: "Bearer " + S.token } : {}) };
  let body = opts.body;
  if (body && !(body instanceof FormData)) { headers["Content-Type"] = "application/json"; body = JSON.stringify(body); }
  const res = await fetch("/api" + path, { method: opts.method || (body ? "POST" : "GET"), headers, body });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && !opts.quiet) { logout(); throw new Error("Please log in."); }
  if (!res.ok) {
    const d = data.detail;
    throw new Error(Array.isArray(d) ? d.map(x => `${x.loc?.slice(-1)[0]}: ${x.msg}`).join(", ") : d || "Something went wrong.");
  }
  return data;
}
function toast(msg, err) {
  $("#toast").innerHTML = `<div class="toast ${err ? "err" : ""}" role="status">${esc(msg)}</div>`;
  clearTimeout(toast.t); toast.t = setTimeout(() => ($("#toast").innerHTML = ""), err ? 4200 : 2600);
}
async function run(fn) { try { return await fn(); } catch (e) { toast(e.message, true); } }
function modal(html, wide) {
  $("#modal").innerHTML = html ? `<div class="scrim" data-a="scrim"><div class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true">${html}</div></div>` : "";
}
const closeModal = () => { modal(""); M = null; };
const go = h => { if (location.hash === h) route(); else location.hash = h; };
function setToken(t) { S.token = t; try { t ? localStorage.setItem("clinic.token", t) : localStorage.removeItem("clinic.token"); } catch {} }
function logout() { setToken(null); S.me = null; stopTimers(); go("#/login"); }
function stopTimers() { clearInterval(S.timer); S.timer = null; clearTimeout(S.docT); if (S.rec) { try { S.rec.stop(); } catch {} S.rec = null; } }

/* ---------- routing ---------- */
const SCREENS = [["operations", "#/ops", "Operations", icon.ops], ["patients", "#/patients", "Patients", icon.patients],
  ["consultation", "#/consult", "Consultation", icon.consult], ["administration", "#/admin", "Administration", icon.admin]];

async function boot() {
  if (!S.token) return route();
  await run(async () => {
    const r = await api("/me");
    S.me = r.member; S.clinic = r.clinic; S.doctors = await api("/doctors");
  });
  route();
}
window.addEventListener("hashchange", route);

async function route() {
  stopTimers();
  const [path, query] = (location.hash.slice(1) || "/").split("?");
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "invite") return viewInvite(parts[1]);
  if (!S.token || !S.me) return parts[0] === "signup" ? viewOnboarding(1) : viewLogin();
  if (!S.clinic.onboarded) return viewOnboarding(2);
  const allowed = SCREENS.filter(s => S.me.screens.includes(s[0]));
  const map = { ops: "operations", patients: "patients", consult: "consultation", admin: "administration" };
  if (!parts[0] || !map[parts[0]] || !S.me.screens.includes(map[parts[0]])) return go(allowed[0]?.[1] || "#/patients");
  if (parts[0] !== "consult") shell(parts[0]);
  const q = new URLSearchParams(query || "");
  if (parts[0] === "ops") return parts[1] === "doctor" ? viewQueue(Number(parts[2])) : viewOps();
  if (parts[0] === "patients") return viewPatients(parts[1] ? Number(parts[1]) : null);
  if (parts[0] === "consult") return viewConsult(parts[1] ? Number(parts[1]) : null, q.get("doctor"), q.get("patient"));
  if (parts[0] === "admin") return viewAdmin(parts[1] || "clinic");
}

function shell(active) {
  const m = S.me;
  $("#root").innerHTML = `<div class="app">
    <nav class="nav" aria-label="Main">
      <div class="brand"><b>Dictate</b><span>${esc(S.clinic.name)}</span></div>
      ${SCREENS.filter(s => m.screens.includes(s[0])).map(([k, h, l, i]) => `<a href="${h}" ${h.slice(2) === active ? 'aria-current="page"' : ""}>${i}${l}</a>`).join("")}
      <div class="me"><div class="avatar">${esc(firstName(m.name)[0].toUpperCase())}</div><b>${esc(firstName(m.name))}</b><button class="logout-icon" data-a="logout" aria-label="Log out" title="Log out"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 17l5-5-5-5M15 12H3M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4"/></svg></button></div>
    </nav>
    <div class="stage"><main class="surface" id="view"><div class="muted">Loading…</div></main></div></div>`;
}
const view = html => { const v = $("#view"); if (v) v.innerHTML = html; };

/* ---------- login / onboarding / invite ---------- */
const WAVE_H = [14, 26, 40, 22, 48, 34, 18, 52, 30, 44, 20, 38, 54, 28, 16, 42, 50, 24, 36, 46, 18, 32, 52, 26, 40, 20, 48, 30];
const wave = () => `<div class="login-wave" aria-hidden="true">${Array.from({ length: 64 }, (_, i) => `<span style="--h:${WAVE_H[(i * 11) % 28]}px;animation-delay:${(i % 28) * 40}ms"></span>`).join("")}</div>`;
const arrowRight = '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>';
const arrowLeft = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M11 6l-6 6 6 6"/></svg>';
function authPage(inner, cls = "") {
  $("#root").innerHTML = `<main class="login-screen ${cls}"><div class="login-brand">Dictate</div>${wave()}<section class="login-stage">${inner}</section></main>`;
}
function viewLogin() {
  authPage(`<div class="login-card"><form id="login" class="login-fields" novalidate>
      <input class="login-input" id="lg-email" type="email" placeholder="Email" aria-label="Email" autocomplete="username">
      <div class="login-pw"><input class="login-input" id="lg-pw" type="password" placeholder="Password" aria-label="Password" autocomplete="current-password">
        <button class="login-submit glow" type="submit" aria-label="Sign in">${arrowRight}</button></div>
    </form>
    <p class="login-footer"><a class="login-link" href="#/signup">Create account</a></p></div>`);
  $("#login").addEventListener("submit", e => { e.preventDefault(); $(".login-screen").classList.add("busy"); run(async () => {
    try {
      const r = await api("/auth/login", { body: { email: $("#lg-email").value, password: $("#lg-pw").value }, quiet: true });
      setToken(r.token); await boot(); go("#/");
    } finally { $(".login-screen")?.classList.remove("busy"); }
  }); });
}

let OB = {};
function obFrame(step, inner, next = "Continue") {
  authPage(`<div class="ob-card">
    <div class="ob-top"><button class="ob-back" data-a="ob-back" data-v="${step}">${arrowLeft}<span>Back</span></button><span class="label">Step ${step} of 4</span></div>
    ${inner}
    <div class="ob-foot">${step === 4 ? `<button class="btn" data-a="ob-finish">Skip</button>` : ""}<button class="btn primary glow" data-a="ob-next" data-v="${step}">${next}</button></div></div>`, "ob");
}
function viewOnboarding(step) {
  OB.step = step;
  const me = S.me || {};
  if (step === 1) obFrame(1, `<h1>Create your account</h1>
    <label class="field">Name<input id="ob-name" value="${esc(me.name || "")}"></label>
    <div class="grid2"><label class="field">Email<input id="ob-email" type="email" value="${esc(me.email || "")}" ${S.me ? "disabled" : ""}></label><label class="field">Phone<input id="ob-phone" value="${esc(me.phone || "")}"></label></div>
    ${S.me ? "" : `<label class="field">Password<input id="ob-pw" type="password"></label>`}
    <label class="choice"><input type="checkbox" id="ob-doc" ${me.kind === "staff" ? "" : "checked"} ${S.me ? "disabled" : ""}><span><b>I am also a doctor here</b></span></label>`);
  if (step === 2) obFrame(2, `<h1>Your clinic</h1>
    <label class="field">Clinic name<input id="ob-cname" value="${esc(S.clinic.name)}"></label>
    <label class="field">Phone<input id="ob-cphone" value="${esc(S.clinic.phone)}"></label>
    <label class="field">Address<input id="ob-caddr" value="${esc(S.clinic.address)}"></label>`);
  if (step === 3) obFrame(3, `<h1>Clinic rules</h1>${rulesForm("ob", S.clinic)}`);
  if (step === 4) loadMembersStep();
}
async function loadMembersStep() {
  const ms = (await api("/members")).filter(m => !m.is_owner);
  obFrame(4, `<h1>Your team</h1>
    <div class="ob-team"><button class="btn" data-a="member-add" data-v="doctor">+ Add doctor</button><button class="btn" data-a="member-add" data-v="staff">+ Add staff</button></div>
    ${ms.length ? `<div class="rows">${ms.map(m => `<div class="r q"><b>${m.kind === "doctor" ? "Doctor" : esc(m.designation)}</b><span class="who">${esc(m.name)}</span>${inviteLink(m)}</div>`).join("")}</div>` : ""}`, "Finish setup");
}
const inviteLink = m => m.status === "invited" && m.invite_code ? `<button class="btn small" data-a="copy-invite" data-v="${esc(m.invite_code)}">Copy invite link</button>` : `<span class="pill s-paid">Active</span>`;

async function obNext(step) {
  if (step === 1 && S.me) { await api(`/members/${S.me.id}`, { method: "PATCH", body: { name: $("#ob-name").value, phone: $("#ob-phone").value } }); S.me = (await api("/me")).member; return viewOnboarding(2); }
  if (step === 1) {
    const r = await api("/onboarding/owner", { body: { name: $("#ob-name").value, email: $("#ob-email").value, phone: $("#ob-phone").value, password: $("#ob-pw").value, is_doctor: $("#ob-doc").checked } });
    setToken(r.token); const me = await api("/me"); S.me = me.member; S.clinic = me.clinic; return viewOnboarding(2);
  }
  if (step === 2) { S.clinic = await api("/clinic", { method: "PUT", body: { name: $("#ob-cname").value, phone: $("#ob-cphone").value, address: $("#ob-caddr").value } }); return viewOnboarding(3); }
  if (step === 3) { S.clinic = await api("/clinic/rules", { method: "PUT", body: readRules("ob") }); return viewOnboarding(4); }
  return obFinish();
}
async function obFinish() { S.clinic = await api("/onboarding/finish", { body: {} }); S.doctors = await api("/doctors"); toast(`Welcome to ${S.clinic.name}`); go("#/"); }

async function viewInvite(code) {
  await run(async () => {
    const inv = await api("/invites/" + code);
    authPage(`<div class="login-card"><div class="login-mic">${icon.mic}</div><h1 class="login-title">${esc(inv.clinic)}</h1><p class="login-sub">${esc(inv.name)}</p>
      <div class="login-pw"><input class="login-input" id="iv-pw" type="password" placeholder="Choose a password" aria-label="Choose a password">
      <button class="login-submit glow" data-a="accept-invite" data-v="${esc(code)}" aria-label="Join">${arrowRight}</button></div></div>`);
  });
}

/* clinic rules form (onboarding + admin) */
function limitBlock(p, v) {
  const l = limitsOf(v.start, v.end, v.limit_by, v.limit_value);
  const patientValue = v.limit_by === "patients" ? v.limit_value : Math.max(1, l.max);
  const minuteValue = v.limit_by === "minutes" ? v.limit_value : Math.max(1, l.per);
  const byP = v.limit_by === "patients";
  return `<div class="grid2"><label class="field">Start<input type="time" id="${p}-start" value="${v.start}" data-a="lim" data-p="${p}"></label><label class="field">End<input type="time" id="${p}-end" value="${v.end}" data-a="lim" data-p="${p}"></label></div>
    <div class="rule-row"><div class="pick-seg">
      <label><input type="radio" name="${p}-by" value="patients" ${byP ? "checked" : ""} data-a="lim" data-p="${p}"><span>By patients</span></label>
      <label><input type="radio" name="${p}-by" value="minutes" ${byP ? "" : "checked"} data-a="lim" data-p="${p}"><span>By time</span></label></div>
      <label class="field" ${byP ? "" : "hidden"}>Patients per session<input type="number" min="1" id="${p}-patients-val" value="${patientValue}" data-a="lim" data-p="${p}"></label>
      <label class="field" ${byP ? "hidden" : ""}>Minutes per patient<input type="number" min="1" id="${p}-minutes-val" value="${minuteValue}" data-a="lim" data-p="${p}"></label>
      <span class="rule-hint">${byP ? `≈ ${l.per} min each` : `${l.max} patients max`}</span></div>`;
}
function readLimit(p) {
  const by = $(`input[name="${p}-by"]:checked`).value;
  const el = $(`#${p}-${by}-val`);
  return { start: $(`#${p}-start`).value, end: $(`#${p}-end`).value, limit_by: by, limit_value: Number(el?.value) || 1 };
}
function rulesForm(p, c) {
  const dn = ["S", "M", "T", "W", "T", "F", "S"], full = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  return `<label class="field">Consultation fee (₹)<input type="number" min="0" id="${p}-fee" value="${c.fee}"></label>
    <div class="rule-group"><span class="rule-label">Working days</span><div class="day-dots">${dn.map((d, i) => `<label title="${full[i]}"><input type="checkbox" id="${p}-d${i}" ${c.days.includes(i) ? "checked" : ""} aria-label="${full[i]}"><span>${d}</span></label>`).join("")}</div></div>
    <div class="rule-group"><span class="rule-label">Hours</span><div id="${p}-lim" class="rule-stack">${limitBlock(p, c)}</div></div>
    <div class="rule-group"><span class="rule-label">Token</span><div class="pick-seg">
      <label><input type="radio" name="${p}-tok" value="booking" ${c.token_timing === "booking" ? "checked" : ""}><span>At booking</span></label>
      <label><input type="radio" name="${p}-tok" value="arrival" ${c.token_timing === "arrival" ? "checked" : ""}><span>On arrival</span></label></div></div>`;
}
const readRules = p => ({ fee: Number($(`#${p}-fee`).value) || 0, days: [0, 1, 2, 3, 4, 5, 6].filter(i => $(`#${p}-d${i}`).checked),
  ...readLimit(p), token_timing: $(`input[name="${p}-tok"]:checked`).value });

/* ---------- operations ---------- */
async function viewOps() {
  S.date = S.date || TODAY;
  const load = async () => {
    const d = await api(`/operations/day?date=${S.date}`);
    S.data = d;
    const st = d.stats, waiting = d.visits.filter(v => v.status === "waiting"), withDoc = d.visits.filter(v => v.status === "with_doctor");
    view(`<div class="head"><div><h1>Operations</h1><p>${S.date === TODAY ? "Today" : niceDate(S.date)} at ${esc(S.clinic.name)}</p></div><span class="grow"></span>
        <input class="top-date" type="date" data-a="ops-date" value="${S.date}" aria-label="Choose operations date"></div>
      <div class="tiles">
        <div class="tile"><span class="label">Booked</span><span class="big">${st.booked}</span></div>
        <div class="tile"><span class="label">Waiting</span><span class="big">${st.waiting}</span></div>
        <div class="tile"><span class="label">In consultation</span><span class="big">${st.with_doctor}</span></div>
        <div class="tile"><span class="label">Done</span><span class="big">${st.done}</span></div>
      </div>
      <div class="actions quick-actions"><button class="btn" data-a="book">New booking</button><button class="btn" data-a="walkin">Walk-in</button>
        <button class="btn" data-a="register">New patient</button><button class="btn" data-a="schedules">Doctor schedules</button></div>
      <div class="choices" style="gap:18px">
          <section class="panel"><span class="label">Doctors on ${S.date === TODAY ? "today" : niceDate(S.date)}</span>
            ${d.doctors.length ? `<div class="doctors">${d.doctors.map(doctorCard).join("")}</div>` : `<div class="empty">No doctors on this day</div>`}</section>
          <section class="panel"><span class="label">${S.date === TODAY ? "Today's" : "Day's"} visits</span>
            <div class="rows">${d.visits.map(v => `<div class="r"><span class="num"><b>${v.expected_time || "—"}</b></span>${S.me.screens.includes("patients") ? `<button class="patient-link who" data-a="pt-open" data-v="${v.patient_id}">${esc(v.patient_name)}</button>` : `<span class="who">${esc(v.patient_name)}</span>`}<span class="muted who doc-col">${esc(v.doctor_name)}</span>${pill(v.status)}</div>`).join("") || `<div class="empty">—</div>`}</div></section>
      </div>`);
  };
  await run(load);
  if (S.date === TODAY) S.timer = setInterval(() => !M && run(load), 8000);
}
function doctorCard(d) {
  const s = d.schedule;
  return `<button class="dcard" data-a="open-doctor" data-v="${d.id}">
    <div class="line"><span class="actions" style="gap:10px;align-items:center"><span class="letter">${d.letter}</span><h3>${esc(d.name)}</h3></span></div>
    <div class="muted" style="font-size:14px">${s.start}–${s.end}</div>
    <div class="capacity-line"><span>Capacity</span><b class="num">${d.used}/${s.max_patients}</b></div>
    <div class="meter"><i style="width:${Math.min(100, (d.used / s.max_patients) * 100)}%"></i></div>
  </button>`;
}

async function viewQueue(doctorId) {
  S.date = S.date || TODAY;
  const load = async () => {
    const q = await api(`/operations/queue?doctor_id=${doctorId}&date=${S.date}`);
    S.data = q;
    const cols = [["booked", "Booked"], ["waiting", "Waiting"], ["with_doctor", "With doctor"], ["done", "Done"]];
    const s = q.schedule;
    view(`<div class="head"><div><a href="#/ops" class="back-link">${arrowLeft}<span>Back</span></a><h1>${esc(q.doctor.name)}</h1>
        <p>${s ? `${s.start}–${s.end} · ${s.limit_by === "minutes" ? s.minutes_per_patient + " min per patient" : "up to " + s.max_patients + " patients"}` : "Off"}</p></div><span class="grow"></span>
        <input class="top-date" type="date" data-a="ops-date" value="${S.date}" aria-label="Choose queue date"></div>
      <div class="actions quick-actions"><button class="btn" data-a="book" data-v="${doctorId}">New booking</button><button class="btn" data-a="walkin" data-v="${doctorId}">Walk-in</button>
        ${s && q.columns.booked.length ? `<button class="btn" data-a="end-session" data-v="${doctorId}">End session</button>` : ""}</div>
      <div class="board">${cols.map(([k, l]) => `<section class="col"><header>${pill(k).replace(STATUS[k], l)}<span class="muted num">${q.columns[k].length}</span></header>
        ${q.columns[k].map(qCard).join("") || ""}</section>`).join("")}</div>
      ${q.not_seen.length ? `<section class="panel"><span class="label">Not seen</span><div class="rows">${q.not_seen.map(v => `<div class="r q" style="grid-template-columns:minmax(0,1fr) auto"><span>${esc(v.patient_name)}</span>${pill(v.status)}</div>`).join("")}</div></section>` : ""}`);
  };
  await run(load);
  if (S.date === TODAY) S.timer = setInterval(() => !M && run(load), 8000);
}
function qCard(v) {
  const tok = v.token_label ? `<span class="tok chip">${v.token_label}</span>` : `<span class="tok none">No token yet</span>`;
  const clip = `<button class="btn small" data-a="upload" data-v="${v.id}" aria-label="Add document">📎${v.doc_count ? " " + v.doc_count : ""}</button>`;
  let meta = "", acts = "";
  if (v.status === "booked") {
    meta = v.expected_time ? `${S.clinic.limit_by === "minutes" ? "" : "~"}${v.expected_time}` : "";
    acts = `<button class="btn small dark" data-a="arrive" data-v="${v.id}">Arrived</button><button class="btn small" data-a="resched" data-v="${v.id}">Reschedule</button><button class="btn small ghost" data-a="cancel" data-v="${v.id}">Cancel</button>${clip}`;
  } else if (v.status === "waiting") {
    meta = `<span class="pill s-paid">Paid ₹${v.fee} · ${(v.payment_method || "").toUpperCase()}</span>${v.is_walk_in ? `<span class="pill s-soft">Walk-in</span>` : ""}<span>since ${(v.arrived_at || "").slice(11, 16)}</span>`;
    acts = clip;
  } else meta = "";
  return `<article class="card"><div class="top"><b>${esc(v.patient_name)}</b>${tok}</div><div class="meta"><span class="mono">${esc(v.uhid)}</span>${meta}</div>${acts ? `<div class="acts">${acts}</div>` : ""}</article>`;
}
const refresh = () => route();

/* ---------- booking / walk-in / reschedule modal ---------- */
let M = null;
function openBooking(mode, opts = {}) {
  M = { kind: "booking", mode, patient: opts.patient || null, q: "", results: [], doctorId: opts.doctorId || S.doctors[0]?.id, date: mode === "walk" ? TODAY : (S.date && S.date >= TODAY ? S.date : TODAY),
        avail: null, token: null, pay: "upi", visit: opts.visit || null, done: null };
  if (!S.doctors.length) return toast("Add a doctor first (Administration → Members).", true);
  loadAvail();
}
async function loadAvail() {
  const b = M; if (!b || b.kind !== "booking") return;
  b.avail = await api(`/availability?doctor_id=${b.doctorId}&date=${b.mode === "walk" ? TODAY : b.date}${b.visit ? "&exclude_visit=" + b.visit.id : ""}`).catch(e => ({ available: false, reason: e.message }));
  b.token = b.avail.next?.token ?? null;
  renderBooking();
}
function slotCard(token, time, note, a) {
  return `<div class="tiles-row"><div class="tk big"><small>Token</small><b>${token}</b></div>
    ${time ? `<div class="tk"><small>${note ? "Around" : "Time"}</small><b>${time}</b></div>` : ""}
    <div class="tk"><small>Left</small><b>${a.left}</b></div></div>`;
}
function renderBooking() {
  const b = M; if (!b) return;
  if (b.done) return modal(b.done);
  const a = b.avail || {}, s = a.schedule;
  const title = { book: "New booking", walk: "Walk-in", resched: "Reschedule" }[b.mode];
  let slot = "";
  if (!a.available) slot = `<div class="warn">${esc(a.reason || "Not available.")}</div>`;
  else if (b.mode === "walk") slot = slotCard(a.token_timing === "booking" ? a.next.token : "—", "", "", a);
  else if (a.token_timing === "booking") {
    const free = new Set(a.free_tokens.map(t => t.token)), times = Object.fromEntries(a.free_tokens.map(t => [t.token, t.time]));
    slot = `${slotCard(b.token, times[b.token], s.exact_time ? "" : "approx.", a)}<div class="chips slot-chips">${Array.from({ length: s.max_patients }, (_, i) => i + 1).filter(t => free.has(t)).map(t => `<button data-a="pick-token" data-v="${t}" aria-pressed="${t === b.token}"><b>${t}</b>${times[t]}</button>`).join("")}</div>`;
  } else slot = slotCard("—", a.expected_time, "approx.", a);
  const p = b.patient;
  modal(`<div class="booking-dialog"><h2>${title}</h2>
    <div class="field">Patient</div>
    ${p ? `<div class="hit actions" style="justify-content:space-between;align-items:center"><span><b>${esc(p.name)}</b> <span class="mono muted">${esc(p.uhid)}</span> · ${esc(p.phone)}</span>${b.mode === "resched" ? "" : `<button class="btn small" data-a="bk-clear">Change</button>`}</div>`
        : `<input class="input" id="bk-q" placeholder="Search name, phone or UHID" value="${esc(b.q)}" data-a="bk-q" autocomplete="off">
           <div class="pick">${b.results.map(r => `<button data-a="bk-pick" data-v="${r.id}"><span><b>${esc(r.name)}</b> · ${esc(r.phone)}</span><span class="mono muted">${esc(r.uhid)}</span></button>`).join("")}</div>`}
    <div class="grid2 booking-fields">
      ${b.mode === "walk" ? "" : `<label class="field">Date<input type="date" id="bk-date" min="${TODAY}" value="${b.date}" data-a="bk-date"></label>`}
      <label class="field">Doctor<select id="bk-doc" data-a="bk-doc">${S.doctors.map(d => `<option value="${d.id}" ${d.id === b.doctorId ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select></label>
    </div>
    ${slot}
    <div class="foot"><button class="btn" data-a="close">Close</button>
      <button class="btn primary" data-a="bk-confirm" ${p && a.available ? "" : "disabled"}>${b.mode === "walk" ? "Paid" : b.mode === "resched" ? "Move booking" : "Confirm booking"}</button></div></div>`);
  const q = $("#bk-q"); if (q) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
}
async function confirmBooking() {
  const b = M, p = b.patient;
  if (b.mode === "walk") {
    const v = await api("/visits/walk-in", { body: { patient_id: p.id, doctor_id: b.doctorId, payment_method: b.pay } });
    b.done = `<h2>Walk-in added</h2><div class="result">${esc(p.name)} · ${v.token_label}</div><div class="foot"><button class="btn primary" data-a="close-refresh">Done</button></div>`;
  } else if (b.mode === "resched") {
    const v = await api(`/visits/${b.visit.id}/reschedule`, { body: { doctor_id: b.doctorId, date: b.date, token: b.token } });
    b.done = `<h2>Booking moved</h2><div class="result">${esc(p.name)} → ${esc(v.doctor_name)}, ${niceDate(v.date)}${v.token_label ? ` · token ${v.token_label} · ${v.expected_time}` : ""}</div><div class="foot"><button class="btn primary" data-a="close-refresh">Done</button></div>`;
  } else {
    const v = await api("/visits", { body: { patient_id: p.id, doctor_id: b.doctorId, date: b.date, token: b.token } });
    b.done = `<h2>Booked</h2><div class="result">${esc(p.name)} with ${esc(v.doctor_name)} · ${niceDate(v.date)}</div><div class="say">“${esc(v.tell_patient)}”</div>
      <div class="foot"><button class="btn" data-a="close-refresh">Done</button><button class="btn primary" data-a="book-another">Book another</button></div>`;
  }
  renderBooking();
}
let searchT;
function searchPatients(q) {
  M.q = q; clearTimeout(searchT);
  searchT = setTimeout(() => run(async () => { if (!M) return; M.results = q.trim() ? await api(`/patients?q=${encodeURIComponent(q)}`) : []; renderBooking(); }), 180);
}

/* arrival, cancel, upload, register */
function openArrive(v) {
  M = { kind: "arrive", pay: "upi", v };
  modal(`<h2>${esc(v.patient_name)} has arrived</h2>
    <div class="hit"><div class="label">Collect fee</div><div class="say">₹${v.fee}</div></div>
    <div class="seg" id="pay-seg">${["cash", "upi", "card"].map(m => `<button data-a="pay" data-v="${m}" aria-pressed="${m === "upi"}">${m.toUpperCase()}</button>`).join("")}</div>
    <div class="foot"><button class="btn" data-a="close">Not now</button><button class="btn primary" data-a="arrive-paid">Paid · send to Waiting</button></div>`);
}
function openUpload(visitId) {
  M = { kind: "upload", visitId };
  modal(`<h2>Add document</h2>
    <label class="field">File<input type="file" id="up-file" accept="image/*,.pdf,.txt"></label>
    <div class="foot"><button class="btn" data-a="close">Close</button><button class="btn primary" data-a="upload-go">Upload</button></div>`);
}
async function doUpload(visitId, file) {
  const fd = new FormData(); fd.append("file", file);
  await api(`/visits/${visitId}/documents`, { body: fd });
  toast("Uploaded. The AI is reading it.");
}
function openRegister(name) {
  const back = M?.kind === "booking" ? M : null;
  M = { kind: "register", back };
  modal(`<h2>New patient</h2>
    <div class="grid2"><label class="field">Name<input id="rg-name" value="${esc(name || "")}"></label><label class="field">Phone<input id="rg-phone" placeholder="98470 12345"></label></div>
    <div class="grid2"><label class="field">Date of birth<input id="rg-dob" type="date" max="${TODAY}"></label><label class="field">Sex<select id="rg-sex"><option value="M">Male</option><option value="F">Female</option><option value="O">Other</option></select></label></div>
    <div class="foot"><button class="btn" data-a="${back ? "rg-back" : "close"}">${back ? "Back" : "Cancel"}</button><button class="btn primary" data-a="rg-save">Register</button></div>`);
  setTimeout(() => $("#rg-name")?.focus(), 30);
}

/* schedules */
async function openSchedules(doctorId) {
  M = { kind: "sched", doctorId: doctorId || S.doctors[0]?.id, month: (S.date || TODAY).slice(0, 7), days: [], sel: null };
  await loadMonth();
}
async function loadMonth() { M.days = await api(`/schedules/${M.doctorId}?month=${M.month}`); renderSched(); }
function renderSched() {
  const s = M, [y, m] = s.month.split("-").map(Number), lead = new Date(y, m - 1, 1).getDay();
  const scheduleYears = Array.from({ length: 11 }, (_, i) => new Date().getFullYear() - 2 + i);
  const sel = s.days.find(d => d.date === s.sel);
  let editor = "";
  if (sel) {
    const base = sel.schedule || { start: S.clinic.start, end: S.clinic.end, limit_by: S.clinic.limit_by, limit_value: S.clinic.limit_value };
    editor = `<div class="hit choices"><div class="actions" style="justify-content:space-between;align-items:center"><h3>${niceDate(sel.date)}</h3>${sel.override ? `<span class="pill s-with_doctor">Changed</span>` : `<span class="pill s-soft">Clinic hours</span>`}</div>
      <div class="seg"><button data-a="sc-off" data-v="0" aria-pressed="${!sel.off}">Working</button><button data-a="sc-off" data-v="1" aria-pressed="${sel.off}">Off</button></div>
      <div id="so-lim" class="choices" ${sel.off ? 'style="opacity:.35;pointer-events:none"' : ""}>${limitBlock("so", base)}</div>
      <div class="foot"><button class="btn" data-a="sc-reset" ${sel.override ? "" : "disabled"}>Back to clinic hours</button><button class="btn primary" data-a="sc-save">Save day</button></div></div>`;
  }
  modal(`<div class="actions" style="justify-content:space-between;align-items:center"><h2>Doctor schedules</h2>
      <select class="input" style="width:auto" id="sc-doc" data-a="sc-doc">${S.doctors.map(d => `<option value="${d.id}" ${d.id === s.doctorId ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select></div>
    <div class="actions month-picker-wrap"><div class="month-picker"><span>Month</span><select data-a="sc-month-picker" aria-label="Choose schedule month">${Array.from({ length: 12 }, (_, i) => `<option value="${i + 1}" ${i + 1 === m ? "selected" : ""}>${new Date(2000, i, 1).toLocaleDateString("en-IN", { month: "long" })}</option>`).join("")}</select><select data-a="sc-year-picker" aria-label="Choose schedule year">${scheduleYears.map(n => `<option value="${n}" ${n === y ? "selected" : ""}>${n}</option>`).join("")}</select></div></div>
    <div class="cal">${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map(d => `<span class="dow">${d}</span>`).join("")}${"<span></span>".repeat(lead)}
      ${s.days.map(d => `<button class="${d.off ? "off" : ""} ${d.override ? "ovr" : ""}" data-a="sc-day" data-v="${d.date}" aria-pressed="${d.date === s.sel}" ${d.date < TODAY ? "disabled" : ""}><b>${Number(d.date.slice(8))}</b>${d.off ? "Off" : `${d.schedule.start}–${d.schedule.end}`}</button>`).join("")}</div>
    ${editor}
    <div class="foot"><button class="btn" data-a="close-refresh">Close</button></div>`, true);
}

/* members */
function openMember(kind, m) {
  M = { kind: "member", mkind: m?.kind || kind, m };
  const k = M.mkind;
  const screens = m ? m.screens : k === "doctor" ? ["patients", "consultation"] : ["operations", "patients"];
  const locked = m?.is_owner;
  modal(`<div class="mb-head"><div class="avatar big">${esc(initials(m?.name || "?"))}</div><div><h2>${m ? esc(m.name) : k === "doctor" ? "New doctor" : "New staff"}</h2>
      ${m ? `<span class="pill ${m.status === "active" ? "s-paid" : m.status === "invited" ? "s-waiting" : "s-no_show"}">${{ active: "Active", invited: "Invited", inactive: "Inactive" }[m.status]}</span>` : ""}</div></div>
    <div class="grid2"><label class="field">Name<input id="mb-name" value="${esc(m?.name || "")}"></label><label class="field">Phone<input id="mb-phone" value="${esc(m?.phone || "")}"></label></div>
    <label class="field">Email<input id="mb-email" type="email" value="${esc(m?.email || "")}"></label>
    <div class="grid2">${k === "doctor" ? `<label class="field">Department<input id="mb-spec" value="${esc(m?.speciality || "General medicine")}"></label>`
        : `<label class="field">Designation<select id="mb-spec">${["Receptionist", "Nurse", "IT", "Other"].map(d => `<option ${m?.designation === d ? "selected" : ""}>${d}</option>`).join("")}</select></label>`}</div>
    ${k === "doctor" ? `<div class="fee-row"><div class="seg"><button data-a="mb-fee-mode" data-v="clinic" aria-pressed="${m?.fee_override == null}">Clinic fee ₹${S.clinic.fee}</button><button data-a="mb-fee-mode" data-v="own" aria-pressed="${m?.fee_override != null}">Own fee</button></div>
      <label class="field" id="mb-fee-wrap" ${m?.fee_override == null ? "hidden" : ""}>Fee (₹)<input id="mb-fee" type="number" min="0" value="${m?.fee_override ?? S.clinic.fee}"></label></div>` : ""}
    <div class="field">Screens</div>
    <div class="days">${SCREENS.map(([key, , l]) => `<label><input type="checkbox" id="mb-s-${key}" ${screens.includes(key) || locked ? "checked" : ""} ${locked ? "disabled" : ""}>${l}</label>`).join("")}</div>
    <div class="toggles"><label class="choice"><input type="checkbox" id="mb-admin" ${m?.is_admin ? "checked" : ""} ${locked ? "disabled" : ""}><span><b>Admin access</b></span></label>
    ${m && !m.is_owner && m.status !== "invited" ? `<label class="choice"><input type="checkbox" id="mb-active" ${m.status === "active" ? "checked" : ""}><span><b>Active</b></span></label>` : ""}</div>
    <div class="foot">${m && !m.is_owner ? `<button class="btn danger" data-a="mb-remove" style="margin-right:auto">Remove</button>` : ""}${m?.status === "invited" ? `<button class="btn" data-a="copy-invite" data-v="${esc(m.invite_code)}">Copy invite link</button>` : ""}
      <button class="btn" data-a="close">Cancel</button><button class="btn primary" data-a="mb-save">${m ? "Save" : "Send invitation"}</button></div>`);
}
async function saveMember() {
  const { mkind, m } = M, own = $('[data-a="mb-fee-mode"][data-v="own"]')?.getAttribute("aria-pressed") === "true";
  const body = { name: $("#mb-name").value, phone: $("#mb-phone").value, email: $("#mb-email").value,
    screens: SCREENS.map(s => s[0]).filter(k => $("#mb-s-" + k).checked), is_admin: $("#mb-admin").checked,
    ...(mkind === "doctor" ? { speciality: $("#mb-spec").value, fee_override: own ? Number($("#mb-fee").value) || 0 : null } : { designation: $("#mb-spec").value }) };
  if (m) {
    if (!m.is_owner) body.kind = mkind;
    if (mkind === "doctor" && !own) body.clear_fee = true;
    if (m.is_owner) { delete body.screens; delete body.is_admin; }
    if ($("#mb-active")) body.status = $("#mb-active").checked ? "active" : "inactive";
    await api(`/members/${m.id}`, { method: "PATCH", body });
    toast("Saved");
  } else {
    const r = await api("/members", { body: { ...body, kind: mkind } });
    copyInvite(r.invite_code, `Invitation created for ${r.name}. Link copied.`);
  }
  S.doctors = await api("/doctors"); closeModal();
  if (OB.step === 4 && !S.clinic.onboarded) loadMembersStep(); else route();
}
function copyInvite(code, msg) {
  const link = `${location.origin}/#/invite/${code}`;
  navigator.clipboard?.writeText(link).then(() => toast(msg || "Invite link copied"), () => toast(link));
}

/* ---------- consultation ---------- */
/* ---------- consultation (doctor workspace, full-screen layout) ---------- */
const CTABS = [["brief", "Brief"], ["dictate", "Transcript"], ["note", "Note"]];
async function viewConsult(visitId, doctorParam, patientParam) {
  const isDoctor = S.me.kind === "doctor";
  const doctorId = Number(doctorParam) || (isDoctor ? S.me.id : S.doctors[0]?.id);
  if (!CTABS.some(t => t[0] === S.ctab)) S.ctab = "brief";
  S.cside = S.cside || "profile"; S.cq = S.cq ?? "";
  const load = async () => {
    const today = await api(`/consultation/today?doctor_id=${doctorId}`);
    const cur = visitId ? await api(`/visits/${visitId}`) : null;
    const pid = cur?.patient_id || Number(patientParam) || null;
    const profile = pid && S.me.screens.includes("patients") ? await api(`/patients/${pid}`) : null;
    const found = S.cq.trim() ? await api(`/patients?q=${encodeURIComponent(S.cq)}`) : [];
    S.data = { today, cur, profile, found, doctorId, pid };
    renderConsult();
    if (cur && cur.status === "with_doctor" && !cur.brief && !S.briefing) {
      S.briefing = true;
      run(async () => { try { await api(`/visits/${cur.id}/brief`, { body: {} }); } finally { S.briefing = false; } refreshConsult(); });
    }
  };
  S.reloadConsult = load;
  await run(load);
}
const refreshConsult = () => S.reloadConsult && run(S.reloadConsult);
function renderConsult() {
  const D = S.data, m = S.me, v = D.cur;
  const floatMic = v && ["waiting", "with_doctor"].includes(v.status) && S.ctab !== "note";
  $("#root").innerHTML = `<div class="cx">
    <header class="cx-top">
      <b class="cx-logo">Dictate</b>
      <span class="cx-chip">${esc(S.clinic.name)} · OPD</span>
      <nav class="cx-links">${SCREENS.filter(s => m.screens.includes(s[0]) && s[0] !== "consultation").map(([, h, l]) => `<a href="${h}">${l}</a>`).join("")}</nav>
      <span class="grow"></span>
      ${S.doctors.length > 1 || m.kind !== "doctor" ? `<select class="cx-select" id="cs-doc" data-a="cs-doc" aria-label="Doctor">${S.doctors.map(d => `<option value="${d.id}" ${d.id === D.doctorId ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select>` : ""}
      <span class="cx-chip solid">${m.kind === "doctor" ? "Doctor" : esc(m.designation || "Staff")}</span>
      <button class="cx-avatar" data-a="logout" title="Log out ${esc(m.name)}">${esc(initials(m.name))}</button>
    </header>
    <div class="cx-body ${S.rightCollapsed ? "wide" : ""}"><button class="cx-collapse" data-a="cs-collapse" aria-label="${S.rightCollapsed ? "Show side panel" : "Hide side panel"}" title="${S.rightCollapsed ? "Show side panel" : "Hide side panel"}"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${S.rightCollapsed ? "M15 6l-6 6 6 6" : "M9 6l6 6-6 6"}"/></svg></button>
      <aside class="cx-left">${leftCol()}</aside>
      <main class="cx-center" id="cx-center">${center()}${floatMic ? `<div class="cx-float">${micBtn(v)}</div>` : ""}</main>
      ${S.rightCollapsed ? "" : `<aside class="cx-right">${rightCol()}</aside>`}
    </div>
  </div>`;
  const tr = $(".transcript"); if (tr) tr.scrollTop = tr.scrollHeight;
  clearTimeout(S.docT);
  if (v?.documents.some(d => d.ai_status === "processing")) S.docT = setTimeout(refreshConsult, 2000);
}
function micBtn(v, small) {
  return `<button class="mic-dot ${small ? "sm" : ""} ${S.rec ? "on" : ""}" data-a="cs-mic" data-v="${v.id}" aria-label="${S.rec ? "Stop dictation" : "Dictate"}">${icon.mic}</button>${S.rec ? `<span class="mic-time" id="dock-timer">${S.recStart ? fmtClock(Date.now() - S.recStart) : "0:00"}</span>` : ""}`;
}
function leftCol() {
  const D = S.data, q = S.cq.trim().toLowerCase();
  const label = { waiting: "WAITING", with_doctor: "IN VISIT", done: "DONE" };
  const visits = D.today.visits.filter(v => !q || `${v.patient_name} ${v.uhid} ${v.phone}`.toLowerCase().includes(q));
  const inQueue = new Set(D.today.visits.map(v => v.patient_id));
  const others = D.found.filter(p => !inQueue.has(p.id));
  return `<h2 class="cx-kicker">Queue</h2>
    <input class="cx-input" id="cs-q" data-a="cs-q" placeholder="Name, phone or UHID" value="${esc(S.cq)}" autocomplete="off" aria-label="Search">
    <div class="cx-list">${visits.map(v => `<button data-a="cs-open" data-v="${v.id}" aria-current="${v.id === D.cur?.id}">
      <span class="cx-av">${esc(v.token_label)}</span><span class="cx-who"><b>${esc(v.patient_name)}${v.dob ? ", " + ageOf(v.dob) : ""}</b><small>${esc(v.uhid)} · ${esc(v.phone)}</small></span>
      <span class="cx-state st-${v.status}">${label[v.status] || ""}</span></button>`).join("")}
    ${others.map(p => `<button data-a="cs-patient" data-v="${p.id}" aria-current="${!D.cur && p.id === D.pid}">
      <span class="cx-av">${esc(initials(p.name))}</span><span class="cx-who"><b>${esc(p.name)}${p.dob ? ", " + ageOf(p.dob) : ""}</b><small>${esc(p.uhid)} · ${esc(p.phone)}</small></span></button>`).join("")}
    ${!visits.length && !others.length ? `<div class="cx-empty">—</div>` : ""}</div>`;
}
function center() {
  const D = S.data, v = D.cur;
  if (!v) {
    const p = D.profile;
    if (!p) return `<div class="cx-card cx-blank"></div>`;
    const past = p.visits.filter(x => x.status === "done");
    return `<div class="cx-card"><div class="cx-head"><div><h1>${esc(p.name)}${p.dob ? ", " + ageOf(p.dob) : ""}</h1>
      <p class="muted">${{ M: "Male", F: "Female", O: "Other" }[p.sex] || ""} · ${esc(p.uhid)}</p></div></div>
      <div class="cx-events">${past.map(x => `<div><span>•</span><span><b>${longDate(x.date)}</b> · ${esc(x.note?.soap?.A || x.doctor)}</span></div>`).join("") || `<span class="muted">—</span>`}</div></div>`;
  }
  const stateLabel = { waiting: "Waiting", with_doctor: "In visit", done: "Signed", booked: "Booked" }[v.status];
  return `<div class="cx-card">
    <div class="cx-head"><div><h1>${esc(v.patient_name)}${v.age != null ? ", " + v.age : ""}</h1>
</div>
      <span class="cx-status st-${v.status}"><i></i>${stateLabel}</span></div>
    <div class="cx-tabs">${CTABS.map(([k, l]) => `<button data-a="cs-tab" data-v="${k}" aria-pressed="${S.ctab === k}">${l}</button>`).join("")}</div>
    <div class="cx-pane">${({ brief: paneBrief, dictate: paneDictate, note: paneNote })[S.ctab](v)}</div>
  </div>`;
}
function paneBrief(v) {
  const items = v.brief?.items || [];
  const lead = items[0], rest = items.slice(1);
  if (!lead) return v.status === "with_doctor" ? `<p class="muted cx-lead">Preparing brief…</p>` : "";
  return `<p class="cx-lead">${esc(lead.text)}${citeBtns(lead.cites)}</p>
    ${rest.length ? `<div class="cx-events">${rest.map(i => `<div class="${i.flag ? "flag" : ""}"><span>${i.flag ? "⚠" : "•"}</span><span>${esc(i.text)}${citeBtns(i.cites)}</span></div>`).join("")}</div>` : ""}`;
}
function paneDictate(v) {
  return `<div class="live-text">${v.transcript.map(s => `<span class="live-seg" id="ev-${s.id}">${esc(s.text)} </span>`).join("")}<span class="live-interim" id="live-interim">${esc(S.interim || "")}</span>${S.rec ? `<span class="live-cursor"></span>` : ""}</div>`;
}
const seg = s => `<span class="live-seg" id="ev-${s.id}">${esc(s.text)} </span>`;
function paneNote(v) {
  const n = v.note, signed = n?.status === "signed";
  const canDraft = v.status === "with_doctor" && (v.transcript.length || v.documents.some(d => d.ai_status === "ready"));
  const live = ["waiting", "with_doctor"].includes(v.status);
  return `<div class="cx-sec"><span class="label">Clinical note</span><span class="actions" style="gap:8px;align-items:center">
      ${!signed && canDraft ? `<button class="cx-pill-btn" data-a="cs-draft" data-v="${v.id}">${n ? "Re-draft" : "✦ Draft with AI"}</button>` : ""}
      ${signed ? `<button class="cx-pill-btn" data-a="print" data-v="${n.id}">Print</button>` : ""}
      ${live ? micBtn(v, true) : ""}</span></div>
    ${signed ? `<div class="result">✓ Signed and saved · ${esc((n.signed_at || "").replace("T", " ").slice(0, 16))}</div>` : ""}
    ${n ? noteEditor(n, signed) : `<p class="muted">—</p>`}
    ${n && !signed ? `<div class="foot"><button class="btn" data-a="note-save" data-v="${n.id}">Save draft</button><button class="btn primary" data-a="note-sign" data-v="${n.id}">Sign &amp; complete</button></div>` : ""}`;
}
function rightCol() {
  const D = S.data, p = D.profile;
  const tabs = `<div class="cx-seg"><button data-a="cs-side" data-v="profile" aria-pressed="${S.cside !== "citations"}">Profile</button><button data-a="cs-side" data-v="citations" aria-pressed="${S.cside === "citations"}">Citations</button></div>`;
  if (S.cside === "citations") return `${tabs}${citations(D.cur)}`;
  if (!p) return `${tabs}<div class="cx-empty">—</div>`;
  return `${tabs}<div class="cx-rows">
    ${[["Name", p.name], ["Age", ageOf(p.dob)], ["Date of birth", p.dob ? longDate(p.dob) : "—"], ["Sex", { M: "Male", F: "Female", O: "Other" }[p.sex] || "—"], ["Phone", p.phone], ["UHID", p.uhid]].map(([k, val]) => `<div class="cx-row"><span>${k}</span><b>${esc(val)}</b></div>`).join("")}
    <div class="cx-row"><span>Visits</span><b>${p.visits.filter(x => x.status === "done").length}</b></div></div>`;
}
function sourceOf(v, id) {
  if (id.startsWith("T")) { const s = v.transcript.find(x => x.id === id); return s && { kind: "Transcript", text: `${s.speaker}: ${s.text}` }; }
  if (id.startsWith("D")) { const d = v.documents.find(x => "D" + x.id === id); return d && { kind: "Document", text: d.filename + (d.extracted?.findings?.length ? " — " + d.extracted.findings.slice(0, 3).map(f => `${f.name} ${f.value} ${f.unit || ""}`.trim()).join(", ") : "") }; }
  if (id.startsWith("N")) return { kind: "Earlier note", text: "Signed note from a previous visit" };
  return null;
}
function citations(v) {
  if (!v) return `<div class="cx-empty">—</div>`;
  const groups = [];
  const cites = v.note?.citations || {};
  ["S", "O", "A", "P"].forEach(k => { if (cites[k]?.length) groups.push([k, cites[k]]); });
  const briefIds = [...new Set((v.brief?.items || []).flatMap(i => i.cites || []))];
  if (briefIds.length) groups.push(["B", briefIds]);
  if (!groups.length) return `<div class="cx-empty">No citations</div>`;
  return `<div class="cite-list">${groups.map(([k, ids]) => `<div class="cite-item"><b>${k}</b><div class="cite-src">${ids.map(id => { const src = sourceOf(v, id); return src ? `<button data-a="cite" data-v="${id}"><small>${src.kind.toUpperCase()} · ${id}</small>${esc(src.text)}</button>` : ""; }).join("")}</div></div>`).join("")}</div>`;
}
const fmtClock = ms => { const t = Math.floor(ms / 1000); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`; };
function citeBtns(ids) { return (ids || []).map(c => `<button class="cite" data-a="cite" data-v="${c}">${c}</button>`).join(""); }
function noteEditor(n, ro) {
  const soap = n.content.soap, rx = n.content.rx;
  return `<div class="choices">${["S", "O", "A", "P"].map(k => `<div class="soap"><b>${k}</b><div>${ro ? `<div class="ro">${esc(soap[k] || "—")}</div>` : `<textarea id="soap-${k}">${esc(soap[k] || "")}</textarea>`}<div>${citeBtns(n.citations?.[k])}</div></div></div>`).join("")}</div>
    <div class="scroll"><table class="t" id="rx"><thead><tr><th>Medicine</th><th>Dose</th><th>Duration</th><th>Instructions</th>${ro ? "" : "<th></th>"}</tr></thead><tbody>
      ${rx.map((r, i) => `<tr>${["medicine", "dose", "duration", "instructions"].map(f => `<td>${ro ? esc(r[f]) : `<input data-f="${f}" value="${esc(r[f])}" aria-label="${f}">`}</td>`).join("")}${ro ? "" : `<td><button class="btn small ghost" data-a="rx-del" data-v="${i}" aria-label="Remove">✕</button></td>`}</tr>`).join("") || `<tr><td colspan="5" class="muted">—</td></tr>`}
    </tbody></table></div>${ro ? "" : `<div><button class="btn small" data-a="rx-add">+ Add medicine</button></div>`}`;
}
function readNote() {
  const soap = Object.fromEntries(["S", "O", "A", "P"].map(k => [k, $("#soap-" + k)?.value || ""]));
  const rx = [...document.querySelectorAll("#rx tbody tr")].filter(tr => tr.querySelector("input")).map(tr => Object.fromEntries([...tr.querySelectorAll("input")].map(i => [i.dataset.f, i.value])));
  return { soap, rx };
}
function startMic(visitId) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { refreshConsult(); return toast("Use Chrome to dictate", true); }
  const r = new SR(); r.lang = "en-IN"; r.continuous = true; r.interimResults = true;
  r.onresult = e => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      if (e.results[i].isFinal) { S.interim = ""; addLine(visitId, e.results[i][0].transcript); } else interim += e.results[i][0].transcript;
    }
    S.interim = interim; const el = $("#live-interim"); if (el) el.textContent = interim;
  };
  r.onend = () => { if (S.rec === r) { S.rec = null; S.recStart = null; clearInterval(S.recT); refreshConsult(); } };
  r.onerror = e => toast("Mic: " + e.error, true);
  S.rec = r; S.recStart = Date.now(); clearInterval(S.recT); S.recT = setInterval(() => { const t = $("#dock-timer"); if (t && S.recStart) t.textContent = fmtClock(Date.now() - S.recStart); }, 500); r.start(); refreshConsult();
}
async function addLine(visitId, text) {
  if (!text.trim()) return;
  await run(() => api(`/visits/${visitId}/transcript`, { body: { speaker: S.speaker || "Doctor", text } }));
  refreshConsult();
}

/* ---------- patients ---------- */
async function viewPatients(id) {
  S.pq = S.pq ?? "";
  await run(async () => {
    const list = await api(`/patients?q=${encodeURIComponent(S.pq)}`);
    const p = id ? await api(`/patients/${id}`) : null;
    view(`<div class="head"><div><h1>Patients</h1></div><span class="grow"></span><button class="btn primary" data-a="register">New patient</button></div>
      <input class="input" id="pt-q" placeholder="Search name, phone or UHID" value="${esc(S.pq)}" data-a="pt-q" autocomplete="off" aria-label="Search patients">
      <div class="cols" style="grid-template-columns:minmax(0,1fr) minmax(0,1.2fr)">
        <section class="panel scroll"><table class="t"><thead><tr><th>UHID</th><th>Name</th><th>Age</th><th>Phone</th></tr></thead><tbody>
          ${list.map(x => `<tr class="click ${x.id === id ? "selected" : ""}" data-a="pt-open" data-v="${x.id}"><td class="mono">${esc(x.uhid)}</td><td><b>${esc(x.name)}</b></td><td>${ageOf(x.dob)} ${esc(x.sex || "")}</td><td>${esc(x.phone)}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">—</td></tr>`}
        </tbody></table></section>
        ${p ? profile(p) : `<section class="panel"><span class="muted">—</span></section>`}
      </div>`);
  });
}
function profile(p) {
  const visits = p.visits.filter(v => ["done", "with_doctor", "waiting", "booked"].includes(v.status));
  return `<section class="panel" style="gap:14px"><div class="actions" style="justify-content:space-between;align-items:flex-start"><div><h2>${esc(p.name)}</h2>
      <div class="muted">${ageOf(p.dob)} ${esc(p.sex || "")} · <span class="mono">${esc(p.uhid)}</span> · ${esc(p.phone)}</div></div><button class="btn small" data-a="pt-edit" data-v="${p.id}">Edit</button></div>
    <span class="label">Visit history</span>
    ${visits.length ? `<div class="timeline">${visits.map(v => `<div class="tl"><div class="tl-head"><b>${longDate(v.date)}</b><span>${esc(v.doctor)}</span>${pill(v.status)}</div>
      <div class="items">${v.note ? `<button class="btn small" data-a="print" data-v="${v.note.id}">${v.note.status === "signed" ? "Note & prescription" : "Draft note"}</button>` : ""}
      ${v.documents.map(d => `<button class="btn small" data-a="open-doc" data-v="${d.id}">📄 ${esc(d.filename)}</button>`).join("")}</div>
      ${v.note?.soap?.A ? `<div class="muted" style="font-size:13.5px;margin-top:6px">${esc(v.note.soap.A)}</div>` : ""}</div>`).join("")}</div>` : `<div class="empty">—</div>`}
  </section>`;
}
function openPatientEdit(p) {
  M = { kind: "pedit", id: p.id };
  modal(`<h2>Edit patient</h2><div class="grid2"><label class="field">Name<input id="pe-name" value="${esc(p.name)}"></label><label class="field">Phone<input id="pe-phone" value="${esc(p.phone)}"></label></div>
    <div class="grid2"><label class="field">Date of birth<input id="pe-dob" type="date" value="${esc(p.dob || "")}"></label><label class="field">Sex<select id="pe-sex">${["M", "F", "O"].map(s => `<option ${p.sex === s ? "selected" : ""}>${s}</option>`).join("")}</select></label></div>
    <div class="foot"><button class="btn" data-a="close">Cancel</button><button class="btn primary" data-a="pe-save">Save</button></div>`);
}

/* ---------- administration ---------- */
async function viewAdmin(tab) {
  const editable = S.me.is_admin;
  const tabs = [["clinic", "Clinic details"], ["rules", "Clinic rules"], ["members", "Members"]];
  let body = "";
  if (tab === "clinic") body = `<section class="panel" style="max-width:640px"><label class="field">Clinic name<input id="ad-name" value="${esc(S.clinic.name)}"></label>
    <label class="field">Phone<input id="ad-phone" value="${esc(S.clinic.phone)}"></label><label class="field">Address<input id="ad-addr" value="${esc(S.clinic.address)}"></label>
        ${editable ? `<div><button class="btn primary" data-a="ad-details">Save</button></div>` : ""}</section>`;
  if (tab === "rules") body = `<section class="panel" style="max-width:700px">${rulesForm("ad", S.clinic)}
    ${editable ? `<div><button class="btn primary" data-a="ad-rules">Save rules</button></div>` : ""}</section>`;
  if (tab === "members") {
    const ms = await api("/members");
    body = `<section class="panel scroll"><table class="t members"><thead><tr><th>Name</th><th>Phone</th><th>Email</th><th>Role</th><th>Department</th><th>Status</th></tr></thead><tbody>
      ${ms.map(m => `<tr class="${editable ? "click" : ""}" ${editable ? `data-a="member-edit" data-v="${m.id}"` : ""}>
        <td><span class="mname"><span class="avatar sm">${esc(initials(m.name))}</span><b>${esc(m.name)}</b></span></td>
        <td>${esc(m.phone || "—")}</td><td class="muted">${esc(m.email)}</td>
        <td>${m.is_owner ? "Owner" : m.kind === "doctor" ? "Doctor" : "Staff"}</td>
        <td>${esc((m.kind === "doctor" ? m.speciality : m.designation) || "—")}</td>
        <td><span class="pill ${m.status === "active" ? "s-paid" : m.status === "invited" ? "s-waiting" : "s-no_show"}">${{ active: "Active", invited: "Invited", inactive: "Inactive" }[m.status]}</span></td></tr>`).join("")}
    </tbody></table></section>${editable ? `<div class="actions"><button class="btn primary" data-a="member-add" data-v="doctor">Add doctor</button><button class="btn" data-a="member-add" data-v="staff">Add staff</button></div>` : ""}`;
    S.members = ms;
  }
  view(`<div class="head"><div><h1>Administration</h1></div></div>
    <div class="actions admin-tabs">${tabs.map(([k, l]) => `<button class="btn" data-a="ad-tab" data-v="${k}" aria-pressed="${k === tab}">${l}</button>`).join("")}</div>${body}`);
}

/* ---------- events ---------- */
document.addEventListener("click", e => {
  const t = e.target.closest("[data-a]"); if (!t) return;
  const a = t.dataset.a, v = t.dataset.v;
  if (a === "scrim") { if (e.target === t && M?.kind !== "sched") closeModal(); return; }
  if (["lim", "bk-q", "pt-q", "cs-q", "bk-date", "bk-doc", "sc-doc", "sc-month-picker", "sc-year-picker", "cs-doc"].includes(a)) return;
  e.preventDefault();
  const D = S.data;
  run(async () => {
    switch (a) {
      case "logout": logout(); break;
      case "ob-next": await obNext(Number(v)); break;
      case "ob-finish": await obFinish(); break;
      case "ob-back": { const st = Number(v); if (st === 1) { if (S.me) { logout(); } else go("#/login"); } else viewOnboarding(st - 1); break; }
      case "accept-invite": { const r = await api("/invites/accept", { body: { code: v, password: $("#iv-pw").value } }); setToken(r.token); await boot(); go("#/"); break; }
      case "copy-invite": copyInvite(v); break;
      case "day": S.date = addDays(S.date, Number(v)); route(); break;
      case "open-doctor": go(`#/ops/doctor/${v}`); break;
      case "book": openBooking("book", { doctorId: v ? Number(v) : undefined }); break;
      case "walkin": openBooking("walk", { doctorId: v ? Number(v) : undefined }); break;
      case "book-another": openBooking("book", { doctorId: M.doctorId }); break;
      case "resched": { const vis = D.columns.booked.find(x => x.id === Number(v)); openBooking("resched", { visit: vis, doctorId: vis.doctor_id, patient: { id: vis.patient_id, name: vis.patient_name, uhid: vis.uhid, phone: vis.phone } }); break; }
      case "close": closeModal(); break;
      case "close-refresh": closeModal(); refresh(); break;
      case "bk-pick": M.patient = M.results.find(r => r.id === Number(v)); renderBooking(); break;
      case "bk-clear": M.patient = null; M.q = ""; M.results = []; renderBooking(); break;
      case "pick-token": M.token = Number(v); renderBooking(); break;
      case "bk-pay": M.pay = v; renderBooking(); break;
      case "bk-confirm": await confirmBooking(); break;
      case "register": openRegister(v); break;
      case "rg-back": { const back = M.back; M = back; renderBooking(); break; }
      case "rg-save": {
        const p = await api("/patients", { body: { name: $("#rg-name").value, phone: $("#rg-phone").value, dob: $("#rg-dob").value || null, sex: $("#rg-sex").value } });
        toast(p.similar?.length ? `Registered ${p.uhid}. Note: similar patient ${p.similar[0].name} (${p.similar[0].uhid}) exists.` : `Registered ${p.uhid}`);
        if (M.back) { const back = M.back; M = back; M.patient = p; renderBooking(); } else { closeModal(); location.hash.startsWith("#/consult") ? go(`#/consult?doctor=${S.data.doctorId}&patient=${p.id}`) : go(`#/patients/${p.id}`); }
        break; }
      case "arrive": openArrive([...D.columns.booked].find(x => x.id === Number(v))); break;
      case "pay": M.pay = v; document.querySelectorAll("#pay-seg button").forEach(b => b.setAttribute("aria-pressed", b.dataset.v === v)); break;
      case "arrive-paid": { const r = await api(`/visits/${M.v.id}/arrive`, { body: { payment_method: M.pay } }); closeModal(); toast(`${r.patient_name} · token ${r.token_label} · waiting`); refresh(); break; }
      case "cancel": { const vis = D.columns.booked.find(x => x.id === Number(v)); M = { kind: "cancel" };
        modal(`<h2>Cancel booking?</h2><p style="margin:0">${esc(vis.patient_name)} will be removed from the list. Their token becomes free again.</p><div class="foot"><button class="btn" data-a="close">Keep booking</button><button class="btn danger" data-a="cancel-go" data-v="${v}">Cancel booking</button></div>`); break; }
      case "cancel-go": await api(`/visits/${v}/cancel`, { body: {} }); closeModal(); toast("Booking cancelled"); refresh(); break;
      case "end-session": { const r = await api(`/operations/end-session?doctor_id=${v}&date=${S.date}`, { body: {} }); toast(`${r.no_shows} marked as no-show`); refresh(); break; }
      case "upload": openUpload(Number(v)); break;
      case "upload-go": { const f = $("#up-file").files[0]; if (!f) return toast("Choose a file first", true); await doUpload(M.visitId, f); closeModal(); location.hash.startsWith("#/consult") ? refreshConsult() : refresh(); break; }
      case "schedules": await openSchedules(D?.doctor?.id); break;
      case "sc-month": { const [y, m] = M.month.split("-").map(Number); const d = new Date(y, m - 1 + Number(v), 1); M.month = iso(d).slice(0, 7); M.sel = null; await loadMonth(); break; }
      case "sc-day": M.sel = v; renderSched(); break;
      case "sc-off": { const d = M.days.find(x => x.date === M.sel); d.off = v === "1"; d.schedule = d.schedule || null; renderSched(); break; }
      case "sc-save": { const d = M.days.find(x => x.date === M.sel);
        await api(`/schedules/${M.doctorId}/${M.sel}`, { method: "PUT", body: d.off ? { is_off: true } : { is_off: false, ...readLimit("so") } }); toast("Saved " + niceDate(M.sel)); await loadMonth(); break; }
      case "sc-reset": await api(`/schedules/${M.doctorId}/${M.sel}`, { method: "DELETE" }); await loadMonth(); break;
      case "member-add": openMember(v); break;
      case "member-edit": { const m = S.members.find(x => x.id === Number(v)); openMember(m.kind, m); break; }
      case "mb-fee-mode": { document.querySelectorAll('[data-a="mb-fee-mode"]').forEach(x => x.setAttribute("aria-pressed", x.dataset.v === v)); $("#mb-fee-wrap").hidden = v !== "own"; break; }
      case "mb-remove": { const m = M.m; const r = await api(`/members/${m.id}`, { method: "DELETE" }); toast(r.removed ? `${m.name} removed` : `${m.name} has visit history, set to inactive`); S.doctors = await api("/doctors"); closeModal(); route(); break; }
      case "mb-save": await saveMember(); break;
      case "ad-tab": go(`#/admin/${v}`); break;
      case "ad-details": S.clinic = await api("/clinic", { method: "PUT", body: { name: $("#ad-name").value, phone: $("#ad-phone").value, address: $("#ad-addr").value } }); toast("Saved"); route(); break;
      case "ad-rules": S.clinic = await api("/clinic/rules", { method: "PUT", body: readRules("ad") }); toast("Rules saved. Booking now follows them."); route(); break;
      case "pt-open": go(`#/patients/${v}`); break;
      case "pt-edit": openPatientEdit(await api(`/patients/${v}`)); break;
      case "pe-save": await api(`/patients/${M.id}`, { method: "PATCH", body: { name: $("#pe-name").value, phone: $("#pe-phone").value, dob: $("#pe-dob").value || null, sex: $("#pe-sex").value } }); closeModal(); toast("Saved"); route(); break;
      case "cs-tab": if (D.cur?.note && $("#soap-S")) D.cur.note.content = readNote(); S.ctab = v; renderConsult(); break;
      case "cs-side": S.cside = v; renderConsult(); break;
      case "cs-left": S.cleft = v; refreshConsult(); break;
      case "cs-patient": go(`#/consult?doctor=${D.doctorId}&patient=${v}`); break;
      case "cs-draft-go": await api(`/visits/${v}/note/draft`, { body: {} }); S.ctab = "note"; toast("Draft ready. Check it, then sign."); refreshConsult(); break;
      case "note-sign-ro": await api(`/notes/${v}`, { method: "PUT", body: D.cur.note.content }); await api(`/notes/${v}/sign`, { body: {} }); toast("Signed. Visit complete."); refreshConsult(); break;
      case "cs-next-mic": { const r = await api(`/consultation/next?doctor_id=${v}`, { body: {} }); S.ctab = "dictate"; await new Promise(res => { const once = () => { window.removeEventListener("hashchange", once); setTimeout(res, 300); }; window.addEventListener("hashchange", once); go(`#/consult/${r.id}?doctor=${v}`); }); startMic(r.id); break; }
      case "cs-collapse": S.rightCollapsed = !S.rightCollapsed; renderConsult(); break;
      case "cs-mic": {
        const cur = D.cur;
        if (S.rec) { const r = S.rec; S.rec = null; S.recStart = null; clearInterval(S.recT); r.stop(); refreshConsult(); break; }
        if (cur.status === "waiting") { await api(`/visits/${cur.id}/start`, { body: {} }); }
        if (S.ctab === "brief") S.ctab = "dictate";
        await S.reloadConsult(); startMic(cur.id); break; }
      case "cs-next": { const r = await api(`/consultation/next?doctor_id=${v}`, { body: {} }); S.ctab = "brief"; go(`#/consult/${r.id}?doctor=${v}`); break; }
      case "cs-open": go(`#/consult/${v}?doctor=${D.doctorId}`); break;
      case "cs-start": await api(`/visits/${v}/start`, { body: {} }); refreshConsult(); break;
      case "cs-brief": await api(`/visits/${v}/brief`, { body: {} }); toast("Brief updated"); refreshConsult(); break;
      case "cs-draft": await api(`/visits/${v}/note/draft`, { body: {} }); S.ctab = "note"; toast("Draft ready. Check it, edit, then sign."); refreshConsult(); break;
      case "mic": if (S.rec) { const r = S.rec; S.rec = null; S.recStart = null; clearInterval(S.recT); r.stop(); refreshConsult(); } else { S.ctab = "dictate"; startMic(Number(v)); } break;
      case "spk": S.speaker = v; document.querySelectorAll('[data-a="spk"]').forEach(b => b.setAttribute("aria-pressed", b.dataset.v === v)); break;
      case "dict-add": { const i = $("#dict-in"); await addLine(Number(v), i.value); break; }
      case "rx-add": { const n = D.cur.note; n.content = readNote(); n.content.rx.push({ medicine: "", dose: "", duration: "", instructions: "" }); rerenderNote(); break; }
      case "rx-del": { const n = D.cur.note; n.content = readNote(); n.content.rx.splice(Number(v), 1); rerenderNote(); break; }
      case "note-save": await api(`/notes/${v}`, { method: "PUT", body: readNote() }); toast("Draft saved"); refreshConsult(); break;
      case "note-sign": await api(`/notes/${v}`, { method: "PUT", body: readNote() }); await api(`/notes/${v}/sign`, { body: {} }); toast("Signed. Visit complete."); refreshConsult(); break;
      case "print": window.open(`/api/notes/${v}/print?token=${encodeURIComponent(S.token)}`, "_blank"); break;
      case "open-doc": { const res = await fetch(`/api/documents/${v}/file`, { headers: { Authorization: "Bearer " + S.token } }); window.open(URL.createObjectURL(await res.blob()), "_blank"); break; }
      case "cite": { const el = document.getElementById("ev-" + v); if (el) { el.scrollIntoView({ behavior: "smooth", block: "nearest" }); el.classList.add("hl"); setTimeout(() => el.classList.remove("hl"), 1800); } else toast(v.startsWith("N") ? "From an earlier signed note (see Patients → history)" : "Source: " + v); break; }
    }
  });
});
function rerenderNote() { const c = $("#cx-center"); if (c) c.innerHTML = center(); }
document.addEventListener("input", e => {
  const a = e.target.dataset?.a;
  if (a === "bk-q") searchPatients(e.target.value);
  if (a === "cs-q") { S.cq = e.target.value; clearTimeout(S.cqt); S.cqt = setTimeout(async () => { await run(S.reloadConsult); const q = $("#cs-q"); if (q) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); } }, 220); }
  if (a === "pt-q") { S.pq = e.target.value; clearTimeout(S.pqt); S.pqt = setTimeout(async () => { await viewPatients(Number(location.hash.split("/")[2]) || null); const q = $("#pt-q"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }, 200); }
});
document.addEventListener("change", e => {
  const a = e.target.dataset?.a;
  if (a === "ops-date") { S.date = e.target.value || TODAY; route(); }
  if (a === "bk-date") { M.date = e.target.value || TODAY; run(loadAvail); }
  if (a === "bk-doc") { M.doctorId = Number(e.target.value); run(loadAvail); }
  if (a === "sc-doc") { M.doctorId = Number(e.target.value); M.sel = null; run(loadMonth); }
  if (a === "sc-month-picker" || a === "sc-year-picker") {
    const month = a === "sc-month-picker" ? Number(e.target.value) : Number(M.month.slice(5, 7));
    const year = a === "sc-year-picker" ? Number(e.target.value) : Number(M.month.slice(0, 4));
    M.month = `${year}-${String(month).padStart(2, "0")}`; M.sel = null; run(loadMonth);
  }
  if (a === "cs-doc") { S.ctab = "brief"; go(`#/consult?doctor=${e.target.value}`); }
  if (a === "lim") { const p = e.target.dataset.p, vals = readLimit(p); $(`#${p}-lim`).innerHTML = limitBlock(p, vals); }
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && M) { closeModal(); if (M === null) refresh(); }
  if (e.key === "Enter" && e.target.id === "dict-in") { e.preventDefault(); run(() => addLine(Number(e.target.dataset.v), e.target.value)); }
});

/* ---------- enhancers: labels inside boxes, rounded dropdowns, calendar picker ---------- */
const chevron = '<svg class="dd-chev" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 10l5 5 5-5"/></svg>';
const calIcon = '<svg class="dd-chev" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="5" width="17" height="15" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/></svg>';
function textOf(el) { return [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join("").trim(); }
function enhance(root) {
  root.querySelectorAll("label.field:not(.fl)").forEach(f => {
    const ctl = f.querySelector("input, select, textarea"); if (!ctl) return;
    const text = textOf(f); [...f.childNodes].forEach(n => { if (n.nodeType === 3) n.remove(); });
    f.classList.add("fl");
    if (!ctl.getAttribute("aria-label")) ctl.setAttribute("aria-label", text);
    const span = document.createElement("span"); span.className = "fl-label"; span.textContent = text; f.prepend(span);
  });
  root.querySelectorAll("div.field:not(.fl)").forEach(f => {
    if (f.querySelector("input, select, textarea")) return;
    const text = f.textContent.trim(), next = f.nextElementSibling; f.classList.add("fl");
    if (!next) return;
    if (next.matches("input")) { f.remove(); return; }
    const span = document.createElement("span"); span.className = "grp-label"; span.textContent = text;
    next.prepend(span); next.classList.add("has-grp"); f.remove();
  });
  root.querySelectorAll("select:not([data-dd])").forEach(makeDropdown);
  root.querySelectorAll('input[type="date"]:not([data-dd])').forEach(makeDatePicker);
  root.querySelectorAll('input[type="time"]:not([data-dd])').forEach(makeTimePicker);
}
function closeMenus(except) { document.querySelectorAll(".dd.open").forEach(d => d !== except && !d.contains(except) && d.classList.remove("open")); }
function makeDropdown(sel) {
  sel.dataset.dd = "1";
  const wrap = document.createElement("div");
  wrap.className = "dd" + (sel.classList.contains("cx-select") ? " dark" : "") + (sel.style.width === "auto" ? " inline" : "");
  const btn = document.createElement("button"); btn.type = "button"; btn.className = "dd-btn"; btn.setAttribute("aria-haspopup", "listbox");
  if (sel.disabled) btn.disabled = true;
  const menu = document.createElement("div"); menu.className = "dd-menu"; menu.setAttribute("role", "listbox");
  const paint = () => {
    const o = sel.options[sel.selectedIndex];
    btn.innerHTML = `<span class="dd-val">${esc(o ? o.text : "")}</span>${chevron}`;
    menu.innerHTML = [...sel.options].map((op, i) => `<button type="button" role="option" class="dd-opt" data-i="${i}" aria-selected="${i === sel.selectedIndex}">${esc(op.text)}</button>`).join("");
  };
  paint();
  sel.parentNode.insertBefore(wrap, sel); wrap.append(btn, menu, sel); sel.classList.add("dd-native"); sel.tabIndex = -1;
  btn.addEventListener("click", e => { e.preventDefault(); e.stopPropagation(); closeMenus(wrap); wrap.classList.toggle("open"); menu.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" }); });
  menu.addEventListener("click", e => {
    const o = e.target.closest(".dd-opt"); if (!o) return; e.preventDefault(); e.stopPropagation();
    sel.selectedIndex = Number(o.dataset.i); paint(); wrap.classList.remove("open"); btn.focus();
    sel.dispatchEvent(new Event("change", { bubbles: true }));
  });
  wrap.addEventListener("keydown", e => {
    if (e.key === "Escape" && wrap.classList.contains("open")) { e.stopPropagation(); wrap.classList.remove("open"); btn.focus(); }
    if (["ArrowDown", "ArrowUp"].includes(e.key)) {
      e.preventDefault(); const opts = [...menu.querySelectorAll(".dd-opt")], i = opts.indexOf(document.activeElement);
      if (!wrap.classList.contains("open")) { wrap.classList.add("open"); (opts[sel.selectedIndex] || opts[0])?.focus(); return; }
      opts[Math.max(0, Math.min(opts.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))]?.focus();
    }
  });
}
function makeDatePicker(inp) {
  inp.dataset.dd = "1";
  const wrap = document.createElement("div"); wrap.className = "dd date" + (inp.classList.contains("top-date") ? " top-date" : "");
  const btn = document.createElement("button"); btn.type = "button"; btn.className = "dd-btn";
  const menu = document.createElement("div"); menu.className = "dd-menu cal-pop";
  let view = (inp.value || TODAY).slice(0, 7);
  const paintBtn = () => { btn.innerHTML = `<span class="dd-val">${inp.value ? niceDate(inp.value) : "Select date"}</span>${calIcon}`; };
  const paintCal = () => {
    const [y, m] = view.split("-").map(Number), first = new Date(y, m - 1, 1), days = new Date(y, m, 0).getDate();
    const minYear = inp.min ? Number(inp.min.slice(0, 4)) : 1900;
    const maxYear = inp.max ? Number(inp.max.slice(0, 4)) : new Date().getFullYear() + 10;
    const years = Array.from({ length: Math.max(1, maxYear - minYear + 1) }, (_, i) => minYear + i);
    let cells = "<span></span>".repeat(first.getDay());
    for (let d = 1; d <= days; d++) {
      const ds = `${view}-${String(d).padStart(2, "0")}`, off = (inp.min && ds < inp.min) || (inp.max && ds > inp.max);
      cells += `<button type="button" class="cal-d ${ds === TODAY ? "today" : ""}" data-d="${ds}" aria-pressed="${ds === inp.value}" ${off ? "disabled" : ""}>${d}</button>`;
    }
    menu.innerHTML = `<div class="cal-head"><select data-cal="month" aria-label="Month">${Array.from({ length: 12 }, (_, i) => `<option value="${i + 1}" ${i + 1 === m ? "selected" : ""}>${new Date(2000, i, 1).toLocaleDateString("en-IN", { month: "long" })}</option>`).join("")}</select><select data-cal="year" aria-label="Year">${years.map(n => `<option value="${n}" ${n === y ? "selected" : ""}>${n}</option>`).join("")}</select></div>
      <div class="cal-grid">${["S", "M", "T", "W", "T", "F", "S"].map(x => `<i>${x}</i>`).join("")}${cells}</div>`;
  };
  paintBtn(); paintCal();
  inp.parentNode.insertBefore(wrap, inp); wrap.append(btn, menu, inp); inp.classList.add("dd-native"); inp.tabIndex = -1;
  btn.addEventListener("click", e => { e.preventDefault(); e.stopPropagation(); closeMenus(wrap); view = (inp.value || TODAY).slice(0, 7); paintCal(); wrap.classList.toggle("open"); });
  menu.addEventListener("click", e => {
    e.preventDefault(); e.stopPropagation();
    const nav = e.target.closest(".cal-nav");
    if (nav) { const [y, m] = view.split("-").map(Number); view = iso(new Date(y, m - 1 + Number(nav.dataset.m), 1)).slice(0, 7); paintCal(); return; }
    const d = e.target.closest(".cal-d"); if (!d || d.disabled) return;
    inp.value = d.dataset.d; paintBtn(); wrap.classList.remove("open");
    inp.dispatchEvent(new Event("change", { bubbles: true }));
  });
  menu.addEventListener("change", e => {
    const part = e.target.dataset.cal; if (!part) return;
    const [y, m] = view.split("-").map(Number);
    view = `${part === "year" ? e.target.value : y}-${String(part === "month" ? e.target.value : m).padStart(2, "0")}`;
    paintCal();
  });
  wrap.addEventListener("keydown", e => { if (e.key === "Escape" && wrap.classList.contains("open")) { e.stopPropagation(); wrap.classList.remove("open"); } });
}
function makeTimePicker(inp) {
  inp.dataset.dd = "1";
  const sel = document.createElement("select");
  const times = []; for (let m = 0; m < 24 * 60; m += 15) times.push(`${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`);
  if (inp.value && !times.includes(inp.value)) times.push(inp.value), times.sort();
  sel.innerHTML = times.map(t => `<option value="${t}" ${t === inp.value ? "selected" : ""}>${t}</option>`).join("");
  inp.type = "hidden"; inp.after(sel);
  sel.addEventListener("change", () => { inp.value = sel.value; inp.dispatchEvent(new Event("change", { bubbles: true })); });
  makeDropdown(sel);
}
document.addEventListener("click", e => { if (!e.target.closest(".dd")) closeMenus(); }, true);
let enhanceQueued = false;
new MutationObserver(() => { if (enhanceQueued) return; enhanceQueued = true; requestAnimationFrame(() => { enhanceQueued = false; enhance(document.body); }); })
  .observe(document.body, { childList: true, subtree: true });

boot();
