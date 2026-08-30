const API = window.RELIEFOS_API_URL || "";
const actorId = localStorage.getItem("reliefos.actorId") || `web_${crypto.randomUUID()}`;
localStorage.setItem("reliefos.actorId", actorId);
let caseMap;
let caseMarkers = [];

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function headers(role = "citizen", extra = {}) {
  return { "Content-Type": "application/json", "X-Actor-ID": actorId, "X-Actor-Role": role, ...extra };
}

async function apiFetch(path, options = {}) {
  const response = await fetch(`${API}${path}`, options);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try { detail = (await response.json()).detail || detail; } catch (_) { /* response was not JSON */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (response.status === 204) return null;
  return response.json();
}

function showView(name) {
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.view === name));
  if (name === "operations") loadOperations();
}

$$('.tab').forEach((tab) => tab.addEventListener("click", () => showView(tab.dataset.view)));

function updateNetwork() {
  const online = navigator.onLine;
  $("#networkStatus").textContent = online ? "Online" : "Offline — reports will be queued";
  $("#networkStatus").classList.toggle("offline", !online);
  renderQueuedReports();
  if (online) flushQueuedReports();
}
window.addEventListener("online", updateNetwork);
window.addEventListener("offline", updateNetwork);

function selectedValues(container) {
  return $$(`${container} input:checked`).map((item) => item.value);
}

function useGps(callback) {
  if (!navigator.geolocation) return callback(new Error("GPS is not available in this browser"));
  navigator.geolocation.getCurrentPosition(
    (position) => callback(null, position.coords),
    (error) => callback(error),
    { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 },
  );
}

$("#gpsButton").addEventListener("click", () => {
  $("#locationMessage").textContent = "Requesting GPS…";
  useGps((error, coords) => {
    if (error) return $("#locationMessage").textContent = `GPS unavailable: ${error.message}`;
    $("[name=latitude]").value = coords.latitude;
    $("[name=longitude]").value = coords.longitude;
    $("[name=gps_accuracy_meters]").value = coords.accuracy;
    $("#locationMessage").textContent = `${coords.latitude.toFixed(5)}, ${coords.longitude.toFixed(5)} (±${Math.round(coords.accuracy)} m)`;
  });
});

function buildCasePayload(form) {
  const data = new FormData(form);
  const number = (name) => data.get(name) ? Number(data.get(name)) : null;
  return {
    case_type: data.get("case_type"),
    reporter: { name: data.get("reporter_name") || null, phone: data.get("reporter_phone") || null },
    affected_people_count: Number(data.get("affected_people_count")),
    description: data.get("description"),
    latitude: number("latitude"),
    longitude: number("longitude"),
    gps_accuracy_meters: number("gps_accuracy_meters"),
    location_description: data.get("location_description") || null,
    danger_indicators: selectedValues("#dangerOptions"),
    requested_assistance: selectedValues("#assistanceOptions"),
    preferred_language: data.get("preferred_language"),
  };
}

function queueReport(payload, idempotencyKey) {
  const queue = JSON.parse(localStorage.getItem("reliefos.reportQueue") || "[]");
  queue.push({ payload, idempotencyKey, queuedAt: new Date().toISOString() });
  localStorage.setItem("reliefos.reportQueue", JSON.stringify(queue));
  renderQueuedReports();
}

async function submitCasePayload(payload, idempotencyKey) {
  return apiFetch("/v1/cases", {
    method: "POST", headers: headers("citizen", { "Idempotency-Key": idempotencyKey }), body: JSON.stringify(payload),
  });
}

async function flushQueuedReports() {
  const queue = JSON.parse(localStorage.getItem("reliefos.reportQueue") || "[]");
  if (!queue.length) return;
  const remaining = [];
  for (const item of queue) {
    try {
      const result = await submitCasePayload(item.payload, item.idempotencyKey);
      saveCaseAccess(result);
    } catch (_) { remaining.push(item); }
  }
  localStorage.setItem("reliefos.reportQueue", JSON.stringify(remaining));
  renderQueuedReports();
}

