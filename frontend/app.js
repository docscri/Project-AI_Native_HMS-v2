/* Hash routes, one state object, event delegation on data-a. */
"use strict";

const S = { token: null, me: null, clinic: null, doctors: [], date: null, data: null, timer: null, rec: null };
try { S.token = localStorage.getItem("clinic.token"); } catch {}

/* helpers */
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
const rupees = n => "₹" + Number(n || 0).toLocaleString("en-IN");
const hoursOf = s => (s.sessions?.length ? s.sessions : [s]).map(x => `${x.start}–${x.end}`).join(" · ");
const openReceipt = id => window.open(`/api/visits/${id}/receipt?token=${encodeURIComponent(S.token)}`, "_blank");
const CANCEL_REASONS = ["Patient asked", "Doctor unavailable", "Booked by mistake"];
const RESCHED_REASONS = ["Patient asked", "Doctor unavailable", "Clinic change"];
const REFUND_REASONS = ["Charged twice", "Visit not done", "Fee changed"];
const reasonChips = (list, cur, a) => `<div class="seg reason-seg">${list.map(r => `<button data-a="${a}" data-v="${esc(r)}" aria-pressed="${r === cur}">${r}</button>`).join("")}</div>`;
const feeTile = fee => `<div class="tk fee"><small>Fee</small><b id="pay-due">${rupees(fee)}</b></div>`;
function payBlock(fee, pay, feeShown) {
  return `<div class="pay-box">${feeShown ? "" : `<div class="tiles-row">${feeTile(fee)}</div>`}
    <div class="pay-line"><div class="seg" id="pay-seg">${[["cash", "Cash"], ["upi", "UPI"], ["card", "Card"], ["waive", "Waive"]].map(([m, l]) => `<button data-a="pay" data-v="${m}" aria-pressed="${m === pay}">${l}</button>`).join("")}</div>
    <label class="field" id="pay-disc-wrap" ${pay === "waive" ? "hidden" : ""}>Discount (₹)<input type="number" min="0" max="${fee}" id="pay-disc" data-a="pay-disc" data-fee="${fee}" value=""></label></div></div>`;
}
function readPay(fee) {
  const pay = M.pay, why = $("#pay-why")?.value.trim() || "";
  if (pay === "waive") return { payment_method: null, discount: fee, discount_reason: why };
  return { payment_method: pay, discount: Number($("#pay-disc")?.value) || 0, discount_reason: why };
}
const paidDone = (title, v) => `<h2>${title}</h2><div class="result">${esc(v.patient_name)}${v.token_label ? ` · token ${v.token_label}` : ""} · ${rupees(v.amount_paid)}${v.payment_method ? " · " + v.payment_method.toUpperCase() : ""}</div>
  <div class="foot"><button class="btn" data-a="receipt" data-v="${v.id}">Receipt</button><button class="btn primary" data-a="close-refresh">Done</button></div>`;
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
  if (res.status === 401 && !opts.quiet && S.token) { endLocal(); throw new Error(data.detail || "Session ended. Log in again."); }
  if (!res.ok) {
    const d = data.detail;
    const err = new Error(Array.isArray(d) ? `Check ${String(d[0]?.loc?.slice(-1)[0] || "the form").replace(/_/g, " ")}.` : d || "Something went wrong.");
    err.status = res.status; throw err;
  }
  return data;
}
function toast(msg, err) {
  $("#toast").innerHTML = `<div class="toast ${err ? "err" : ""}" role="status">${esc(msg)}</div>`;
  clearTimeout(toast.t); toast.t = setTimeout(() => ($("#toast").innerHTML = ""), err ? 4200 : 2600);
}
async function run(fn) { try { return await fn(); } catch (e) { toast(e.message, true); } }
function modal(html, wide) {
  const old = $("#modal .modal"), top = old ? old.scrollTop : 0, scrim = $("#modal .scrim")?.scrollTop || 0;
  $("#modal").innerHTML = html ? `<div class="scrim" data-a="scrim"><div class="modal ${wide ? "wide" : ""} ${old ? "re" : ""}" role="dialog" aria-modal="true">${/data-a="close(-refresh)?"[^>]*>(Cancel|Close)</.test(html) ? "" : `<button class="icon-x modal-x" data-a="close-refresh" aria-label="Close">×</button>`}${html}</div></div>` : "";
  if (html && old) { $("#modal .modal").scrollTop = top; $("#modal .scrim").scrollTop = scrim; }
}
const closeModal = () => { modal(""); M = null; };
const go = h => { if (location.hash === h) route(); else location.hash = h; };
function setToken(t) { S.token = t; try { t ? localStorage.setItem("clinic.token", t) : localStorage.removeItem("clinic.token"); } catch {} }
function endLocal() { setToken(null); S.me = null; stopTimers(); closeModal(); go("#/login"); }
async function logout() { if (S.token) await fetch("/api/auth/logout", { method: "POST", headers: { Authorization: "Bearer " + S.token } }).catch(() => {}); endLocal(); }
function stopTimers() { clearInterval(S.timer); S.timer = null; clearTimeout(S.docT); if (S.rec) { const r = S.rec; S.rec = null; try { r.stop(); } catch {} } S.recState = null; clearInterval(S.recT); }

/* routing */
const SCREENS = [["operations", "#/ops", "Operations", icon.ops], ["patients", "#/patients", "Patients", icon.patients],
  ["consultation", "#/consult", "Consultation", icon.consult], ["administration", "#/admin", "Administration", icon.admin]];

async function boot() {
  if (!S.token) return route();
  await run(async () => {
    const r = await api("/me");
    S.me = r.member; S.clinic = r.clinic; S.doctors = await api("/doctors");
    api("/dictation").then(d => { S.dictBy = d.provider; S.aiOn = d.ai; }, () => {});
  });
  route();
}
window.addEventListener("hashchange", route);

async function route() {
  stopTimers();
  S.gen = (S.gen || 0) + 1;
  const [path, query] = (location.hash.slice(1) || "/").split("?");
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "invite") return viewInvite(parts[1]);
  if (parts[0] === "reset") return viewReset(parts[1]);
  if (parts[0] === "forgot" && !S.me) return viewForgot();
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
  if (parts[0] === "admin") return viewAdmin(parts[1] === "members" ? "team" : parts[1] || "clinic", parts[2]);
}