function renderQueuedReports() {
  const queue = JSON.parse(localStorage.getItem("reliefos.reportQueue") || "[]");
  const panel = $("#queuedReports");
  panel.classList.toggle("hidden", !queue.length);
  panel.innerHTML = queue.length ? `<strong>${queue.length} report${queue.length > 1 ? "s" : ""} waiting to synchronize</strong><p>Keep this page installed. ReliefOS will retry when connectivity returns.</p>` : "";
}

function saveCaseAccess(result) {
  localStorage.setItem(`reliefos.case.${result.case.case_id}`, result.access_token);
}

async function uploadMedia(caseResult, file) {
  if (!file) return;
  const token = caseResult.access_token;
  const prepared = await apiFetch(`/v1/cases/${caseResult.case.case_id}/media-upload`, {
    method: "POST",
    headers: headers("citizen", { "X-Case-Access-Token": token }),
    body: JSON.stringify({ file_name: file.name, content_type: file.type, size_bytes: file.size }),
  });
  const target = prepared.upload_url.startsWith("http") ? prepared.upload_url : `${API}${prepared.upload_url}`;
  let body = file;
  let uploadHeaders = prepared.headers;
  if (prepared.method === "POST" && prepared.form_fields) {
    const form = new FormData();
    Object.entries(prepared.form_fields).forEach(([key, value]) => form.append(key, value));
    form.append("file", file);
    body = form;
    uploadHeaders = {};
  }
  const response = await fetch(target, { method: prepared.method, headers: uploadHeaders, body });
  if (!response.ok) throw new Error("The case was created, but the media upload failed");
}

$("#caseForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#submitCase");
  const panel = $("#caseResult");
  const payload = buildCasePayload(event.currentTarget);
  const idempotencyKey = crypto.randomUUID();
  const media = new FormData(event.currentTarget).get("media");
  button.disabled = true;
  button.textContent = "Saving essential report…";
  try {
    if (!navigator.onLine) {
      queueReport(payload, idempotencyKey);
      panel.className = "result";
      panel.innerHTML = "<strong>Saved on this device.</strong><p>The report will synchronize automatically when a connection returns.</p>";
      return;
    }
    const result = await submitCasePayload(payload, idempotencyKey);
    saveCaseAccess(result);
    panel.className = "result";
    panel.innerHTML = `<strong>Case received: ${escapeHtml(result.case.case_id)}</strong><p>Priority ${result.case.priority} · Status ${result.case.status.replaceAll("_", " ")}</p><p>Save this case ID. It does not guarantee an arrival time.</p>`;
    if (media && media.size) {
      button.textContent = "Uploading media…";
      await uploadMedia(result, media);
      panel.innerHTML += "<p>Media uploaded successfully.</p>";
    }
    event.currentTarget.reset();
  } catch (error) {
    if (!navigator.onLine || error instanceof TypeError) {
      queueReport(payload, idempotencyKey);
      panel.className = "result";
      panel.innerHTML = "<strong>Connection lost.</strong><p>The essential report is saved on this device and will retry.</p>";
    } else {
      panel.className = "result";
      panel.innerHTML = `<strong>Could not create case.</strong><p>${escapeHtml(error.message)}</p>`;
    }
  } finally {
    button.disabled = false;
    button.textContent = "Create emergency case";
  }
});

$("#personSearchForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = new FormData(event.currentTarget).get("query");
  try {
    const people = await apiFetch(`/v1/people/search?query=${encodeURIComponent(query)}`);
    $("#personResults").innerHTML = people.length ? people.map((person) => `
      <article class="data-card"><strong>${escapeHtml(person.full_name)}</strong>
      <p>${escapeHtml(person.status.replaceAll("_", " "))}${person.approximate_age !== null ? ` · approximately ${person.approximate_age}` : ""}</p>
      <p>${escapeHtml(person.last_confirmed_area || "Area not publicly confirmed")}</p></article>`).join("") : "<p>No public-safe matching record was found.</p>";
  } catch (error) { $("#personResults").textContent = error.message; }
});

$("#personReportForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const payload = Object.fromEntries(data.entries());
  payload.approximate_age = payload.approximate_age ? Number(payload.approximate_age) : null;
  Object.keys(payload).forEach((key) => { if (payload[key] === "") payload[key] = null; });
  try {
    const result = await apiFetch("/v1/people/reports", { method: "POST", headers: headers(), body: JSON.stringify(payload) });
    $("#personReportResult").textContent = `Report saved: ${result.person_id}`;
    event.currentTarget.reset();
  } catch (error) { $("#personReportResult").textContent = error.message; }
});