function shell(active) {
  const m = S.me;
  if ($("#view") && S.shellFor === active) return;   // keep the frame to avoid flash/scroll
  S.shellFor = active;
  $("#root").innerHTML = `<div class="app">
    <nav class="nav" aria-label="Main">
      <div class="brand"><b>Dictate</b><span>${esc(S.clinic.name)}</span></div>
      ${SCREENS.filter(s => m.screens.includes(s[0])).map(([k, h, l, i]) => `<a href="${h}" ${h.slice(2) === active ? 'aria-current="page"' : ""}>${i}${l}</a>`).join("")}
      <div class="me"><button class="me-open" data-a="account" title="Account"><span class="avatar">${esc(firstName(m.name)[0].toUpperCase())}</span><b>${esc(firstName(m.name))}</b></button><button class="logout-icon" data-a="logout" aria-label="Log out" title="Log out"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 17l5-5-5-5M15 12H3M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4"/></svg></button></div>
    </nav>
    <div class="stage"><main class="surface" id="view"><div class="muted">Loading…</div></main></div></div>`;
}
const pageKey = () => location.hash.replace(/^(#\/patients)\/\d+/, "$1");
const view = (html, g) => {
  if (g !== undefined && g !== S.gen) return;
  const v = $("#view"); if (!v) return;
  const same = S.viewKey === pageKey(), top = v.scrollTop;
  v.innerHTML = html;
  v.scrollTop = same ? top : 0;
  S.viewKey = pageKey();
};
const stale = g => g !== S.gen;

/* login, onboarding, invite */
const WAVE_H = [14, 26, 40, 22, 48, 34, 18, 52, 30, 44, 20, 38, 54, 28, 16, 42, 50, 24, 36, 46, 18, 32, 52, 26, 40, 20, 48, 30];
const wave = () => `<div class="login-wave" aria-hidden="true">${Array.from({ length: 64 }, (_, i) => `<span style="--h:${WAVE_H[(i * 11) % 28]}px;animation-delay:${(i % 28) * 40}ms"></span>`).join("")}</div>`;
const arrowRight = '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>';
const arrowLeft = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M11 6l-6 6 6 6"/></svg>';
function authPage(inner, cls = "") {
  $("#root").innerHTML = `<main class="login-screen ${cls}"><div class="login-brand">Dictate</div>${wave()}<section class="login-stage">${inner}</section></main>`;
}
function viewLogin() {
  authPage(`<div class="login-card login-home"><form id="login" class="login-fields" novalidate>
      <input class="login-input" id="lg-email" type="email" placeholder="Email" aria-label="Email" autocomplete="username">
      <div class="login-pw"><input class="login-input" id="lg-pw" type="password" placeholder="Password" aria-label="Password" autocomplete="current-password">
        <button class="login-submit glow" type="submit" aria-label="Sign in">${arrowRight}</button></div>
    </form>
    <p class="login-footer"><a class="login-link" href="#/signup">Create account</a><span class="dot-sep">·</span><a class="login-link" href="#/forgot">Forgot password?</a></p></div>`);
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
    <div class="grid2"><label class="field">Email<input id="ob-email" type="email" value="${esc(me.email || "")}"></label><label class="field">Phone<input id="ob-phone" value="${esc(me.phone || "")}"></label></div>
    <label class="field">Password<input id="ob-pw" type="password" autocomplete="new-password"></label>
    <label class="choice"><input type="checkbox" id="ob-doc" ${me.kind === "staff" ? "" : "checked"}><span><b>I am also a doctor here</b></span></label>`);
  if (step === 2) obFrame(2, `<h1>Your clinic</h1>
    <label class="field">Clinic name<input id="ob-cname" value="${esc(S.clinic.name)}"></label>
    <label class="field">Phone<input id="ob-cphone" value="${esc(S.clinic.phone)}"></label>
    <label class="field">Address<input id="ob-caddr" value="${esc(S.clinic.address)}"></label>`);
  if (step === 3) obFrame(3, `<h1>Clinic rules</h1>${rulesForm("ob", S.clinic)}`);
  if (step === 4) loadMembersStep();
}
async function loadMembersStep() {
  const ms = (await api("/members")).filter(m => !m.is_owner);
  S.members = ms;
  obFrame(4, `<h1>Your team</h1>
    <div class="ob-team"><button class="btn" data-a="member-add" data-v="doctor">+ Add doctor</button><button class="btn" data-a="member-add" data-v="staff">+ Add staff</button></div>
    ${ms.length ? `<div class="rows">${ms.map(m => `<div class="r q"><b>${m.kind === "doctor" ? "Doctor" : esc(m.designation)}</b><span class="who">${esc(m.name)}</span>${inviteLink(m)}</div>`).join("")}</div>` : ""}`, "Finish setup");
}
const inviteLink = m => m.status === "invited" ? `<button class="btn small" data-a="renew-invite" data-v="${m.id}">Invite link</button>` : `<span class="pill s-paid">Active</span>`;

async function obNext(step) {
  if (step === 1 && S.me) { S.me = await api("/onboarding/owner", { method: "PUT", body: { name: $("#ob-name").value, email: $("#ob-email").value, phone: $("#ob-phone").value, password: $("#ob-pw").value, is_doctor: $("#ob-doc").checked } }); S.doctors = await api("/doctors"); return viewOnboarding(2); }
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
    authPage(`<div class="login-card"><h1 class="login-title">${esc(inv.clinic)}</h1><p class="login-sub">${esc(inv.name)}</p>
      <form class="login-pw" data-form="accept-invite" data-v="${esc(code)}"><input class="login-input" id="iv-pw" type="password" placeholder="New password · 8+ letters & numbers" aria-label="New password" autocomplete="new-password">
      <button class="login-submit glow" type="submit" aria-label="Join">${arrowRight}</button></form></div>`);
  }).then(r => { if (!$(".login-card")) authPage(`<div class="login-card"><h1 class="login-title">Link not valid</h1><p class="login-sub">Ask the clinic for a new invitation.</p><p class="login-footer"><a class="login-link" href="#/login">Back</a></p></div>`); });
}
function viewForgot() {
  authPage(`<div class="login-card"><h1 class="login-title">Reset password</h1>
    <form class="login-pw" data-form="forgot"><input class="login-input" id="fg-email" type="email" placeholder="Email" aria-label="Email" autocomplete="username">
    <button class="login-submit glow" type="submit" aria-label="Send reset link">${arrowRight}</button></form>
    <p class="login-footer"><a class="login-link" href="#/login">Back</a></p></div>`);
}
function viewReset(code) {
  authPage(`<div class="login-card"><h1 class="login-title">New password</h1>
    <form class="login-pw" data-form="reset" data-v="${esc(code)}"><input class="login-input" id="rs-pw" type="password" placeholder="8+ letters & numbers" aria-label="New password" autocomplete="new-password">
    <button class="login-submit glow" type="submit" aria-label="Save password">${arrowRight}</button></form>
    <p class="login-footer"><a class="login-link" href="#/login">Back</a></p></div>`);
}
document.addEventListener("submit", e => {
  const f = e.target.closest("[data-form]"); if (!f) return;
  e.preventDefault(); const kind = f.dataset.form, v = f.dataset.v;
  $(".login-screen")?.classList.add("busy");
  run(async () => {
    try {
      if (kind === "accept-invite") { const r = await api("/invites/accept", { body: { code: v, password: $("#iv-pw").value } }); setToken(r.token); await boot(); go("#/"); }
      if (kind === "reset") { const r = await api("/auth/reset", { body: { code: v, password: $("#rs-pw").value } }); setToken(r.token); await boot(); toast("Password updated"); go("#/"); }
      if (kind === "forgot") {
        const r = await api("/auth/forgot", { body: { email: $("#fg-email").value } });
        authPage(`<div class="login-card"><h1 class="login-title">Check your email</h1><p class="login-sub">${r.email_sent ? "If this email has an account, a reset link is on its way." : "Ask your clinic admin for a reset link."}</p>
          <p class="login-footer"><a class="login-link" href="#/login">Back</a></p></div>`);
      }
    } finally { $(".login-screen")?.classList.remove("busy"); }
  });
});

/* clinic rules form */
const sessionsOf = v => v.sessions?.length ? v.sessions.map(x => ({ start: x.start, end: x.end })) : [{ start: v.start || "09:00", end: v.end || "13:00" }];
function limitBlock(p, v) {
  const ss = sessionsOf(v), f = ss[0];
  const l = limitsOf(f.start, f.end, v.limit_by, v.limit_value);
  const patientValue = v.limit_by === "patients" ? v.limit_value : Math.max(1, l.max);
  const minuteValue = v.limit_by === "minutes" ? v.limit_value : Math.max(1, l.per);
  const byP = v.limit_by === "patients";
  return `${ss.map((x, i) => `<div class="sess-row"><div class="grid2"><label class="field">${ss.length > 1 ? `Session ${i + 1} start` : "Start"}<input type="time" id="${p}-s${i}" value="${x.start}" data-a="lim" data-p="${p}"></label><label class="field">End<input type="time" id="${p}-e${i}" value="${x.end}" data-a="lim" data-p="${p}"></label></div>
      ${ss.length > 1 ? `<button class="icon-x" data-a="ses-del" data-p="${p}" data-v="${i}" aria-label="Remove session">×</button>` : ""}</div>`).join("")}
    ${ss.length < 3 ? `<div><button class="btn small" data-a="ses-add" data-p="${p}">+ Add session</button></div>` : ""}
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
  const sessions = [];
  for (let i = 0; $(`#${p}-s${i}`); i++) sessions.push({ start: $(`#${p}-s${i}`).value, end: $(`#${p}-e${i}`).value });
  return { sessions, limit_by: by, limit_value: Number(el?.value) || 1 };
}
function rulesForm(p, c) {
  const dn = ["S", "M", "T", "W", "T", "F", "S"], full = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  return `<label class="field">Consultation fee (₹)<input type="number" min="0" id="${p}-fee" value="${c.fee}"></label>
    <div class="rule-group"><span class="rule-label">Working days</span><div class="day-dots">${dn.map((d, i) => `<label title="${full[i]}"><input type="checkbox" id="${p}-d${i}" ${c.days.includes(i) ? "checked" : ""} aria-label="${full[i]}"><span>${d}</span></label>`).join("")}</div></div>
    <div class="rule-group"><span class="rule-label">Sessions</span><div id="${p}-lim" class="rule-stack">${limitBlock(p, c)}</div></div>
    <div class="rule-group"><span class="rule-label">Token</span><div class="pick-seg">
      <label><input type="radio" name="${p}-tok" value="booking" ${c.token_timing === "booking" ? "checked" : ""}><span>At booking</span></label>
      <label><input type="radio" name="${p}-tok" value="arrival" ${c.token_timing === "arrival" ? "checked" : ""}><span>On arrival</span></label></div></div>`;
}
const readRules = p => ({ fee: Number($(`#${p}-fee`).value) || 0, days: [0, 1, 2, 3, 4, 5, 6].filter(i => $(`#${p}-d${i}`).checked),
  ...readLimit(p), token_timing: $(`input[name="${p}-tok"]:checked`).value });

/* operations */
async function viewOps() {
  const g = S.gen;
  S.date = S.date || TODAY;
  S.vf = S.vf || { q: "", st: "", doc: "" };
  const load = async () => {
    if (document.activeElement?.id === "vf-q") return;
    const d = await api(`/operations/day?date=${S.date}`);
    if (stale(g)) return;
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
            <div class="vf-bar"><input class="input" id="vf-q" placeholder="Search name, phone or UHID" value="${esc(S.vf.q)}" data-a="vf-q" autocomplete="off">
              ${S.doctors.length > 1 ? `<select class="input" data-a="vf-doc" aria-label="Doctor"><option value="">All doctors</option>${S.doctors.map(x => `<option value="${x.id}" ${String(x.id) === S.vf.doc ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select>` : ""}</div>
            <div class="seg vf-seg">${VF.map(([k, l]) => `<button data-a="vf-st" data-v="${k}" aria-pressed="${k === S.vf.st}">${l}</button>`).join("")}</div>
            <div class="rows" id="ops-rows">${opsRows(d.visits)}</div></section>
      </div>`);
  };
  await run(load);
  if (S.date === TODAY && !stale(g)) S.timer = setInterval(() => !M && !stale(g) && run(load), 8000);
}
const VF = [["", "All"], ["booked", "Booked"], ["waiting", "Waiting"], ["with_doctor", "In consultation"], ["done", "Done"], ["no_show", "No-show"]];
function opsRows(vs) {
  const q = S.vf.q.trim().toLowerCase(), digits = q.replace(/\D/g, "");
  const list = vs.filter(v => (!S.vf.st || v.status === S.vf.st) && (!S.vf.doc || String(v.doctor_id) === S.vf.doc)
    && (!q || v.patient_name.toLowerCase().includes(q) || (v.uhid || "").toLowerCase().includes(q) || (digits && (v.phone || "").replace(/\D/g, "").includes(digits))));
  return list.map(v => `<div class="r"><span class="num"><b>${v.token_label || v.expected_time || "—"}</b></span>${S.me.screens.includes("patients") ? `<button class="patient-link who" data-a="pt-open" data-v="${v.patient_id}">${esc(v.patient_name)}</button>` : `<span class="who">${esc(v.patient_name)}</span>`}<span class="muted who doc-col">${esc(v.doctor_name)}${v.session_label ? " · " + v.session_label : ""}</span>${pill(v.status)}</div>`).join("") || `<div class="empty">—</div>`;
}
function doctorCard(d) {
  const s = d.schedule;
  return `<button class="dcard" data-a="open-doctor" data-v="${d.id}">
    <div class="line"><span class="actions" style="gap:10px;align-items:center"><span class="letter">${d.letter}</span><h3>${esc(d.name)}</h3></span></div>
    <div class="muted" style="font-size:14px">${hoursOf(s)}</div>
    <div class="capacity-line"><span>Capacity</span><b class="num">${d.used}/${s.max_patients}</b></div>
    <div class="meter"><i style="width:${Math.min(100, (d.used / s.max_patients) * 100)}%"></i></div>
  </button>`;
}

async function viewQueue(doctorId) {
  const g = S.gen;
  S.date = S.date || TODAY;
  const load = async () => {
    const q = await api(`/operations/queue?doctor_id=${doctorId}&date=${S.date}`);
    const wl = await api(`/waitlist?doctor_id=${doctorId}&date=${S.date}`);
    if (stale(g)) return;
    S.data = q;
    const cols = [["booked", "Booked"], ["waiting", "Waiting"], ["with_doctor", "With doctor"], ["done", "Done"]];
    const s = q.schedule;
    view(`<div class="head"><div><a href="#/ops" class="back-link">${arrowLeft}<span>Back</span></a><h1>${esc(q.doctor.name)}</h1>
        <p>${s ? `${hoursOf(s)} · ${s.limit_by === "minutes" ? s.minutes_per_patient + " min per patient" : "up to " + s.max_patients + " patients"}` : "Off"}</p></div><span class="grow"></span>
        <input class="top-date" type="date" data-a="ops-date" value="${S.date}" aria-label="Choose queue date"></div>
      <div class="actions quick-actions"><button class="btn" data-a="book" data-v="${doctorId}">New booking</button><button class="btn" data-a="walkin" data-v="${doctorId}">Walk-in</button>
        ${s ? s.sessions.filter(x => q.columns.booked.some(v => v.session_start === x.key)).map(x => `<button class="btn" data-a="end-session" data-v="${doctorId}" data-s="${x.key}">End ${s.sessions.length > 1 ? x.label.toLowerCase() + " " : ""}session</button>`).join("") : ""}</div>
      <div class="board">${cols.map(([k, l]) => `<section class="col"><header>${pill(k).replace(STATUS[k], l)}<span class="muted num">${q.columns[k].length}</span></header>
        ${q.columns[k].map((v, i, l) => qCard(v, i, l)).join("")}</section>`).join("")}</div>
      ${wl.items.length ? `<section class="panel"><span class="label">Waitlist</span><div class="rows">${wl.items.map((w, i) => `<div class="r wl-row"><span class="num muted">${i + 1}</span><span class="who"><b>${esc(w.patient_name)}</b></span><span class="muted">${esc(w.phone || w.uhid)}</span>
          <span class="actions" style="gap:6px"><button class="btn small dark" data-a="wl-book" data-v="${w.id}" ${wl.open ? "" : "disabled"}>Book</button><button class="icon-x" data-a="wl-del" data-v="${w.id}" aria-label="Remove">×</button></span></div>`).join("")}</div></section>` : ""}
      ${q.not_seen.length ? `<section class="panel"><span class="label">Not seen</span><div class="rows">${q.not_seen.map(v => `<div class="r q" style="grid-template-columns:minmax(0,1fr) auto"><span>${esc(v.patient_name)}</span>${pill(v.status)}</div>`).join("")}</div></section>` : ""}`);
  };
  await run(load);
  if (S.date === TODAY && !stale(g)) S.timer = setInterval(() => !M && !stale(g) && run(load), 8000);
}
function qCard(v, i, list) {
  const tok = v.token_label ? `<span class="tok chip">${v.token_label}</span>` : `<span class="tok none">No token yet</span>`;
  const clip = `<button class="btn small" data-a="upload" data-v="${v.id}" aria-label="Add document">📎${v.doc_count ? " " + v.doc_count : ""}</button>`;
  const sess = (v.session_label ? `<span class="pill s-soft">${v.session_label}</span>` : "") + (v.follow_up_of ? `<span class="pill s-with_doctor">Follow-up</span>` : "");
  const paid = v.paid_at ? `<span class="pill s-paid">${v.amount_paid ? `${rupees(v.amount_paid)} · ${(v.payment_method || "").toUpperCase()}` : "Waived"}</span>` : "";
  const refunded = v.refund_amount && v.paid_at ? `<span class="pill s-no_show">Refunded ${rupees(v.refund_amount)}</span>` : "";
  const more = v.paid_at || (v.status === "waiting" && !v.is_walk_in) ? `<button class="btn small icon-btn" data-a="v-more" data-v="${v.id}" aria-label="More">⋯</button>` : "";
  let meta = sess, acts = "";
  if (v.status === "booked") {
    meta += (v.expected_time ? `<span>${S.clinic.limit_by === "minutes" ? "" : "~"}${v.expected_time}</span>` : "") + (v.late ? `<span class="pill s-waiting">Late</span>` : "");
    acts = `<div class="acts-row"><button class="btn small dark" data-a="arrive" data-v="${v.id}">Arrived</button><button class="btn small icon-btn" data-a="v-more" data-v="${v.id}" aria-label="More">⋯</button></div><div class="acts-row"><button class="btn small" data-a="late" data-v="${v.id}" aria-pressed="${v.late}">Late</button><button class="btn small" data-a="resched" data-v="${v.id}">Reschedule</button></div>`;
  } else if (v.status === "waiting") {
    const same = list.filter(x => x.session_start === v.session_start), k = same.indexOf(v);
    meta += `${paid}${refunded}${v.is_walk_in ? `<span class="pill s-soft">Walk-in</span>` : ""}<span>since ${(v.arrived_at || "").slice(11, 16)}</span>`;
    acts = `<button class="btn small icon-btn" data-a="q-move" data-v="${v.id}" data-d="up" aria-label="Move up" ${k === 0 ? "disabled" : ""}>↑</button><button class="btn small icon-btn" data-a="q-move" data-v="${v.id}" data-d="down" aria-label="Move down" ${k === same.length - 1 ? "disabled" : ""}>↓</button>${clip}${more}`;
  } else {
    meta += paid + refunded;
    acts = more;
  }
  return `<article class="card"><div class="top"><b>${esc(v.patient_name)}</b>${tok}</div><div class="meta"><span class="mono">${esc(v.uhid)}</span>${meta}</div>${acts ? `<div class="acts">${acts}</div>` : ""}</article>`;
}
const refresh = () => route();

/* booking modal */
let M = null;
function openBooking(mode, opts = {}) {
  M = { kind: "booking", mode, patient: opts.patient || null, q: "", results: [], doctorId: opts.doctorId || S.doctors[0]?.id, date: mode === "walk" ? TODAY : (S.date && S.date >= TODAY ? S.date : TODAY),
        avail: null, token: null, pay: "upi", session: opts.visit?.session_start || null, reason: "", visit: opts.visit || null, done: null };
  if (!S.doctors.length) return toast("Add a doctor first.", true);
  loadAvail();
}
async function loadAvail() {
  const b = M; if (!b || b.kind !== "booking") return;
  b.avail = await api(`/availability?doctor_id=${b.doctorId}&date=${b.mode === "walk" ? TODAY : b.date}${b.visit ? "&exclude_visit=" + b.visit.id : ""}${b.session ? "&session=" + b.session : ""}`).catch(e => ({ available: false, reason: e.message, sessions: [] }));
  b.session = b.avail.session || null;
  b.token = b.avail.next?.token ?? null;
  renderBooking();
}
function slotCard(token, time, note, a, fee) {
  return `<div class="tiles-row"><div class="tk big"><small>Token</small><b>${token}</b></div>
    ${time ? `<div class="tk"><small>${note ? "Around" : "Time"}</small><b>${time}</b></div>` : ""}
    <div class="tk"><small>Left</small><b>${a.left}</b></div>${fee != null ? feeTile(fee) : ""}</div>`;
}
function renderBooking() {
  const b = M; if (!b) return;
  if (b.done) return modal(b.done);
  const a = b.avail || {}, s = a.schedule;
  const title = { book: "New booking", walk: "Walk-in", resched: "Reschedule" }[b.mode];
  let slot = "";
  if (!a.available) slot = `<div class="warn">${esc(a.reason || "Not available.")}</div>`;
  else if (b.mode === "walk") slot = slotCard(a.token_timing === "booking" ? a.next.token : "—", "", "", a, a.available ? a.fee : null);
  else if (a.token_timing === "booking") {
    const free = new Set(a.free_tokens.map(t => t.token)), times = Object.fromEntries(a.free_tokens.map(t => [t.token, t.time]));
    slot = `${slotCard(b.token, times[b.token], s.exact_time ? "" : "approx.", a)}<div class="chips slot-chips">${Array.from({ length: s.max_patients }, (_, i) => i + 1).filter(t => free.has(t)).map(t => `<button data-a="pick-token" data-v="${t}" aria-pressed="${t === b.token}"><b>${t}</b>${times[t]}</button>`).join("")}</div>`;
  } else slot = slotCard("—", a.expected_time, "approx.", a);
  const p = b.patient;
  const sessChips = (a.sessions || []).length > 1 ? `<div class="seg">${a.sessions.map(x => `<button data-a="bk-session" data-v="${x.key}" aria-pressed="${x.key === b.session}" ${x.ended ? "disabled" : ""}>${x.label} · ${x.start}–${x.end}</button>`).join("")}</div>` : "";
  const extra = b.mode === "walk" && a.available ? payBlock(a.fee, b.pay, true) : b.mode === "resched" ? reasonChips(RESCHED_REASONS, b.reason, "bk-reason") : "";
  modal(`<div class="booking-dialog"><h2>${title}</h2>
    ${p ? `<div class="pt-chip"><span class="avatar">${esc(initials(p.name))}</span><span class="pt-main"><b>${esc(p.name)}</b><span class="pt-meta"><span class="mono">${esc(p.uhid)}</span>${p.phone ? `<span>${esc(p.phone)}</span>` : ""}</span></span>${b.mode === "resched" ? "" : `<button class="btn small" data-a="bk-clear">Change</button>`}</div>`
        : `<input class="input" id="bk-q" placeholder="Search name, phone or UHID" value="${esc(b.q)}" data-a="bk-q" autocomplete="off">
           <div class="pick">${b.results.map(r => `<button data-a="bk-pick" data-v="${r.id}"><span><b>${esc(r.name)}</b> · ${esc(r.phone)}</span><span class="mono muted">${esc(r.uhid)}</span></button>`).join("")}</div>`}
    <div class="grid2 booking-fields">
      ${b.mode === "walk" ? "" : `<label class="field"><input type="date" aria-label="Date" id="bk-date" min="${TODAY}" value="${b.date}" data-a="bk-date"></label>`}
      <label class="field"><select aria-label="Doctor" id="bk-doc" data-a="bk-doc">${S.doctors.map(d => `<option value="${d.id}" ${d.id === b.doctorId ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select></label>
    </div>
    ${sessChips}
    ${slot}
    ${extra}
    <div class="foot">
      ${p && !a.available && b.mode === "book" && /full/i.test(a.reason || "") ? `<button class="btn" data-a="bk-wait">Waitlist</button>` : ""}
      <button class="btn primary" data-a="bk-confirm" ${p && a.available ? "" : "disabled"}>${b.mode === "walk" ? "Paid" : b.mode === "resched" ? "Move booking" : "Confirm"}</button></div></div>`);
  const q = $("#bk-q"); if (q) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
}
async function confirmBooking() {
  const b = M, p = b.patient;
  if (b.mode === "walk") {
    const v = await api("/visits/walk-in", { body: { patient_id: p.id, doctor_id: b.doctorId, session: b.session, ...readPay(b.avail.fee) } });
    b.done = paidDone("Walk-in added", v);
  } else if (b.mode === "resched") {
    const v = await api(`/visits/${b.visit.id}/reschedule`, { body: { doctor_id: b.doctorId, date: b.date, session: b.session, token: b.token, reason: b.reason } });
    b.done = `<h2>Booking moved</h2><div class="result">${esc(p.name)} → ${esc(v.doctor_name)}, ${niceDate(v.date)}${v.token_label ? ` · token ${v.token_label} · ${v.expected_time}` : ""}</div><div class="foot"><button class="btn primary" data-a="close-refresh">Done</button></div>`;
  } else {
    const v = await api("/visits", { body: { patient_id: p.id, doctor_id: b.doctorId, date: b.date, session: b.session, token: b.token } });
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
  modal(`<h2>${esc(v.patient_name)} has arrived</h2>${payBlock(v.fee, "upi")}
    <div class="foot"><button class="btn primary" data-a="arrive-paid">Send to Waiting</button></div>`);
}
function openRefund(v) {
  const left = v.refundable || 0;
  M = { kind: "refund", v, reason: "" };
  modal(`<h2>Refund · ${esc(v.patient_name)}</h2>
    <label class="field">Amount (₹)<input type="number" min="1" max="${left}" id="rf-amt" value="${left}"></label>
    ${reasonChips(REFUND_REASONS, "", "rf-reason")}
    <label class="field">Reason<input id="rf-why"></label>
    <div class="foot"><button class="btn danger" data-a="refund-go">Refund</button></div>`);
}
function openUpload(visitId) {
  M = { kind: "upload", visitId };
  modal(`<h2>Add document</h2>
    <label class="file-drop"><input type="file" id="up-file" accept="image/*,.pdf,.txt" data-a="up-file"><span class="file-btn">Choose file</span><span class="file-name" id="up-name">No file</span></label>
    <div class="foot"><button class="btn primary" data-a="upload-go">Upload</button></div>`);
}
async function doUpload(visitId, file) {
  const fd = new FormData(); fd.append("file", file);
  await api(`/visits/${visitId}/documents`, { body: fd });
  toast("Uploaded.");
}
function openRegister(name) {
  const back = M?.kind === "booking" ? M : null;
  M = { kind: "register", back };
  modal(`<h2>New patient</h2>
    <div class="grid2"><label class="field">Name<input id="rg-name" value="${esc(name || "")}"></label><label class="field">Phone<input id="rg-phone" placeholder="98470 12345"></label></div>
    <div class="grid2"><label class="field">Date of birth<input id="rg-dob" type="date" max="${TODAY}"></label><label class="field">Sex<select id="rg-sex"><option value="M">Male</option><option value="F">Female</option><option value="O">Other</option></select></label></div>
    <label class="field">Address<input id="rg-addr"></label>
    <label class="choice"><input type="checkbox" id="rg-consent"><span><b>Patient agrees to the clinic keeping their health records</b></span></label>
    <div class="foot"><button class="btn" data-a="${back ? "rg-back" : "close"}">${back ? "Back" : "Cancel"}</button><button class="btn primary" data-a="rg-save">Register</button></div>`);
  setTimeout(() => $("#rg-name")?.focus(), 30);
}

/* schedules */
async function openSchedules(doctorId, own) {
  M = { kind: "sched", own: !!own, doctorId: doctorId || S.doctors[0]?.id, month: (S.date || TODAY).slice(0, 7), days: [], sel: null };
  await loadMonth();
}
async function loadMonth() { M.days = await api(`/schedules/${M.doctorId}?month=${M.month}`); renderSched(); }
function renderSched() {
  const s = M, [y, m] = s.month.split("-").map(Number), lead = new Date(y, m - 1, 1).getDay();
  const scheduleYears = Array.from({ length: 11 }, (_, i) => new Date().getFullYear() - 2 + i);
  const sel = s.days.find(d => d.date === s.sel);
  let editor = "";
  if (sel) {
    const base = sel.edit || sel.schedule || { sessions: S.clinic.sessions, limit_by: S.clinic.limit_by, limit_value: S.clinic.limit_value };
    editor = `<div class="hit choices"><div class="actions" style="justify-content:space-between;align-items:center"><h3>${niceDate(sel.date)}</h3>${sel.override ? `<span class="pill s-with_doctor">Changed</span>` : `<span class="pill s-soft">Clinic hours</span>`}</div>
      <div class="seg"><button data-a="sc-off" data-v="0" aria-pressed="${!sel.off}">Working</button><button data-a="sc-off" data-v="1" aria-pressed="${sel.off}">Off</button></div>
      <div id="so-lim" class="choices" ${sel.off ? 'style="opacity:.35;pointer-events:none"' : ""}>${limitBlock("so", base)}</div>
      <div class="foot"><button class="btn" data-a="sc-reset" ${sel.override ? "" : "disabled"}>Default</button><button class="btn primary" data-a="sc-save">Save</button></div></div>`;
  }
  modal(`<div class="actions" style="justify-content:space-between;align-items:center"><h2>${s.own ? "My schedule" : "Doctor schedules"}</h2>
      ${s.own ? "" : `<select class="input" style="width:auto" id="sc-doc" data-a="sc-doc">${S.doctors.map(d => `<option value="${d.id}" ${d.id === s.doctorId ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select>`}</div>
    <div class="actions month-picker-wrap"><div class="month-picker"><span>Month</span><select data-a="sc-month-picker" aria-label="Choose schedule month">${Array.from({ length: 12 }, (_, i) => `<option value="${i + 1}" ${i + 1 === m ? "selected" : ""}>${new Date(2000, i, 1).toLocaleDateString("en-IN", { month: "long" })}</option>`).join("")}</select><select data-a="sc-year-picker" aria-label="Choose schedule year">${scheduleYears.map(n => `<option value="${n}" ${n === y ? "selected" : ""}>${n}</option>`).join("")}</select></div></div>
    <div class="cal">${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map(d => `<span class="dow">${d}</span>`).join("")}${"<span></span>".repeat(lead)}
      ${s.days.map(d => `<button class="${d.off ? "off" : ""} ${d.override ? "ovr" : ""}" data-a="sc-day" data-v="${d.date}" aria-pressed="${d.date === s.sel}" ${d.date < TODAY ? "disabled" : ""}><b>${Number(d.date.slice(8))}</b>${d.off ? "Off" : `${d.schedule.start}–${d.schedule.end}`}</button>`).join("")}</div>
    ${s.leave ? leaveEditor() : editor}
    <div class="foot">${s.leave ? "" : `<button class="btn" data-a="lv-open" data-v="doc">Leave</button>${S.me.is_admin && !s.own ? `<button class="btn" data-a="lv-open" data-v="all">Clinic holiday</button>` : ""}`}</div>`, true);
}
function leaveEditor() {
  const l = M.leave;
  return `<div class="hit choices"><h3>${l.all ? "Clinic holiday" : `${esc(S.doctors.find(d => d.id === M.doctorId)?.name || "Doctor")} · Leave`}</h3>
    <div class="date-row"><input class="date-pill" aria-label="From" type="date" id="lv-from" min="${TODAY}" value="${l.from}"><input class="date-pill" aria-label="To" type="date" id="lv-to" min="${TODAY}" value="${l.to}"></div>
    <div class="foot"><button class="btn" data-a="lv-save" data-v="0">Working</button><button class="btn primary" data-a="lv-save" data-v="1">${l.all ? "Holiday" : "Leave"}</button></div></div>`;
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
    ${k === "doctor" ? `<div class="fee-row"><div class="seg"><button data-a="mb-fee-mode" data-v="clinic" aria-pressed="${m?.fee_override == null}">Clinic fee</button><button data-a="mb-fee-mode" data-v="own" aria-pressed="${m?.fee_override != null}">Own fee</button></div>
      <label class="field" id="mb-fee-wrap" ${m?.fee_override == null ? "hidden" : ""}>Fee (₹)<input id="mb-fee" type="number" min="0" value="${m?.fee_override ?? S.clinic.fee}"></label></div>` : ""}
    ${m ? `<div class="grid2"><label class="field">Joining date<input type="date" id="mb-joined" value="${esc(m.joined_on || "")}"></label><label class="field">ID number<input id="mb-idno" value="${esc(m.id_number || "")}"></label></div>
    <div class="grid2"><label class="field">Emergency contact<input id="mb-emerg" value="${esc(m.emergency_contact || "")}"></label><label class="field">Address<input id="mb-addr" value="${esc(m.address || "")}"></label></div>
    ${k === "staff" ? `<div class="rule-group"><span class="rule-label">Working days</span><div class="day-dots">${["S", "M", "T", "W", "T", "F", "S"].map((d, i) => `<label><input type="checkbox" id="mb-d${i}" ${(m.work_days ? JSON.parse(m.work_days) : S.clinic.days).includes(i) ? "checked" : ""}><span>${d}</span></label>`).join("")}</div></div>
      <div class="grid2"><label class="field">Starts<input type="time" id="mb-ws" value="${esc(m.work_start || S.clinic.start || "09:00")}"></label><label class="field">Ends<input type="time" id="mb-we" value="${esc(m.work_end || S.clinic.end || "17:00")}"></label></div>` : ""}` : ""}
    <div class="field">Screens</div>
    <div class="days">${SCREENS.filter(([key]) => key !== "consultation" || k === "doctor").map(([key, , l]) => `<label><input type="checkbox" id="mb-s-${key}" ${screens.includes(key) || locked ? "checked" : ""} ${locked || (key === "administration" && !m?.is_admin) ? "disabled" : ""}>${l}</label>`).join("")}</div>
    <div class="toggles"><label class="choice"><input type="checkbox" id="mb-admin" data-a="mb-admin" ${m?.is_admin ? "checked" : ""} ${locked ? "disabled" : ""}><span><b>Admin access</b></span></label>
    ${m && !m.is_owner && m.status !== "invited" ? `<label class="choice"><input type="checkbox" id="mb-active" ${m.status === "active" ? "checked" : ""}><span><b>Active</b></span></label>` : ""}</div>
    <div class="foot">${m && !m.is_owner ? `<button class="btn danger" data-a="mb-remove" style="margin-right:auto">Remove</button>` : ""}${m?.status === "invited" ? `<button class="btn" data-a="renew-invite" data-v="${m.id}">Invite link</button>` : ""}${m?.status === "active" && !m.is_owner ? `<button class="btn" data-a="reset-link" data-v="${m.id}">Reset password</button>` : ""}${m && k === "doctor" ? `<button class="btn" data-a="mb-schedule" data-v="${m.id}">Schedule</button>` : ""}
      <button class="btn primary" data-a="mb-save">${m ? "Save" : "Send invitation"}</button></div>`);
}
async function saveMember() {
  const { mkind, m } = M, own = $('[data-a="mb-fee-mode"][data-v="own"]')?.getAttribute("aria-pressed") === "true";
  const body = { name: $("#mb-name").value, phone: $("#mb-phone").value, email: $("#mb-email").value,
    screens: SCREENS.map(s => s[0]).filter(k => $("#mb-s-" + k)?.checked), is_admin: $("#mb-admin").checked,
    ...(mkind === "doctor" ? { speciality: $("#mb-spec").value, fee_override: own ? Number($("#mb-fee").value) || 0 : null } : { designation: $("#mb-spec").value }) };
  if (m) {
    if (!m.is_owner) body.kind = mkind;
    if (mkind === "doctor" && !own) body.clear_fee = true;
    if (m.is_owner) { delete body.screens; delete body.is_admin; }
    if ($("#mb-active")) body.status = $("#mb-active").checked ? "active" : "inactive";
    Object.assign(body, { joined_on: $("#mb-joined").value || null, id_number: $("#mb-idno").value, emergency_contact: $("#mb-emerg").value, address: $("#mb-addr").value });
    if (mkind === "staff") Object.assign(body, { work_days: [0, 1, 2, 3, 4, 5, 6].filter(i => $("#mb-d" + i).checked), work_start: $("#mb-ws").value, work_end: $("#mb-we").value });
    await api(`/members/${m.id}`, { method: "PATCH", body });
    toast("Saved");
  } else {
    const r = await api("/members", { body: { ...body, kind: mkind } });
    copyLink(`${location.origin}/#/invite/${r.invite_code}`, `Invitation created for ${r.name} · link copied`);
  }
  S.doctors = await api("/doctors"); closeModal();
  if (OB.step === 4 && !S.clinic.onboarded) loadMembersStep(); else route();
}
function openShare(what, id, code, emailOn) {
  const m = (S.members || []).find(x => x.id === id), back = M?.kind === "member" ? M : null;
  const link = `${location.origin}/#/${what}/${code}`;
  M = { kind: "share", what, id, code, link, back };
  modal(`<h2>${what === "invite" ? "Invite link" : "Password reset"}</h2>
    <div class="pt-chip share-chip"><span class="avatar">${esc(initials(m?.name || "?"))}</span><span class="pt-main"><b>${esc(m?.name || "")}</b><span class="pt-meta"><span>${esc(m?.email || "")}</span><span>${what === "invite" ? "7 days" : "2 hours"}</span></span></span></div>
    <div class="share-row">${emailOn ? `<button class="share-opt" data-a="share-email"><b>Email link</b></button>` : ""}
      <button class="share-opt" data-a="share-copy"><b>Copy link</b></button></div>
    <div class="foot"><button class="btn primary" data-a="close">Done</button></div>`);
}
function copyLink(link, msg) {
  navigator.clipboard?.writeText(link).then(() => toast(msg), () => { M = { kind: "link" }; modal(`<h2>Share this link</h2><label class="field">Link<input readonly value="${esc(link)}" onfocus="this.select()"></label><div class="foot"><button class="btn primary" data-a="close">Done</button></div>`); });
}
async function openAccount() {
  const m = S.me, doc = m.kind === "doctor";
  const [att, myLeave] = await Promise.all([api("/attendance/me").catch(() => ({})), api("/leave?mine=true").catch(() => [])]);
  M = { kind: "account" };
  const upcoming = myLeave.filter(l => l.end_date >= TODAY && ["pending", "approved"].includes(l.status));
  modal(`<div class="mb-head"><div class="avatar big">${esc(initials(m.name))}</div><div><h2>${esc(m.name)}</h2><span class="muted">${esc(doc ? m.speciality || "Doctor" : m.designation || "Staff")}</span></div>
      <span class="grow"></span>${att.check_out ? `<span class="pill s-paid">${hhmm(att.check_in)} – ${hhmm(att.check_out)}</span>` : att.check_in ? `<button class="btn small" data-a="att-out">Check out · in ${hhmm(att.check_in)}</button>` : `<button class="btn small dark" data-a="att-in">Check in</button>`}</div>
    ${upcoming.length ? `<div class="rows my-leave">${upcoming.map(l => `<div class="r my-leave-row"><span class="num">${niceDate(l.start_date)}${l.end_date !== l.start_date ? " – " + niceDate(l.end_date) : ""}</span><span class="who muted">${esc(l.reason || "")}</span><span class="actions" style="gap:6px"><span class="pill ${LEAVE_ST[l.status][1]}">${LEAVE_ST[l.status][0]}</span><button class="btn small icon-btn" data-a="lv-cancel" data-v="${l.id}" aria-label="Cancel leave">×</button></span></div>`).join("")}</div>` : ""}
    <div class="grid2"><label class="field">Name<input id="ac-name" value="${esc(m.name)}"></label><label class="field">${doc ? "Speciality" : "Designation"}<input id="ac-role" value="${esc((doc ? m.speciality : m.designation) || "")}"></label></div>
    <div class="grid2"><label class="field">Email<input id="ac-email" type="email" value="${esc(m.email)}"></label><label class="field">Phone<input id="ac-phone" value="${esc(m.phone || "")}"></label></div>
    <label class="field">Current password<input id="ac-cur" type="password" autocomplete="current-password"></label>
    <div class="grid2"><label class="field">New password<input id="ac-new" type="password" autocomplete="new-password"></label><label class="field">Repeat new password<input id="ac-new2" type="password" autocomplete="new-password"></label></div>
    <div class="foot"><button class="btn danger" data-a="logout" style="margin-right:auto">Log out</button><button class="btn" data-a="my-leave">Leave</button>${doc ? `<button class="btn" data-a="my-schedule">My schedule</button>` : ""}<button class="btn primary" data-a="ac-save">Save</button></div>`);
}
function copyInvite(code, msg) {
  const link = `${location.origin}/#/invite/${code}`;
  navigator.clipboard?.writeText(link).then(() => toast(msg || "Invite link copied"), () => toast(link));
}

/* consultation */
const CTABS = [["brief", "Brief"], ["dictate", "Transcript"], ["note", "Note"]];
async function viewConsult(visitId, doctorParam, patientParam) {
  const g = S.gen;
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
    if (stale(g)) return;
    if (cur) { S.textRev = S.textRev || {}; S.textRev[cur.id] = Math.max(S.textRev[cur.id] ?? 0, cur.text_rev ?? 0); }
    S.data = { today, cur, profile, found, doctorId, pid };
    renderConsult();
    if (cur && ["waiting", "with_doctor"].includes(cur.status) && !cur.brief && !S.briefing) {
      S.briefing = true;
      run(async () => { try { await api(`/visits/${cur.id}/brief`, { body: {} }); } finally { S.briefing = false; } refreshConsult(); });
    }
  };
  S.reloadConsult = load;
  await run(load);
}
const refreshConsult = () => S.reloadConsult && run(S.reloadConsult);
function renderConsult() {
  const D = S.data, m = S.me, v = D.cur, y = window.scrollY, again = S.cxShown === (v?.id ?? "p" + D.pid);
  S.cxShown = v?.id ?? "p" + D.pid;
  const fe = $("#free-text"); if (fe && S.ft?.id === Number(fe.dataset.v)) { S.ft.sel = document.activeElement === fe ? fe.selectionEnd : null; S.ft.scroll = fe.scrollTop; }
  if (S.ft && S.ft.id !== v?.id) { saveText(S.ft.id, S.ft); S.ft = null; }
  if (!S.ft && v && S.drafts?.[v.id] && S.drafts[v.id].saved !== S.drafts[v.id].text) S.ft = S.drafts[v.id];   // restore unsaved text
  if (S.noteVisit !== v?.id) { S.noteVisit = v?.id; S.noteEdit = false; }
  const floatMic = v && (["waiting", "with_doctor"].includes(v.status) || S.recState) && S.ctab !== "note";
  $("#root").innerHTML = `<div class="cx">
    <header class="cx-top">
      <b class="cx-logo">Dictate</b>
      <span class="cx-chip">${esc(S.clinic.name)} · OPD</span>
      <nav class="cx-links">${SCREENS.filter(s => m.screens.includes(s[0]) && s[0] !== "consultation").map(([, h, l]) => `<a href="${h}">${l}</a>`).join("")}</nav>
      <span class="grow"></span>
      ${S.doctors.length > 1 || m.kind !== "doctor" ? `<select class="cx-select" id="cs-doc" data-a="cs-doc" aria-label="Doctor">${S.doctors.map(d => `<option value="${d.id}" ${d.id === D.doctorId ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select>` : ""}
      <span class="cx-chip solid">${m.kind === "doctor" ? "Doctor" : esc(m.designation || "Staff")}</span>
      <button class="cx-avatar" data-a="account" title="Account">${esc(firstName(m.name)[0].toUpperCase())}</button>
    </header>
    <div class="cx-body ${S.rightCollapsed ? "wide" : ""}">
      <aside class="cx-left">${leftCol()}</aside>
      <main class="cx-center" id="cx-center">${center()}${floatMic ? `<div class="cx-float">${dock(v)}</div>` : v && S.ctab === "note" ? `<div class="cx-float">${noteDock(v)}</div>` : ""}</main>
      ${S.rightCollapsed ? "" : `<aside class="cx-right">${rightCol()}</aside>`}
    </div>
  </div>`;
  if (again) { $(".cx")?.classList.add("re"); window.scrollTo(0, y); }
  restoreFree();
  clearTimeout(S.docT);
  if (v?.documents.some(d => d.ai_status === "processing")) S.docT = setTimeout(refreshConsult, 2000);
}
function restoreFree() {
  const el = $("#free-text"); if (!el || !S.ft || S.ft.id !== Number(el.dataset.v)) return;
  if (S.ft.sel != null) { el.focus({ preventScroll: true }); el.setSelectionRange(S.ft.sel, S.ft.sel); }
  if (S.ft.scroll) el.scrollTop = S.ft.scroll;
}
const ICON = {
  pause: '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><rect x="6.5" y="5" width="3.6" height="14" rx="1.4"/><rect x="13.9" y="5" width="3.6" height="14" rx="1.4"/></svg>',
  play: '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M8 5.6v12.8a1 1 0 0 0 1.5.86l10.2-6.4a1 1 0 0 0 0-1.72L9.5 4.74A1 1 0 0 0 8 5.6z"/></svg>',
  x: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  stop: '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2.5"/></svg>',
};
const WAVE = [4, 9, 14, 7, 11, 5, 3, 16, 10, 6, 12, 8, 5, 13, 18, 7, 11, 6, 9, 4];
function dock(v) {
  if (S.recState && S.recVisit === v.id) {
    const paused = S.recState === "paused";
    return `<div class="dock rec ${paused ? "paused" : ""}"><div class="dock-wave">${WAVE.map((h, i) => `<i style="--h:${h}px;animation-delay:${(i * 97) % 900}ms"></i>`).join("")}</div>
      <span class="dock-time" id="dock-timer">${fmtClock(recElapsed())}</span>
      <button class="dock-round" data-a="${paused ? "mic-resume" : "mic-pause"}" aria-label="${paused ? "Resume" : "Pause"}" title="${paused ? "Resume" : "Pause"}">${paused ? ICON.play : ICON.pause}</button>
      <button class="dock-stop" data-a="mic-stop" aria-label="Stop" title="Stop">${ICON.stop}</button></div>`;
  }
  const n = v.note, canDraft = v.status === "with_doctor" && n?.status !== "signed" && (freeText(v).trim() || v.documents.some(d => d.ai_status === "ready"));
  if (S.ctab === "dictate" && S.dictDone === v.id && canDraft)
    return `<div class="dock"><span class="dock-msg ok">Transcript finalized.</span><span class="grow"></span><button class="dock-ghost" data-a="cs-mic" data-v="${v.id}">Dictate more</button><button class="dock-go" data-a="cs-draft" data-v="${v.id}">Generate SOAP note</button></div>`;
  return micBtn(v);
}
const sideBtn = () => !S.rightCollapsed ? "" : `<button class="cx-side-btn" data-a="cs-collapse" aria-label="${S.rightCollapsed ? "Show side panel" : "Hide side panel"}" title="${S.rightCollapsed ? "Show side panel" : "Hide side panel"}"><i></i><i></i></button>`;
function micBtn(v, small) {
  return `<button class="mic-dot ${small ? "sm" : ""}" data-a="cs-mic" data-v="${v.id}" aria-label="Dictate">${icon.mic}</button>`;
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
      <p class="muted">${{ M: "Male", F: "Female", O: "Other" }[p.sex] || ""} · ${esc(p.uhid)}</p></div><span class="cx-top-right">${sideBtn()}</span></div>
      <div class="cx-events">${past.map(x => `<div><span>•</span><span><b>${longDate(x.date)}</b> · ${esc(x.note?.soap?.A || x.doctor)}</span></div>`).join("") || `<span class="muted">—</span>`}</div></div>`;
  }
  const stateLabel = { waiting: "Waiting", with_doctor: "In visit", done: "Signed", booked: "Booked" }[v.status];
  return `<div class="cx-card">
    <div class="cx-head"><div><h1>${esc(v.patient_name)}${v.age != null ? ", " + v.age : ""}</h1>
</div>
      <span class="cx-top-right">${["with_doctor", "done"].includes(v.status) ? `<button class="cx-pill-btn" data-a="fu-open" data-v="${v.id}">Follow-up</button>` : ""}<span class="cx-status st-${v.status}"><i></i>${stateLabel}</span>${sideBtn()}</span></div>
    <div class="cx-tabs">${CTABS.map(([k, l]) => `<button data-a="cs-tab" data-v="${k}" aria-pressed="${S.ctab === k}">${l}</button>`).join("")}</div>
    <div class="cx-pane">${({ brief: paneBrief, dictate: paneDictate, note: paneNote })[S.ctab](v)}</div>
  </div>`;
}
function paneBrief(v) {
  const items = v.brief?.items || [];
  const lead = items[0], rest = items.slice(1);
  if (!lead) return ["waiting", "with_doctor"].includes(v.status) ? `<p class="muted cx-lead">Preparing brief…</p>` : "";
  return `<p class="cx-lead">${esc(lead.text)}${citeBtns(lead.cites)}</p>
    ${rest.length ? `<div class="cx-events">${rest.map(i => `<div class="${i.flag ? "flag" : ""}"><span>${i.flag ? "⚠" : "•"}</span><span>${esc(i.text)}${citeBtns(i.cites)}</span></div>`).join("")}</div>` : ""}`;
}
function paneDictate(v) {
  const n = v.note, can = v.status === "with_doctor" && n?.status !== "signed";
  return `<textarea class="live-text live-edit" id="free-text" data-a="free-text" data-v="${v.id}" spellcheck="true" aria-label="Transcript" ${can ? "" : "readonly"}>${esc(freeText(v))}</textarea>`;
}
const freeText = v => S.ft?.id === v.id ? S.ft.text : S.drafts?.[v.id]?.saved !== S.drafts?.[v.id]?.text ? S.drafts[v.id].text : (v.text || "");
const SOAP = [["S", "Subjective"], ["O", "Objective"], ["A", "Assessment"], ["P", "Plan"]];
function paneNote(v) {
  const n = v.note, signed = n?.status === "signed";
  if (S.drafting === v.id) return `<div class="note-gen"><i></i><i></i><i></i></div>`;
  if (!n) return `<div class="cx-empty">—</div>`;
  if (S.noteEdit && !signed) return noteEditor(n, false);
  return soapRead(v, n);
}
function soapRead(v, n, still) {
  let num = 0;
  const sec = (k, label, body) => `<div class="soap-sec"><b class="soap-tile">${k}</b><div><span class="soap-label">${label}</span><div class="soap-body">${body}</div></div></div>`;
  const out = SOAP.map(([k, label]) => {
    const text = (n.content.soap[k] || "").trim();
    const sents = sentences(text).map(x => x.text);
    const srcs = (n.citations?.[k] || []).map(id => ({ id, text: sourceOf(v, id)?.text || "" }));
    return sec(k, label, sents.map(t => `<span class="nb">${++num}</span>${marked(t, srcs, still)}`).join(" ") || `<span class="muted">—</span>`);
  }).join("");
  const rx = n.content.rx.filter(r => r.medicine);
  return `<div class="soap-read">${out}${rx.length ? sec("Rx", "Prescription", rx.map(r => `<div class="rx-line"><span class="nb">${++num}</span><b>${esc(r.medicine)}</b>${[r.dose, r.duration, r.instructions].filter(Boolean).map(x => ` · ${esc(x)}`).join("")}</div>`).join("")) : ""}</div>`;
}
const STOP = new Set("a an the and or of to in on at for with by is are was were be been has have had this that it its as from no not patient patients reports reported says said complains denies looks like seems tab tablet order rule out once twice daily mg ml for since".split(" "));
function marked(sentence, srcs, still) {
  const words = sentence.split(/(\s+)/), norm = w => w.toLowerCase().replace(/[^a-z0-9/]/g, "");
  const toks = words.map((w, i) => ({ w, i, n: /\s/.test(w) ? null : norm(w) })).filter(t => t.n !== null);
  // up to 3-word phrases shared with a source; keep the 2 best
  const cands = [];
  for (const src of srcs) {
    const hay = " " + src.text.toLowerCase().split(/\s+/).map(norm).filter(Boolean).join(" ") + " ";
    for (let i = 0; i < toks.length; i++) for (let j = i; j < Math.min(i + 3, toks.length); j++) {
      if (!hay.includes(" " + toks.slice(i, j + 1).map(t => t.n).join(" ") + " ")) break;
      if (STOP.has(toks[i].n) || STOP.has(toks[j].n) || i === 0 && j === toks.length - 1) continue;
      const score = toks.slice(i, j + 1).reduce((n, t) => n + (STOP.has(t.n) ? 0 : t.n.length), 0) + (j - i) * 3;
      if (score >= 8) cands.push({ a: i, b: j, id: src.id, score });
    }
  }
  const marks = [];
  for (const c of cands.sort((x, y) => y.score - x.score)) {
    if (marks.length === 2) break;
    if (!marks.some(m => !(c.b < m.a - 1 || c.a > m.b + 1))) marks.push(c);
  }
  if (!marks.length) return esc(sentence);
  const byTok = new Map(); marks.forEach(m => { byTok.set(toks[m.a].i, { start: true, id: m.id }); byTok.set(toks[m.b].i, { ...(byTok.get(toks[m.b].i) || {}), end: true, id: m.id }); });
  return words.map((w, i) => { const m = byTok.get(i); return (m?.start ? (still ? `<span class="cited">` : `<button class="cited" data-a="cite" data-v="${m.id}">`) : "") + esc(w) + (m?.end ? (still ? "</span>" : "</button>") : ""); }).join("");
}
function noteDock(v) {
  const n = v.note, signed = n?.status === "signed";
  if (S.drafting === v.id) return `<div class="dock"><span class="dock-text">Writing your note…</span></div>`;
  if (!n) {
    const canDraft = v.status === "with_doctor" && (freeText(v).trim() || v.documents.some(d => d.ai_status === "ready"));
    return canDraft ? `<div class="dock"><span class="grow"></span><button class="dock-go" data-a="cs-draft" data-v="${v.id}">Generate SOAP note</button></div>` : "";
  }
  if (signed) return `<div class="dock"><span class="dock-msg ok">Signed · ${stampOf(n.signed_at)}${n.signed_by_name ? " · " + esc(n.signed_by_name) : ""}</span><span class="grow"></span><button class="dock-go" data-a="note-print" data-v="${n.id}">Print</button></div>`;
  if (S.noteEdit) return `<div class="dock"><span class="dock-msg">Editing.</span><span class="grow"></span><button class="dock-go" data-a="note-done">Save</button></div>`;
  return `<div class="dock"><span class="dock-msg">${S.aiOn ? "Drafted by AI." : "Draft."}</span><span class="grow"></span>
    <button class="dock-ghost" data-a="note-edit">Edit</button>${v.status === "with_doctor" ? `<button class="dock-ghost" data-a="cs-redraft" data-v="${v.id}">Redraft</button>` : ""}<button class="dock-go" data-a="note-sign-ro" data-v="${n.id}">Sign note</button></div>`;
}
function rightCol() {
  const D = S.data, p = D.profile;
  const tabs = `<div class="cx-right-top"><button class="cx-side-btn close" data-a="cs-collapse" aria-label="Hide side panel" title="Hide side panel"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h12M12 6l6 6-6 6"/></svg></button><div class="cx-seg"><button data-a="cs-side" data-v="profile" aria-pressed="${S.cside !== "citations"}">Profile</button><button data-a="cs-side" data-v="citations" aria-pressed="${S.cside === "citations"}">Citations</button></div></div>`;
  if (S.cside === "citations") return `${tabs}${citations(D.cur)}`;
  if (!p) return `${tabs}<div class="cx-empty">—</div>`;
  return `${tabs}<div class="cx-rows">
    ${[["Name", p.name], ["Age", ageOf(p.dob)], ["Date of birth", p.dob ? longDate(p.dob) : "—"], ["Sex", { M: "Male", F: "Female", O: "Other" }[p.sex] || "—"], ["Phone", p.phone || "—"], ["Address", p.address || "—"], ["UHID", p.uhid]].map(([k, val]) => `<div class="cx-row"><span>${k}</span><b>${esc(val)}</b></div>`).join("")}
    <div class="cx-row"><span>Visits</span><b>${p.visits.filter(x => x.status === "done").length}</b></div></div>`;
}
function sourceOf(v, id) {
  if (id.startsWith("T")) { const t = v.note?.sources?.[id] ?? sentences(freeText(v))[Number(id.slice(1)) - 1]?.text; return t && { kind: "Transcript", text: t }; }
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
      ${rx.map((r, i) => `<tr>${["medicine", "dose", "duration", "instructions"].map(f => `<td>${ro ? esc(r[f]) : `<input data-f="${f}" value="${esc(r[f])}" aria-label="${f}">`}</td>`).join("")}${ro ? "" : `<td><button class="icon-x" data-a="rx-del" data-v="${i}" aria-label="Remove">×</button></td>`}</tr>`).join("") || `<tr><td colspan="5" class="muted">—</td></tr>`}
    </tbody></table></div>${ro ? "" : `<div><button class="btn small" data-a="rx-add">+ Add medicine</button></div>`}`;
}
function readNote() {
  const soap = Object.fromEntries(["S", "O", "A", "P"].map(k => [k, $("#soap-" + k)?.value || ""]));
  const rx = [...document.querySelectorAll("#rx tbody tr")].filter(tr => tr.querySelector("input")).map(tr => Object.fromEntries([...tr.querySelectorAll("input")].map(i => [i.dataset.f, i.value])));
  return { soap, rx };
}
// Deepgram when the server has a key, else the browser's own speech recognition.
function startMic(visitId) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (S.dictBy !== "deepgram" && !SR) { refreshConsult(); return toast("Use Chrome to dictate", true); }
  Object.assign(S, { recState: "on", recVisit: visitId, recAcc: 0, recStart: Date.now(), dict: null, dictDone: null });
  listen(visitId);
  clearInterval(S.recT); S.recT = setInterval(() => { const t = $("#dock-timer"); if (t) t.textContent = fmtClock(recElapsed()); }, 500);
  renderConsult();
}
const recElapsed = () => (S.recAcc || 0) + (S.recState === "on" && S.recStart ? Date.now() - S.recStart : 0);
function listen(visitId) {
  if (S.dictBy === "deepgram") return streamMic(visitId);
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const r = new SR(); r.lang = "en-IN"; r.continuous = true; r.interimResults = true;
  S.dict = null;
  r.onresult = e => {
    const el = $("#free-text"); if (!el || el.readOnly) return;
    if (!S.dict || (!S.dict.len && document.activeElement === el)) S.dict = { start: document.activeElement === el ? el.selectionEnd : el.value.length, len: 0 };
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const said = e.results[i][0].transcript.trim();
      if (e.results[i].isFinal) { if (said) putSpeech(el, said + " ", true); } else interim += (interim ? " " : "") + said;
    }
    if (interim) putSpeech(el, interim, false);
    edit(visitId, el.value);
  };
  // Chrome stops after silence; restart until the doctor stops.
  r.onend = () => { if (S.rec === r && S.recState === "on") { try { r.start(); } catch { listen(visitId); } } };
  r.onerror = e => !["no-speech", "aborted"].includes(e.error) && toast("Mic: " + e.error, true);
  S.rec = r; r.start();
}
function pauseMic() {
  if (S.recState !== "on") return;
  S.recAcc = recElapsed(); S.recState = "paused";
  const r = S.rec; S.rec = null; try { if (r?.finish) S.finishing = r.finish().catch(() => {}); else r?.stop(); } catch {}
  S.dict = null; renderConsult();
}
function resumeMic() {
  if (S.recState !== "paused") return;
  S.recState = "on"; S.recStart = Date.now(); listen(S.recVisit); renderConsult();
}
async function stopMic() {
  const id = S.recVisit, r = S.rec;
  S.rec = null; S.recState = null; clearInterval(S.recT);
  try { r?.finish ? await r.finish() : r?.stop(); } catch {}
  S.dict = null; S.dictDone = id;
  await saveText(id); refreshConsult();
}
function speech(visitId, text, final) {
  const el = $("#free-text"); if (!el || el.readOnly || Number(el.dataset.v) !== visitId) return;
  if (!S.dict || (!S.dict.len && !S.dict.kept && document.activeElement === el)) S.dict = { start: document.activeElement === el ? el.selectionEnd : el.value.length, len: 0 };
  const kept = S.dict.kept;   // words already left in the box when the doctor typed
  if (kept && text.toLowerCase().startsWith(kept.toLowerCase())) text = text.slice(kept.length).trimStart();
  if (final) S.dict.kept = "";
  if (!text) return;
  putSpeech(el, final ? text + " " : text, final);
  edit(visitId, el.value);
}
// Mic → 16 kHz PCM frames (ported from Project-Dictate). The AudioContext is made at the click, before any await.
const audioContext = () => { const C = window.AudioContext || window.webkitAudioContext; const c = new C({ latencyHint: "interactive" }); c.resume().catch(() => {}); return c; };
async function micCapture(onFrame, onLost) {
  const ctx = S.audioCtx || audioContext(); S.audioCtx = null;
  let stream, node, src, mute, on = false, stopped = false, flushed;
  const stop = async ({ flush = false } = {}) => {
    if (stopped) return; stopped = true;
    if (flush && node && on) await new Promise(r => { flushed = r; node.port.postMessage("flush"); setTimeout(r, 150); });
    on = false;
    if (node) { node.port.onmessage = null; node.disconnect(); node.port.close(); }
    src?.disconnect(); mute?.disconnect();
    stream?.getTracks().forEach(t => { t.onended = null; t.stop(); });
    if (ctx.state !== "closed") await ctx.close().catch(() => {});
  };
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    await ctx.resume();
    await ctx.audioWorklet.addModule("/static/pcm-worklet.js");
    node = new AudioWorkletNode(ctx, "dictate-pcm", { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1] });
    node.port.onmessage = ({ data }) => { if (data.type === "audio" && on) onFrame(data.frame); if (data.type === "flushed") flushed?.(); };
    src = ctx.createMediaStreamSource(stream); mute = ctx.createGain(); mute.gain.value = 0;
    src.connect(node); node.connect(mute); mute.connect(ctx.destination);
    stream.getTracks().forEach(t => { t.onended = () => { if (!stopped) { stop(); onLost(); } }; });
  } catch (e) { await stop(); throw e; }
  return { start: () => { on = true; }, stop };
}
// Deepgram via the server. Text lands in the writing box and is saved by the normal autosave.
async function streamMic(visitId) {
  const rec = { stop() {}, async finish() {} };
  S.rec = rec; S.dict = null;
  const fail = msg => { if (S.rec !== rec) return; toast(msg, true); stopMic(); };
  let ws, mic;
  try { mic = await micCapture(f => ws?.readyState === 1 && ws.send(f), () => fail("Microphone disconnected")); }
  catch { S.audioCtx = null; return fail("Allow the microphone to dictate"); }
  await S.finishing;   // a paused stream must close before the next one opens
  if (S.rec !== rec) return mic.stop();
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/visits/${visitId}/dictate`, ["dictate", S.token]);
  let closed; const done = new Promise(r => { closed = r; });
  const timer = setTimeout(() => fail("Dictation couldn't connect"), 10000);
  ws.onmessage = ({ data }) => {
    const m = JSON.parse(data);
    if (m.type === "ready") { clearTimeout(timer); mic.start(); }
    else if (m.type === "transcript") speech(visitId, m.text, m.final);
    else if (m.type === "error") { clearTimeout(timer); fail(m.message); }
  };
  ws.onclose = () => { clearTimeout(timer); closed(); fail("Dictation stopped. Try again."); };
  rec.stop = () => { clearTimeout(timer); mic.stop(); ws.close(); };
  rec.finish = async () => {   // send the last audio, then wait for Deepgram's last words
    clearTimeout(timer); await mic.stop({ flush: true });
    if (ws.readyState === 1) { ws.send("stop"); await Promise.race([done, new Promise(r => setTimeout(r, 8000))]); } else ws.close();
  };
}
// The doctor typed while words were still being recognised: keep those words, and let the rest of
// the phrase continue right after them (shifted if the typing happened before them).
function typedOver(d, el) {
  if (!d.len && !d.kept) return { start: el.selectionEnd, len: 0 };
  const was = S.ft?.id === Number(el.dataset.v) ? S.ft.text : null, shift = was == null ? 0 : el.value.length - was.length;
  const after = el.selectionEnd - shift >= d.start + d.len;
  return { start: d.start + d.len + (after ? 0 : shift), len: 0, kept: d.len ? d.said || "" : d.kept };
}
function putSpeech(el, text, final) {
  const d = S.dict, before = el.value.slice(0, d.start);
  const pad = before && !/\s$/.test(before) ? " " : "";
  if (!before.trim() || /[.!?]\s*$/.test(before)) text = text.charAt(0).toUpperCase() + text.slice(1);
  el.setRangeText(pad + text, d.start, d.start + d.len, "end");
  if (final) { d.start += pad.length + text.length; d.len = 0; } else { d.len = pad.length + text.length; d.said = (d.kept ? d.kept + " " : "") + text; }
  if (document.activeElement === el) el.setSelectionRange(d.start + d.len, d.start + d.len);
}
// Same split as the server's ai.sentences(): T1, T2… are sentences; 100.8 stays whole.
const sentences = text => {
  const out = []; let at = 0;
  for (const line of text.split("\n")) {
    for (const m of line.matchAll(/[^.!?\s].*?(?:[.!?]+(?=\s|$)|$)/g)) { const t = m[0].trim(); if (t) out.push({ text: t, from: at + m.index, to: at + m.index + m[0].trimEnd().length }); }
    at += line.length + 1;
  }
  return out;
};
function scheduleSave(visitId) { clearTimeout(S.ftT); S.ftT = setTimeout(() => saveText(visitId), 700); }
// Each snapshot keeps its first rev so stale retries are refused by the server.
function edit(visitId, text) {
  const { base, tries, ...was } = S.ft?.id === visitId ? S.ft : (S.drafts?.[visitId] || {});
  S.ft = { ...was, id: visitId, text };
  (S.drafts = S.drafts || {})[visitId] = S.ft;
  scheduleSave(visitId);
}
// Serialise saves per visit.
function saveText(visitId, ft = S.ft) {
  clearTimeout(S.ftT);
  S.saving = S.saving || {};
  const run = (S.saving[visitId] || Promise.resolve()).then(() => saveOnce(visitId, ft));
  S.saving[visitId] = run.catch(() => {});
  return run;
}
async function saveOnce(visitId, ft, again) {
  if (!ft || ft.id !== visitId || S.drafts?.[visitId] !== ft) return true;   // superseded
  if (ft.saved === ft.text) return true;
  const text = ft.text;
  S.textRev = S.textRev || {}; S.sent = S.sent || {};
  if (ft.base == null) ft.base = S.textRev[visitId] ?? 0;
  (S.sent[visitId] = S.sent[visitId] || new Set()).add(text);
  try {
    const r = await api(`/visits/${visitId}/text`, { method: "PUT", body: { text, rev: ft.base } });
    S.textRev[visitId] = r.rev;
  } catch (e) {
    if (e.status === 409 && !again && S.drafts[visitId] === ft) {
      // A lost reply may hide our own save: if the server holds text we sent, continue from it.
      const now = await api(`/visits/${visitId}`).catch(() => null);
      if (now?.text === text) { S.textRev[visitId] = now.text_rev; return done(visitId, ft, text); }
      if (now && S.sent[visitId].has(now.text)) { ft.base = now.text_rev; return saveOnce(visitId, ft, true); }
    }
    if (e.status === 409) {
      if (S.drafts[visitId] !== ft) return true;
      // Someone else saved newer text: keep theirs.
      delete S.drafts[visitId]; if (S.ft?.id === visitId) S.ft = null;
      toast(e.message, true); refreshConsult(); return false;
    }
    toast(`Not saved · ${e.message}`, true);
    ft.tries = (ft.tries || 0) + 1;
    if (ft.tries < 6) setTimeout(() => saveText(visitId, ft), 5000);
    return false;
  }
  return done(visitId, ft, text);
}
function done(visitId, ft, text) {
  ft.saved = text; ft.tries = 0;
  if (S.drafts[visitId] === ft && S.data?.cur?.id === visitId) S.data.cur.text = text;
  return true;
}
const unsaved = () => Object.values(S.drafts || {}).some(d => d.saved !== d.text);
// false if unsaved text couldn't be saved.
const flushText = async (visitId = S.ft?.id ?? S.data?.cur?.id) => {
  const d = S.drafts?.[visitId];
  return !d || d.saved === d.text || (await saveText(visitId, d)) !== false;
};
window.addEventListener("beforeunload", e => { if (unsaved()) { e.preventDefault(); e.returnValue = ""; } });

/* patients */
async function viewPatients(id) {
  const g = S.gen;
  S.pq = S.pq ?? "";
  await run(async () => {
    const list = await api(`/patients?q=${encodeURIComponent(S.pq)}`);
    const p = id ? await api(`/patients/${id}`) : null;
    if (stale(g)) return;
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
      <div class="muted">${ageOf(p.dob)} ${esc(p.sex || "")} · <span class="mono">${esc(p.uhid)}</span> · ${esc(p.phone)}</div>${p.address ? `<div class="muted">${esc(p.address)}</div>` : ""}${p.consent_at ? `<div class="muted consent-line">✓ Consent ${longDate(p.consent_at)}</div>` : ""}</div><span class="actions" style="gap:6px"><button class="btn small" data-a="pt-edit" data-v="${p.id}">Profile</button><button class="btn small" data-a="pt-merge" data-v="${p.id}">Merge</button></span></div>
    <span class="label">Visit history</span>
    ${visits.length ? `<div class="timeline">${visits.map(v => `<div class="tl"><div class="tl-head"><b>${longDate(v.date)}</b><span>${esc(v.doctor)}</span>${pill(v.status)}</div>
      <div class="items">${v.note ? `<button class="btn small" data-a="note-view" data-v="${v.id}">${v.note.status === "signed" ? "Note & prescription" : "Draft note"}</button>` : ""}
      ${v.documents.map(d => `<button class="btn small" data-a="open-doc" data-v="${d.id}">📄 ${esc(d.filename)}</button>`).join("")}</div>
      ${v.note?.soap?.A ? `<div class="muted" style="font-size:13.5px;margin-top:6px">${esc(v.note.soap.A)}</div>` : ""}</div>`).join("")}</div>` : `<div class="empty">—</div>`}
  </section>`;
}
const stampOf = ts => { const d = new Date(ts); return `${d.getDate()} ${d.toLocaleDateString("en-IN", { month: "short" })}, ${d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" }).toLowerCase()}`; };
async function openNoteView(visitId) {
  const v = await api(`/visits/${visitId}`), n = v.note;
  if (!n) return;
  const signed = n.status === "signed", when = ts => { const d = new Date(ts); return `${d.getDate()} ${d.toLocaleDateString("en-IN", { month: "short" })}, ${d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" }).toLowerCase()}`; };
  M = { kind: "note-view", noteId: n.id };
  const by = n.signed_by_name && n.signed_by_name !== v.doctor_name ? ` by ${esc(n.signed_by_name)}` : "";
  modal(`<div class="nv">
    <div class="nv-top"><div><h2>${esc(v.patient_name)}${v.age != null ? ", " + v.age : ""}</h2>
      <span class="muted">${longDate(v.date)} · ${esc(v.doctor_name)}${signed ? ` · Signed ${when(n.signed_at)}${by}` : ""}</span></div>
      <span class="grow"></span><span class="pill ${signed ? "s-paid" : "s-waiting"}">${signed ? "Signed" : "Draft"}</span>${signed ? `<button class="btn small primary" data-a="note-print" data-v="${n.id}">Print</button>` : ""}</div>
    <div class="nv-body">${soapRead(v, n, true)}</div></div>`, true);
}
function renderFollowUp() {
  const opts = [[3, "3 days"], [7, "1 week"], [14, "2 weeks"], [30, "1 month"]];
  modal(`<h2>Follow-up</h2>
    <div class="seg">${opts.map(([n, l]) => `<button data-a="fu-pick" data-v="${n}" aria-pressed="${addDays(TODAY, n) === M.date}">${l}</button>`).join("")}</div>
    <input class="date-pill" aria-label="Date" type="date" id="fu-date" min="${addDays(TODAY, 1)}" value="${M.date}">
    <div class="foot"><button class="btn primary" data-a="fu-go">Book</button></div>`);
}
function renderMerge() {
  const m = M;
  modal(`<h2>Merge into this patient</h2>
    ${m.other ? `<div class="hit actions" style="justify-content:space-between;align-items:center"><span><b>${esc(m.other.name)}</b> · ${esc(m.other.phone || "—")}</span><span class="mono muted">${esc(m.other.uhid)}</span></div>`
      : `<input class="input" id="mg-q" placeholder="Search name, phone or UHID" value="${esc(m.q)}" data-a="mg-q" autocomplete="off">
         <div class="pick">${m.results.filter(x => x.id !== m.id).map(x => `<button data-a="mg-pick" data-v="${x.id}"><span><b>${esc(x.name)}</b> · ${esc(x.phone || "—")}</span><span class="mono muted">${esc(x.uhid)}</span></button>`).join("")}</div>`}
    <div class="foot"><button class="btn danger" data-a="mg-go" ${m.other ? "" : "disabled"}>Merge</button></div>`);
  const q = $("#mg-q"); if (q) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
}
function openPatientEdit(p) {
  M = { kind: "pedit", id: p.id };
  modal(`<div><h2>${esc(p.name)}</h2><span class="muted">${esc(p.uhid)}${p.dob ? " · " + ageOf(p.dob) : ""}${p.sex ? " " + esc(p.sex) : ""}</span></div><div class="grid2"><label class="field">Name<input id="pe-name" value="${esc(p.name)}"></label><label class="field">Phone<input id="pe-phone" value="${esc(p.phone)}"></label></div>
    <div class="grid2"><label class="field">Date of birth<input id="pe-dob" type="date" value="${esc(p.dob || "")}"></label><label class="field">Sex<select id="pe-sex">${["M", "F", "O"].map(s => `<option ${p.sex === s ? "selected" : ""}>${s}</option>`).join("")}</select></label></div>
    <label class="field">Address<input id="pe-addr" value="${esc(p.address || "")}"></label>
    <div class="foot"><button class="btn primary" data-a="pe-save">Save</button></div>`);
}

/* administration */
async function viewAdmin(tab, sub) {
  const g = S.gen;
  const editable = S.me.is_admin;
  const tabs = [["clinic", "Clinic details"], ["rules", "Clinic rules"], ["team", "Team"], ...(editable ? [["money", "Collections"]] : [])];
  let body = "";
  if (tab === "clinic") body = `<section class="panel" style="max-width:640px"><label class="field">Clinic name<input id="ad-name" value="${esc(S.clinic.name)}"></label>
    <label class="field">Phone<input id="ad-phone" value="${esc(S.clinic.phone)}"></label><label class="field">Address<input id="ad-addr" value="${esc(S.clinic.address)}"></label>
        ${editable ? `<div class="save-row"><button class="btn primary" data-a="ad-details">Save</button></div>` : ""}</section>`;
  if (tab === "rules") body = `<section class="panel" style="max-width:700px">${rulesForm("ad", S.clinic)}
    ${editable ? `<div class="save-row"><button class="btn primary" data-a="ad-rules">Save</button></div>` : ""}</section>`;
  if (tab === "team" && editable && sub && sub !== "members") body = await teamView(sub);
  else if (tab === "money" && editable) body = await moneyView();
  else if (tab === "team") {
    const ms = await api("/members");
    body = `<section class="panel scroll"><table class="t members"><thead><tr><th>Name</th><th>Phone</th><th>Email</th><th>Role</th><th>Department</th><th>Status</th></tr></thead><tbody>
      ${ms.map(m => `<tr class="${editable ? "click" : ""}" ${editable ? `data-a="member-edit" data-v="${m.id}"` : ""}>
        <td><span class="mname"><span class="avatar sm">${esc(initials(m.name))}</span><b>${esc(m.name)}</b></span></td>
        <td>${esc(m.phone || "—")}</td><td class="muted">${esc(m.email)}</td>
        <td>${m.is_owner ? "Owner" : m.kind === "doctor" ? "Doctor" : "Staff"}</td>
        <td>${esc((m.kind === "doctor" ? m.speciality : m.designation) || "—")}</td>
        <td><span class="pill ${m.status === "active" ? "s-paid" : m.status === "invited" ? "s-waiting" : "s-no_show"}">${{ active: "Active", invited: "Invited", inactive: "Inactive" }[m.status]}</span></td></tr>`).join("")}
    </tbody></table></section>${editable ? `<div class="actions"><button class="btn primary" data-a="member-add" data-v="doctor">Add doctor</button><button class="btn" data-a="member-add" data-v="staff">Add staff</button></div>` : ""}`;
    if (editable) body = subTabs("team", "members") + body;
    S.members = ms;
  }
  if (stale(g)) return;
  view(`<div class="head"><div><h1>Administration</h1></div></div>
    <div class="actions admin-tabs">${tabs.map(([k, l]) => `<button class="btn" data-a="ad-tab" data-v="${k}" aria-pressed="${k === tab}">${l}</button>`).join("")}</div>${body}`);
}

/* team & collections */
const TEAM_TABS = [["members", "Members"], ["today", "Today"], ["leave", "Leave"], ["register", "Register"]];
const subTabs = (tab, cur) => `<div class="seg sub-seg">${TEAM_TABS.map(([k, l]) => `<button data-a="ad-sub" data-t="${tab}" data-v="${k}" aria-pressed="${k === cur}">${l}</button>`).join("")}</div>`;
const ATT = { present: ["Present", "s-paid"], late: ["Late", "s-waiting"], half: ["Half day", "s-waiting"], absent: ["Absent", "s-no_show"], leave: ["Leave", "s-soft"], off: ["Off", "s-soft"], due: ["Not in yet", "s-booked"] };
const LEAVE_ST = { pending: ["Pending", "s-waiting"], approved: ["Approved", "s-paid"], rejected: ["Rejected", "s-no_show"], cancelled: ["Cancelled", "s-cancelled"] };
const hhmm = ts => ts ? ts.slice(11, 16) : "—";
const roleOf = m => m.kind === "doctor" ? (m.speciality || "Doctor") : (m.designation || "Staff");
const monthPick = (a, ym) => { const [y, m] = ym.split("-").map(Number); return `<div class="month-picker"><span>Month</span><select data-a="${a}-m" aria-label="Month">${Array.from({ length: 12 }, (_, i) => `<option value="${i + 1}" ${i + 1 === m ? "selected" : ""}>${new Date(2000, i, 1).toLocaleDateString("en-IN", { month: "long" })}</option>`).join("")}</select><select data-a="${a}-y" aria-label="Year">${Array.from({ length: 6 }, (_, i) => new Date().getFullYear() - 4 + i).map(n => `<option ${n === y ? "selected" : ""}>${n}</option>`).join("")}</select></div>`; };
const person = m => `<span class="mname"><span class="avatar sm">${esc(initials(m.name))}</span><span class="pname"><b>${esc(m.name)}</b><small>${esc(m.role ?? roleOf(m))}</small></span></span>`;

async function teamView(sub) {
  S.adm = S.adm || { month: TODAY.slice(0, 7) };
  if (sub === "today") {
    const t = await api("/team/today");
    return `${subTabs("team", "today")}<section class="panel"><span class="label">${niceDate(t.date)}</span><div class="rows">${t.people.map(p => {
      const [l, c] = ATT[p.status] || [p.status, "s-soft"];
      const edit = p.status === "leave" || !p.working && p.status === "off" ? "" : `<div class="seg mini">${[["present", "Present"], ["late", "Late"], ["absent", "Absent"]].map(([k, x]) => `<button data-a="att-mark" data-m="${p.id}" data-v="${k}" aria-pressed="${p.status === k}">${x}</button>`).join("")}</div>`;
      return `<div class="r team-row">${person(p)}<span class="pill ${c}">${l}</span><span class="muted num">${p.check_in ? hhmm(p.check_in) + (p.check_out ? " – " + hhmm(p.check_out) : "") : p.working && p.start ? "from " + p.start : ""}</span>${edit}</div>`;
    }).join("") || `<div class="empty">—</div>`}</div></section>`;
  }
  if (sub === "leave") {
    const ls = await api(`/leave?month=${S.adm.month}`), pend = ls.filter(l => l.status === "pending"), rest = ls.filter(l => l.status !== "pending");
    const line = l => { const [st, c] = LEAVE_ST[l.status]; return `<div class="r leave-row">${person({ ...l, role: l.reason || "" })}
      <span class="num">${niceDate(l.start_date)}${l.end_date !== l.start_date ? " – " + niceDate(l.end_date) : ""}</span><span class="muted">${l.days} day${l.days > 1 ? "s" : ""}</span>
      <span class="actions" style="gap:6px;justify-content:flex-end">${l.status === "pending" ? `<button class="btn small dark" data-a="lv-approve" data-v="${l.id}">Approve</button><button class="btn small" data-a="lv-reject" data-v="${l.id}">Reject</button>` : `<span class="pill ${c}">${st}</span>${l.status === "approved" && l.end_date >= TODAY ? `<button class="btn small icon-btn" data-a="lv-cancel" data-v="${l.id}" aria-label="Cancel leave">×</button>` : ""}`}</span></div>`; };
    return `${subTabs("team", "leave")}<div class="bar-row">${monthPick("lvm", S.adm.month)}</div>
      ${pend.length ? `<section class="panel"><span class="label">Waiting for approval</span><div class="rows">${pend.map(line).join("")}</div></section>` : ""}
      <section class="panel"><span class="label">${new Date(S.adm.month + "-01T00:00").toLocaleDateString("en-IN", { month: "long", year: "numeric" })}</span><div class="rows">${rest.map(line).join("") || `<div class="empty">—</div>`}</div></section>`;
  }
  if (sub === "register") {
    const r = await api(`/team/register?month=${S.adm.month}`);
    S.reg = r;
    return `${subTabs("team", "register")}<div class="bar-row">${monthPick("rgm", S.adm.month)}<span class="grow"></span><button class="btn" data-a="reg-print">Print</button></div>
      <section class="panel scroll"><table class="t"><thead><tr><th>Name</th><th>Working days</th><th>Present</th><th>Late</th><th>Leave</th><th>Absent</th></tr></thead><tbody>
      ${r.people.map(p => `<tr><td>${person(p)}</td><td class="num">${p.working}</td><td class="num">${p.present + p.late + p.half}</td><td class="num">${p.late}</td><td class="num">${p.leave}</td><td class="num">${p.absent}</td></tr>`).join("")}</tbody></table></section>`;
  }
  return "";
}
function moneyTiles(t) {
  const m = t.by_method, st = (k, v) => `<div class="st"><small>${k}</small><b>${v}</b></div>`;
  return `<div class="stat-strip"><div class="st net"><small>Net</small><b>${rupees(t.net)}</b></div>${st("Cash", rupees(m.cash))}${st("UPI", rupees(m.upi))}${st("Card", rupees(m.card))}
    <span class="st-gap"></span>${st("Visits", t.visits)}${st("Refunds", rupees(t.refunded))}${st("Discounts", rupees(t.discounts))}${st("Waived", t.waived)}</div>`;
}
async function moneyView() {
  S.mon = S.mon || { from: TODAY, to: TODAY };
  const f = S.mon, t = await api(`/collections?start=${f.from}&end=${f.to}`);
  S.monData = t;
  const dash = n => n ? n : `<span class="muted">—</span>`;
  const tot = t.by_doctor.reduce((a, d) => ({ seen: a.seen + d.seen, walk_ins: a.walk_ins + d.walk_ins, no_shows: a.no_shows + d.no_shows, collected: a.collected + d.collected, refunded: a.refunded + d.refunded, net: a.net + d.net }), { seen: 0, walk_ins: 0, no_shows: 0, collected: 0, refunded: 0, net: 0 });
  return `<div class="bar-row money-bar"><input class="date-pill" aria-label="From" type="date" id="mr-from" max="${TODAY}" value="${f.from}" data-a="mr-range"><input class="date-pill" aria-label="To" type="date" id="mr-to" max="${TODAY}" value="${f.to}" data-a="mr-range"><button class="btn" data-a="mr-print">Print</button></div>
    <section class="panel">${moneyTiles(t)}</section>
    <section class="panel scroll"><span class="label">By doctor</span><table class="t doc-table"><thead><tr><th>Doctor</th><th class="n">Patients seen</th><th class="n">Walk-ins</th><th class="n">No-shows</th><th class="n">Collected</th><th class="n">Refunds</th><th class="n">Net</th></tr></thead><tbody>
      ${t.by_doctor.map(d => `<tr><td>${person({ name: d.name, role: d.speciality || "Doctor" })}</td><td class="n"><b>${d.seen}</b></td><td class="n">${dash(d.walk_ins)}</td><td class="n">${dash(d.no_shows)}</td><td class="n">${rupees(d.collected)}</td><td class="n">${d.refunded ? rupees(d.refunded) : dash(0)}</td><td class="n"><b>${rupees(d.net)}</b></td></tr>`).join("") || `<tr><td colspan="7" class="muted">—</td></tr>`}
      ${t.by_doctor.length > 1 ? `<tr class="tot-row"><td><b>Total</b></td><td class="n"><b>${tot.seen}</b></td><td class="n">${tot.walk_ins}</td><td class="n">${tot.no_shows}</td><td class="n">${rupees(tot.collected)}</td><td class="n">${rupees(tot.refunded)}</td><td class="n"><b>${rupees(tot.net)}</b></td></tr>` : ""}</tbody></table></section>
    <section class="panel scroll"><span class="label">By date</span><table class="t doc-table"><thead><tr><th>Date</th><th class="n">Visits</th><th class="n">Cash</th><th class="n">UPI</th><th class="n">Card</th><th class="n">Refunds</th><th class="n">Net</th></tr></thead><tbody>
      ${t.days.map(d => `<tr><td><b>${niceDate(d.date)}</b></td><td class="n">${d.visits}</td><td class="n">${rupees(d.by_method.cash)}</td><td class="n">${rupees(d.by_method.upi)}</td><td class="n">${rupees(d.by_method.card)}</td><td class="n">${d.refunded ? rupees(d.refunded) : dash(0)}</td><td class="n"><b>${rupees(d.net)}</b></td></tr>`).join("") || `<tr><td colspan="7" class="muted">—</td></tr>`}</tbody></table></section>`;
}
function printCollections() {
  const t = S.monData, f = S.mon, w = window.open("", "_blank"), m = t.by_method;
  const span = f.from === f.to ? niceDate(f.from) : `${niceDate(f.from)} – ${niceDate(f.to)}`;
  const doc = "All doctors";
  w.document.write(`<!doctype html><meta charset="utf-8"><title>Collections · ${span}</title><link href="https://fonts.googleapis.com/css2?family=Manrope:wght@500;600;700;800&display=swap" rel="stylesheet">
    <style>@page{size:A4;margin:14mm}*{box-sizing:border-box}body{font-family:Manrope,sans-serif;color:#0B1411;margin:0;background:#E8F1EC;-webkit-print-color-adjust:exact;print-color-adjust:exact}
    .page{max-width:860px;margin:28px auto;background:#F6FAF7;border-radius:28px;padding:40px 44px}header{display:flex;justify-content:space-between;align-items:flex-start;background:#0B1411;color:#E8F1EC;border-radius:22px;padding:22px 26px}
    h1{margin:0;font-size:22px;font-weight:800}small{color:#9FB1A9;font-size:12.5px;font-weight:600;display:block;margin-top:4px}.lime{color:#B6F36B;font-weight:800;font-size:16px}
    .tiles{display:flex;gap:10px;margin:22px 0 6px}.tk{flex:1;background:#E8F1EC;border-radius:16px;padding:12px 16px}.tk.big{background:#0B1411;color:#B6F36B}.tk small{color:#6B7C75;margin:0 0 2px;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase}.tk b{font-size:20px}
    h2{font-size:11px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:#6B7C75;margin:26px 0 10px}table{width:100%;border-collapse:separate;border-spacing:0;font-size:14px}th{text-align:left;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:#6B7C75;padding:0 12px 8px}
    td{padding:11px 12px}.n{text-align:right}tr:nth-child(even) td{background:#E8F1EC}tr:nth-child(even) td:first-child{border-radius:12px 0 0 12px}tr:nth-child(even) td:last-child{border-radius:0 12px 12px 0}tr.tot td{background:#0B1411;color:#E8F1EC;font-weight:800}tr.tot td:first-child{border-radius:12px 0 0 12px}tr.tot td:last-child{border-radius:0 12px 12px 0;color:#B6F36B}
    @media print{body{background:#fff}.page{margin:0;padding:0;background:#fff;border-radius:0;max-width:none}}</style>
    <div class="page"><header><div><h1>${esc(S.clinic.name)}</h1><small>Collections · ${esc(doc)}</small></div><div style="text-align:right"><span class="lime">${span}</span><small>${t.visits} paid visits</small></div></header>
    <div class="tiles"><div class="tk big"><small style="color:#9FB1A9">Net</small><b>${rupees(t.net)}</b></div><div class="tk"><small>Cash</small><b>${rupees(m.cash)}</b></div><div class="tk"><small>UPI</small><b>${rupees(m.upi)}</b></div><div class="tk"><small>Card</small><b>${rupees(m.card)}</b></div><div class="tk"><small>Refunds</small><b>${rupees(t.refunded)}</b></div></div>
    <h2>By doctor</h2><table><tr><th>Doctor</th><th class="n">Patients seen</th><th class="n">Walk-ins</th><th class="n">No-shows</th><th class="n">Collected</th><th class="n">Refunds</th><th class="n">Net</th></tr>
    ${t.by_doctor.map(d => `<tr><td><b>${esc(d.name)}</b></td><td class="n">${d.seen}</td><td class="n">${d.walk_ins}</td><td class="n">${d.no_shows}</td><td class="n">${rupees(d.collected)}</td><td class="n">${rupees(d.refunded)}</td><td class="n"><b>${rupees(d.net)}</b></td></tr>`).join("")}
    <tr class="tot"><td>Total</td><td class="n">${t.by_doctor.reduce((a, d) => a + d.seen, 0)}</td><td class="n">${t.by_doctor.reduce((a, d) => a + d.walk_ins, 0)}</td><td class="n">${t.by_doctor.reduce((a, d) => a + d.no_shows, 0)}</td><td class="n">${rupees(t.collected)}</td><td class="n">${rupees(t.refunded)}</td><td class="n">${rupees(t.net)}</td></tr></table></div><script>onload=()=>setTimeout(print,300)<\/script>`);
  w.document.close();
}
function openLeave(memberId) {
  const admin = S.me.is_admin && !memberId?.self;
  M = { kind: "leave-new" };
  modal(`<h2>Leave</h2>
    ${admin ? `<label class="field">Person<select id="lv-who">${(S.members || []).filter(m => m.status === "active").map(m => `<option value="${m.id}" ${m.id === memberId ? "selected" : ""}>${esc(m.name)}</option>`).join("")}</select></label>` : ""}
    <div class="date-row"><input class="date-pill" aria-label="From" type="date" id="lvn-from" value="${TODAY}"><input class="date-pill" aria-label="To" type="date" id="lvn-to" value="${TODAY}"></div>
    <label class="field">Reason<input id="lvn-why"></label>
    <div class="foot"><button class="btn primary" data-a="lvn-save">${S.me.is_admin ? "Save" : "Request"}</button></div>`);
}
function printRegister() {
  const r = S.reg, w = window.open("", "_blank");
  const mon = new Date(r.month + "-01T00:00").toLocaleDateString("en-IN", { month: "long", year: "numeric" });
  w.document.write(`<!doctype html><meta charset="utf-8"><title>Register · ${mon}</title><link href="https://fonts.googleapis.com/css2?family=Manrope:wght@500;600;700;800&display=swap" rel="stylesheet">
    <style>@page{size:A4 landscape;margin:14mm}*{box-sizing:border-box}body{font-family:Manrope,sans-serif;color:#0B1411;margin:0;background:#E8F1EC;-webkit-print-color-adjust:exact;print-color-adjust:exact}
    .page{max-width:980px;margin:28px auto;background:#F6FAF7;border-radius:28px;padding:40px 44px}
    header{display:flex;justify-content:space-between;align-items:flex-start;background:#0B1411;color:#E8F1EC;border-radius:22px;padding:22px 26px;margin-bottom:26px}
    h1{margin:0;font-size:22px;font-weight:800}small{color:#9FB1A9;font-size:12.5px;font-weight:600;display:block;margin-top:4px}.lime{color:#B6F36B;font-weight:800;font-size:16px}
    table{width:100%;border-collapse:separate;border-spacing:0;font-size:14.5px}th{text-align:left;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:#6B7C75;padding:0 14px 8px}
    td{padding:12px 14px}td.n,th.n{text-align:center}tr:nth-child(even) td{background:#E8F1EC}tr:nth-child(even) td:first-child{border-radius:12px 0 0 12px}tr:nth-child(even) td:last-child{border-radius:0 12px 12px 0}
    td small{color:#6B7C75;margin:0}@media print{body{background:#fff}.page{margin:0;padding:0;background:#fff;border-radius:0;max-width:none}}</style>
    <div class="page"><header><div><h1>${esc(S.clinic.name)}</h1><small>Working days register</small></div><div style="text-align:right"><span class="lime">${mon}</span><small>${r.people.length} ${r.people.length === 1 ? "person" : "people"}</small></div></header>
    <table><tr><th>Name</th><th class="n">Working days</th><th class="n">Present</th><th class="n">Late</th><th class="n">Leave</th><th class="n">Absent</th></tr>${r.people.map(p => `<tr><td><b>${esc(p.name)}</b><small>${esc(p.role || "")}</small></td><td class="n">${p.working}</td><td class="n">${p.present + p.late + p.half}</td><td class="n">${p.late}</td><td class="n">${p.leave}</td><td class="n">${p.absent}</td></tr>`).join("")}</table></div><script>onload=()=>setTimeout(print,300)<\/script>`);
  w.document.close();
}

/* events */
document.addEventListener("click", e => {
  const t = e.target.closest("[data-a]"); if (!t) return;
  const a = t.dataset.a, v = t.dataset.v;
  if (a === "scrim") { if (e.target === t && M?.kind !== "sched") closeModal(); return; }
  if (["lim", "mb-admin", "mr-range", "lvm-m", "lvm-y", "rgm-m", "rgm-y", "free-text", "up-file", "mg-q", "vf-q", "vf-doc", "pay-disc", "bk-q", "pt-q", "cs-q", "bk-date", "bk-doc", "sc-doc", "sc-month-picker", "sc-year-picker", "cs-doc"].includes(a)) return;
  e.preventDefault();
  const D = S.data;
  run(async () => {
    switch (a) {
      case "logout": logout(); break;
      case "ob-next": await obNext(Number(v)); break;
      case "ob-finish": await obFinish(); break;
      case "ob-back": { const st = Number(v); if (st === 1) { if (S.me) { logout(); } else go("#/login"); } else viewOnboarding(st - 1); break; }
      case "renew-invite": { const r = await api(`/members/${v}/invite`, { body: {} }); openShare("invite", Number(v), r.invite_code, r.email_enabled); break; }
      case "reset-link": { const r = await api(`/members/${v}/reset-link`, { body: {} }); openShare("reset", Number(v), r.code, r.email_enabled); break; }
      case "share-copy": copyLink(M.link, M.what === "invite" ? "Invite link copied · valid 7 days" : "Reset link copied · valid 2 hours"); break;
      case "share-email": { const r = M.what === "invite" ? await api(`/members/${M.id}/invite/email`, { body: {} }) : await api(`/members/${M.id}/reset-link/email`, { body: { code: M.code } });
        toast(`${M.what === "invite" ? "Invite" : "Reset link"} emailed to ${r.email}`); break; }
      case "account": await openAccount(); break;
      case "ac-save": {
        const nw = $("#ac-new").value;
        if (nw && nw !== $("#ac-new2").value) return toast("New passwords don't match", true);
        const doc = S.me.kind === "doctor", role = $("#ac-role").value;
        const me = await api("/me", { method: "PUT", body: { name: $("#ac-name").value, email: $("#ac-email").value, phone: $("#ac-phone").value, speciality: doc ? role : "", designation: doc ? "" : role } });
        if (nw) await api("/auth/change-password", { body: { current: $("#ac-cur").value, new: nw } });
        S.me = me; S.doctors = await api("/doctors"); S.shellFor = null; closeModal(); toast("Saved"); route(); break; }
      case "my-schedule": await openSchedules(S.me.id, true); break;
      case "pw-save": {
        if ($("#ac-new").value !== $("#ac-new2").value) return toast("New passwords don't match", true);
        await api("/auth/change-password", { body: { current: $("#ac-cur").value, new: $("#ac-new").value } }); closeModal(); toast("Password changed"); break; }
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
      case "bk-wait": { await api("/waitlist", { body: { patient_id: M.patient.id, doctor_id: M.doctorId, date: M.date, session: M.session } });
        M.done = `<h2>Added to waitlist</h2><div class="result">${esc(M.patient.name)} · ${niceDate(M.date)}</div><div class="foot"><button class="btn primary" data-a="close-refresh">Done</button></div>`; renderBooking(); break; }
      case "wl-book": { const r = await api(`/waitlist/${v}/book`, { body: {} }); toast(`Booked · ${r.token_label || r.patient_name}`); refresh(); break; }
      case "wl-del": await api(`/waitlist/${v}`, { method: "DELETE" }); refresh(); break;
      case "fu-open": M = { kind: "followup", id: Number(v), date: addDays(TODAY, 7) }; renderFollowUp(); break;
      case "fu-pick": M.date = addDays(TODAY, Number(v)); renderFollowUp(); break;
      case "fu-go": { const d = $("#fu-date").value || M.date; const r = await api(`/visits/${M.id}/follow-up`, { body: { date: d } });
        M = { kind: "done" }; modal(`<h2>${r.waitlisted ? "Day is full" : "Follow-up booked"}</h2><div class="result">${niceDate(d)}${r.waitlisted ? " · added to waitlist" : r.token_label ? ` · token ${r.token_label}` : ""}</div><div class="foot"><button class="btn primary" data-a="close">Done</button></div>`); break; }
      case "register": openRegister(v); break;
      case "rg-use": { const p = M.same.find(x => x.id === Number(v));
        if (M.back) { const back = M.back; M = back; M.patient = p; renderBooking(); } else { closeModal(); location.hash.startsWith("#/consult") ? go(`#/consult?doctor=${S.data.doctorId}&patient=${p.id}`) : go(`#/patients/${p.id}`); }
        break; }
      case "pt-merge": M = { kind: "merge", id: Number(v), q: "", results: [] }; renderMerge(); break;
      case "mg-pick": M.other = M.results.find(x => x.id === Number(v)); renderMerge(); break;
      case "mg-go": { const p = await api(`/patients/${M.id}/merge`, { body: { other_id: M.other.id } }); closeModal(); toast(`Merged into ${p.uhid}`); go(`#/patients/${p.id}`); route(); break; }
      case "rg-back": { const back = M.back; M = back; renderBooking(); break; }
      case "rg-save": case "rg-new": {
        const f = a === "rg-new" ? M.form : { name: $("#rg-name").value, phone: $("#rg-phone").value, dob: $("#rg-dob").value || null, sex: $("#rg-sex").value, address: $("#rg-addr").value, consent: $("#rg-consent").checked };
        if (!f.consent) return toast("Tick patient consent", true);
        if (a === "rg-save") {
          const same = await api(`/patients/check?name=${encodeURIComponent(f.name)}&phone=${encodeURIComponent(f.phone)}&dob=${f.dob || ""}`);
          if (same.length) {
            M.form = f; M.same = same;
            modal(`<h2>Same person?</h2><div class="pick">${same.map(x => `<button data-a="rg-use" data-v="${x.id}"><span><b>${esc(x.name)}</b> · ${esc(x.phone || "—")}${x.dob ? " · " + ageOf(x.dob) : ""} ${esc(x.sex || "")}</span><span class="mono muted">${esc(x.uhid)}</span></button>`).join("")}</div>
              <div class="foot"><button class="btn primary" data-a="rg-new">New patient</button></div>`);
            break;
          }
        }
        const p = await api("/patients", { body: f });
        toast(`Registered ${p.uhid}`);
        if (M.back) { const back = M.back; M = back; M.patient = p; renderBooking(); } else { closeModal(); location.hash.startsWith("#/consult") ? go(`#/consult?doctor=${S.data.doctorId}&patient=${p.id}`) : go(`#/patients/${p.id}`); }
        break; }
      case "arrive": openArrive([...D.columns.booked].find(x => x.id === Number(v))); break;
      case "pay": M.pay = v; document.querySelectorAll("#pay-seg button").forEach(b => b.setAttribute("aria-pressed", b.dataset.v === v)); payShow(); break;
      case "arrive-paid": { const r = await api(`/visits/${M.v.id}/arrive`, { body: readPay(M.v.fee) }); M = { kind: "done" }; modal(paidDone("Sent to Waiting", r)); break; }
      case "receipt": openReceipt(v); break;
      case "v-more": { const vis = Object.values(D.columns).flat().find(x => x.id === Number(v)); M = { kind: "more" };
        modal(`<h2>${esc(vis.patient_name)}</h2><div class="more-list">${vis.paid_at ? `<button class="btn" data-a="receipt" data-v="${v}">Receipt</button>` : ""}
          ${(vis.refundable || 0) > 0 ? `<button class="btn" data-a="refund" data-v="${v}">Refund</button>` : ""}
          ${vis.status === "waiting" && !vis.is_walk_in ? `<button class="btn" data-a="undo-arrival" data-v="${v}">Undo arrival</button>` : ""}
          ${vis.status === "booked" ? `<button class="btn" data-a="upload" data-v="${v}">Add document</button><button class="btn danger" data-a="cancel" data-v="${v}">Cancel booking</button>` : ""}</div>
          `); break; }
      case "refund": openRefund(Object.values(D.columns).flat().find(x => x.id === Number(v))); break;
      case "rf-reason": $("#rf-why").value = v; document.querySelectorAll('[data-a="rf-reason"]').forEach(b => b.setAttribute("aria-pressed", b.dataset.v === v)); break;
      case "refund-go": { const r = await api(`/visits/${M.v.id}/refund`, { body: { amount: Number($("#rf-amt").value) || null, reason: $("#rf-why").value } }); closeModal(); toast(`Refunded ${rupees(r.refund_amount)}`); refresh(); break; }
      case "q-move": await api(`/visits/${v}/queue?direction=${t.dataset.d}`, { body: {} }); refresh(); break;
      case "late": await api(`/visits/${v}/late`, { body: {} }); refresh(); break;
      case "undo-arrival": { closeModal(); const r = await api(`/visits/${v}/undo-arrival`, { body: {} }); toast(`${r.patient_name} back to Booked${r.refund_amount ? " · refund " + rupees(r.refund_amount) : ""}`); refresh(); break; }
      case "bk-session": M.session = v; M.token = null; await loadAvail(); break;
      case "bk-reason": M.reason = v; renderBooking(); break;
      case "vf-st": S.vf.st = v; document.querySelectorAll('[data-a="vf-st"]').forEach(b => b.setAttribute("aria-pressed", b.dataset.v === v));
        { const r = $("#ops-rows"); if (r && S.data?.visits) r.innerHTML = opsRows(S.data.visits); } break;
      case "cancel": { const vis = D.columns.booked.find(x => x.id === Number(v)); M = { kind: "cancel", id: v, reason: "" };
        modal(`<h2>Cancel booking · ${esc(vis.patient_name)}</h2>${reasonChips(CANCEL_REASONS, "", "cn-reason")}<div class="foot"><button class="btn danger" data-a="cancel-go" data-v="${v}">Cancel booking</button></div>`); break; }
      case "cn-reason": M.reason = v; document.querySelectorAll('[data-a="cn-reason"]').forEach(b => b.setAttribute("aria-pressed", b.dataset.v === v)); break;
      case "cancel-go": await api(`/visits/${v}/cancel`, { body: { reason: M.reason || "" } }); closeModal(); toast("Booking cancelled"); refresh(); break;
      case "end-session": { const r = await api(`/operations/end-session?doctor_id=${v}&date=${S.date}&session=${t.dataset.s || ""}`, { body: {} }); toast(`${r.no_shows} marked as no-show`); refresh(); break; }
      case "ses-add": case "ses-del": { const pp = t.dataset.p, vals = readLimit(pp);
        if (a === "ses-add") { const last = vals.sessions[vals.sessions.length - 1]; const hm = m => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`, st = Math.min(toMin(last.end) + 60, 22 * 60); vals.sessions.push({ start: hm(st), end: hm(Math.min(st + 180, 23 * 60 + 59)) }); }
        else vals.sessions.splice(Number(v), 1);
        $(`#${pp}-lim`).innerHTML = limitBlock(pp, vals); break; }
      case "lv-open": M.leave = { from: M.sel && M.sel >= TODAY ? M.sel : TODAY, to: M.sel && M.sel >= TODAY ? M.sel : TODAY, all: v === "all" }; renderSched(); break;
      case "lv-who": M.leave.from = $("#lv-from").value; M.leave.to = $("#lv-to").value; M.leave.all = v === "all"; renderSched(); break;
      case "lv-save": { const l = M.leave, from = $("#lv-from").value, to = $("#lv-to").value || from;
        const r = await api("/schedules/leave", { body: { start_date: from, end_date: to, doctor_id: l.all ? null : M.doctorId, off: v === "1" } });
        toast(`${r.days} day${r.days > 1 ? "s" : ""} ${v === "1" ? (M.leave.all ? "holiday" : "leave") : "working"}${r.bookings_affected ? ` · ${r.bookings_affected} booking${r.bookings_affected > 1 ? "s" : ""} to move` : ""}`, r.bookings_affected > 0);
        M.leave = null; await loadMonth(); break; }
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
      case "ad-sub": go(`#/admin/${t.dataset.t}/${v}`); break;
      case "att-mark": await api(`/attendance/${t.dataset.m}/${TODAY}`, { method: "PUT", body: { status: v, check_in: v === "absent" ? null : new Date().toTimeString().slice(0, 5) } }); route(); break;
      case "lv-new": if (!S.members) S.members = await api("/members"); openLeave(); break;
      case "lvn-save": { const who = $("#lv-who")?.value;
        const r = await api("/leave", { body: { start_date: $("#lvn-from").value, end_date: $("#lvn-to").value || $("#lvn-from").value, reason: $("#lvn-why").value, member_id: who ? Number(who) : null } });
        closeModal(); toast(r.status === "pending" ? "Leave requested" : r.bookings_affected ? `Leave saved · ${r.bookings_affected} booking${r.bookings_affected > 1 ? "s" : ""} to move` : "Leave saved", r.bookings_affected > 0); route(); break; }
      case "lv-approve": case "lv-reject": case "lv-cancel": { const r = await api(`/leave/${v}/${a.slice(3)}`, { body: {} });
        toast({ approve: "Approved", reject: "Rejected", cancel: "Leave cancelled" }[a.slice(3)] + (r.bookings_affected ? ` · ${r.bookings_affected} booking${r.bookings_affected > 1 ? "s" : ""} to move` : ""), r.bookings_affected > 0);
        M?.kind === "account" ? openAccount() : route(); break; }
      case "reg-print": printRegister(); break;
      case "mr-print": printCollections(); break;
      case "att-in": case "att-out": await api(`/attendance/check-${a === "att-in" ? "in" : "out"}`, { body: {} }); toast(a === "att-in" ? "Checked in" : "Checked out"); openAccount(); break;
      case "my-leave": openLeave({ self: true }); break;
      case "mb-schedule": closeModal(); await openSchedules(Number(v)); break;
      case "ad-details": S.shellFor = null; S.clinic = await api("/clinic", { method: "PUT", body: { name: $("#ad-name").value, phone: $("#ad-phone").value, address: $("#ad-addr").value } }); toast("Saved"); route(); break;
      case "ad-rules": S.clinic = await api("/clinic/rules", { method: "PUT", body: readRules("ad") }); toast("Rules saved."); route(); break;
      case "pt-open": go(`#/patients/${v}`); break;
      case "pt-edit": openPatientEdit(await api(`/patients/${v}`)); break;
      case "pe-save": await api(`/patients/${M.id}`, { method: "PATCH", body: { name: $("#pe-name").value, phone: $("#pe-phone").value, dob: $("#pe-dob").value || null, sex: $("#pe-sex").value, address: $("#pe-addr").value } }); closeModal(); toast("Saved"); route(); break;
      case "cs-tab": await flushText(); if (D.cur?.note && $("#soap-S")) D.cur.note.content = readNote(); S.ctab = v; renderConsult(); break;
      case "cs-side": S.cside = v; renderConsult(); break;
      case "cs-left": S.cleft = v; refreshConsult(); break;
      case "cs-patient": go(`#/consult?doctor=${D.doctorId}&patient=${v}`); break;
      case "cs-draft-go": if (!(await flushText(Number(v)))) break; await api(`/visits/${v}/note/draft`, { body: {} }); S.ctab = "note"; toast("Draft ready."); refreshConsult(); break;
      case "note-sign-ro": await api(`/notes/${v}`, { method: "PUT", body: D.cur.note.content }); await api(`/notes/${v}/sign`, { body: {} }); toast("Signed. Visit complete."); refreshConsult(); break;
      case "cs-next-mic": { const r = await api(`/consultation/next?doctor_id=${v}`, { body: {} }); S.ctab = "dictate"; await new Promise(res => { const once = () => { window.removeEventListener("hashchange", once); setTimeout(res, 300); }; window.addEventListener("hashchange", once); go(`#/consult/${r.id}?doctor=${v}`); }); startMic(r.id); break; }
      case "cs-collapse": S.rightCollapsed = !S.rightCollapsed; renderConsult(); break;
      case "mic-pause": pauseMic(); break;
      case "mic-resume": resumeMic(); break;
      case "mic-stop": await stopMic(); break;
      case "note-edit": S.noteEdit = true; renderConsult(); break;
      case "note-done": { const n = D.cur.note; await api(`/notes/${n.id}`, { method: "PUT", body: readNote() }); S.noteEdit = false; toast("Saved"); refreshConsult(); break; }
      case "cs-mic": {
        const cur = D.cur;
        if (S.recState) { await stopMic(); break; }
        if (S.dictBy === "deepgram") S.audioCtx = audioContext();
        if (cur.status === "waiting") { await api(`/visits/${cur.id}/start`, { body: {} }); }
        if (S.ctab === "brief") S.ctab = "dictate";
        await S.reloadConsult(); startMic(cur.id); break; }
      case "cs-next": { const r = await api(`/consultation/next?doctor_id=${v}`, { body: {} }); S.ctab = "brief"; go(`#/consult/${r.id}?doctor=${v}`); break; }
      case "cs-open": go(`#/consult/${v}?doctor=${D.doctorId}`); break;
      case "cs-start": await api(`/visits/${v}/start`, { body: {} }); refreshConsult(); break;
      case "cs-brief": await api(`/visits/${v}/brief`, { body: {} }); toast("Brief updated"); refreshConsult(); break;
      case "cs-redraft":   // asks first only when the doctor changed the draft by hand
        if (D.cur?.note?.edited) { modal(`<h2>Replace your edits?</h2><div class="foot"><button class="btn danger" data-a="cs-redraft-go" data-v="${v}">Replace</button></div>`); break; }
      // falls through
      case "cs-redraft-go": if (a === "cs-redraft-go") closeModal();
      // falls through
      case "cs-draft": if (!(await flushText(Number(v)))) break; if (S.recState) await stopMic(); S.ctab = "note"; S.drafting = Number(v); S.noteEdit = false; renderConsult();
        try { await Promise.all([api(`/visits/${v}/note/draft`, { body: {} }), new Promise(r => setTimeout(r, 1400))]); } finally { S.drafting = null; S.dictDone = null; } refreshConsult(); break;
      case "mic": if (S.recState) await stopMic(); else { S.ctab = "dictate"; startMic(Number(v)); } break;
      case "spk": S.speaker = v; document.querySelectorAll('[data-a="spk"]').forEach(b => b.setAttribute("aria-pressed", b.dataset.v === v)); break;
      case "rx-add": { const n = D.cur.note; n.content = readNote(); n.content.rx.push({ medicine: "", dose: "", duration: "", instructions: "" }); rerenderNote(); break; }
      case "rx-del": { const n = D.cur.note; n.content = readNote(); n.content.rx.splice(Number(v), 1); rerenderNote(); break; }
      case "note-save": await api(`/notes/${v}`, { method: "PUT", body: readNote() }); toast("Draft saved"); refreshConsult(); break;
      case "note-sign": await api(`/notes/${v}`, { method: "PUT", body: readNote() }); await api(`/notes/${v}/sign`, { body: {} }); toast("Signed. Visit complete."); refreshConsult(); break;
      case "note-view": await openNoteView(Number(v)); break;
      case "note-print": window.open(`/api/notes/${v}/print?auto=1&token=${encodeURIComponent(S.token)}`, "_blank"); break;
      case "print": window.open(`/api/notes/${v}/print?token=${encodeURIComponent(S.token)}`, "_blank"); break;
      case "open-doc": { const res = await fetch(`/api/documents/${v}/file`, { headers: { Authorization: "Bearer " + S.token } }); window.open(URL.createObjectURL(await res.blob()), "_blank"); break; }
      case "cite": if (v.startsWith("T")) { const src = sourceOf(D.cur, v); if (!src) break;
        if (S.ctab !== "dictate") { S.ctab = "dictate"; renderConsult(); }
        const ta = $("#free-text"), at = ta.value.indexOf(src.text); ta.focus(); if (at >= 0) ta.setSelectionRange(at, at + src.text.length); break; }
      { const el = document.getElementById("ev-" + v); if (el) { el.scrollIntoView({ behavior: "smooth", block: "nearest" }); el.classList.add("hl"); setTimeout(() => el.classList.remove("hl"), 1800); } else toast(v.startsWith("N") ? "From an earlier note." : "Source: " + v); break; }
    }
  });
});
function payShow() {
  const w = M?.pay === "waive", disc = Number($("#pay-disc")?.value) || 0, fee = Number($("#pay-disc")?.dataset.fee) || 0;
  const dw = $("#pay-disc-wrap"), rw = $("#pay-why-wrap"), due = $("#pay-due");
  if (dw) dw.hidden = w;
  if (rw) rw.hidden = !(w || disc > 0);
  if (due) due.textContent = rupees(w ? 0 : Math.max(0, fee - disc));
}
function rerenderNote() { const c = $("#cx-center"); if (c) c.innerHTML = center(); restoreFree(); }
document.addEventListener("input", e => {
  const a = e.target.dataset?.a;
  if (a === "bk-q") searchPatients(e.target.value);
  if (a === "pay-disc") payShow();
  if (a === "free-text") { if (S.dict) S.dict = typedOver(S.dict, e.target); edit(Number(e.target.dataset.v), e.target.value); }
  if (a === "up-file") { const f = e.target.files[0]; $("#up-name").textContent = f ? f.name : "No file"; $(".file-drop").classList.toggle("has", !!f); }
  if (a === "mg-q") { M.q = e.target.value; clearTimeout(searchT); searchT = setTimeout(() => run(async () => { if (M?.kind !== "merge") return; M.results = M.q.trim() ? await api(`/patients?q=${encodeURIComponent(M.q)}`) : []; renderMerge(); }), 180); }
  if (a === "vf-q") { S.vf.q = e.target.value; const r = $("#ops-rows"); if (r && S.data?.visits) r.innerHTML = opsRows(S.data.visits); }
  if (a === "cs-q") { S.cq = e.target.value; clearTimeout(S.cqt); S.cqt = setTimeout(async () => { await run(S.reloadConsult); const q = $("#cs-q"); if (q) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); } }, 220); }
  if (a === "pt-q") { S.pq = e.target.value; clearTimeout(S.pqt); S.pqt = setTimeout(async () => { await viewPatients(Number(location.hash.split("/")[2]) || null); const q = $("#pt-q"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }, 200); }
});
document.addEventListener("change", e => {
  const a = e.target.dataset?.a;
  if (a === "ops-date") { S.date = e.target.value || TODAY; route(); }
  if (a === "mb-admin") { const box = $("#mb-s-administration"); if (box) { box.disabled = !e.target.checked; if (!e.target.checked) box.checked = false; } }
  if (a === "mr-range") { const from = $("#mr-from").value || TODAY, to = $("#mr-to").value || from; Object.assign(S.mon, from <= to ? { from, to } : { from: to, to: from }); route(); }
  if (/^(lvm|rgm)-[my]$/.test(a)) { const [y, m] = S.adm.month.split("-").map(Number); const nm = a.endsWith("-m") ? Number(e.target.value) : m, ny = a.endsWith("-y") ? Number(e.target.value) : y; S.adm.month = `${ny}-${String(nm).padStart(2, "0")}`; route(); }
  if (a === "vf-doc") { S.vf.doc = e.target.value; const r = $("#ops-rows"); if (r && S.data?.visits) r.innerHTML = opsRows(S.data.visits); }
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
});

/* enhancers */
const chevron = '<svg class="dd-chev" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 10l5 5 5-5"/></svg>';
const calIcon = '<svg class="dd-chev" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="5" width="17" height="15" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/></svg>';
function textOf(el) { return [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join("").trim(); }
function enhance(root) {
  root.querySelectorAll("label.field:not(.fl)").forEach(f => {
    const ctl = f.querySelector("input, select, textarea"); if (!ctl) return;
    const text = textOf(f); [...f.childNodes].forEach(n => { if (n.nodeType === 3) n.remove(); });
    if (!text) return;
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
  const wrap = document.createElement("div"); wrap.className = "dd date" + (inp.classList.contains("top-date") ? " top-date" : "") + (inp.classList.contains("date-pill") ? " date-pill" : "");
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