$("#shelterGps").addEventListener("click", () => useGps((error, coords) => {
  if (error) return alert(error.message);
  $("#shelterForm [name=latitude]").value = coords.latitude;
  $("#shelterForm [name=longitude]").value = coords.longitude;
}));

$("#shelterForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const params = new URLSearchParams(new FormData(event.currentTarget));
  try {
    const shelters = await apiFetch(`/v1/shelters/nearby?${params}`);
    $("#shelterResults").innerHTML = shelters.length ? shelters.map((shelter) => `
      <article class="data-card"><strong>${escapeHtml(shelter.name)}</strong><p>${shelter.distance_km} km away · ${shelter.occupancy}/${shelter.capacity} occupied</p>
      <p>${escapeHtml(shelter.address || "Address unavailable")}</p><a target="_blank" rel="noopener" href="https://www.openstreetmap.org/directions?to=${shelter.latitude},${shelter.longitude}">View suggested route</a></article>`).join("") : "<p>No operating shelter was found within this radius.</p>";
  } catch (error) { $("#shelterResults").textContent = error.message; }
});

$("#responderForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const payload = Object.fromEntries(data.entries());
  payload.capabilities = payload.capabilities.split(",").map((value) => value.trim()).filter(Boolean);
  payload.latitude = null; payload.longitude = null;
  Object.keys(payload).forEach((key) => { if (payload[key] === "") payload[key] = null; });
  try {
    const result = await apiFetch("/v1/responders/register", { method: "POST", headers: headers(), body: JSON.stringify(payload) });
    $("#responderResult").textContent = `Registration saved: ${result.responder_id}. Await coordinator approval.`;
    event.currentTarget.reset();
  } catch (error) { $("#responderResult").textContent = error.message; }
});

function initMap() {
  if (!window.L || caseMap) return;
  caseMap = L.map("caseMap").setView([10.7867, 76.6548], 8);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: "&copy; OpenStreetMap contributors",
  }).addTo(caseMap);
}

function renderOperations(cases) {
  const counts = ["P0", "P1", "P2", "P3", "P4"].map((priority) => ({ priority, count: cases.filter((item) => item.priority === priority).length }));
  $("#metrics").innerHTML = counts.map((item) => `<div class="metric"><strong>${item.count}</strong><span>${item.priority} cases</span></div>`).join("");
  $("#operationsCases").innerHTML = cases.length ? cases.map((item) => `
    <article class="case-card"><header><strong>${escapeHtml(item.case_type.replaceAll("_", " "))}</strong><span class="priority ${item.priority}">${item.priority}</span></header>
    <p>${escapeHtml(item.description)}</p><div class="case-meta"><span>${escapeHtml(item.status.replaceAll("_", " "))}</span><span>${item.affected_people_count} people</span><span>${new Date(item.created_at).toLocaleString()}</span></div></article>`).join("") : "<div class=panel>No cases found.</div>";
  initMap();
  if (!caseMap) return;
  caseMarkers.forEach((marker) => marker.remove());
  caseMarkers = cases.filter((item) => item.latitude !== null).map((item) => L.marker([item.latitude, item.longitude]).addTo(caseMap).bindPopup(`<strong>${item.priority} · ${escapeHtml(item.case_type)}</strong><br>${escapeHtml(item.status)}`));
  if (caseMarkers.length) caseMap.fitBounds(L.featureGroup(caseMarkers).getBounds().pad(0.25));
  setTimeout(() => caseMap.invalidateSize(), 50);
}

async function loadOperations() {
  const status = $("#statusFilter").value;
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  try {
    const cases = await apiFetch(`/v1/admin/cases${query}`, { headers: headers("coordinator") });
    renderOperations(cases);
  } catch (error) { $("#operationsCases").textContent = error.message; }
}
$("#refreshOperations").addEventListener("click", loadOperations);
$("#statusFilter").addEventListener("change", loadOperations);

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}

if ("serviceWorker" in navigator) navigator.serviceWorker.register("service-worker.js");
updateNetwork();
