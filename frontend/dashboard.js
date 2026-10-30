"use strict";

let state = null;
let selectedFlight = null;
let loading = false;

const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(
  /[&<>"']/g,
  (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;",
    '"': "&quot;", "'": "&#39;",
  })[character],
);
const money = (value) => value == null
  ? "—"
  : `NT$${Number(value).toLocaleString("zh-TW")}`;

const dateFormat = new Intl.DateTimeFormat("zh-TW", {
  timeZone: "Asia/Taipei", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hour12: false,
});
const timeFormat = new Intl.DateTimeFormat("zh-TW", {
  timeZone: "Asia/Taipei", hour: "2-digit", minute: "2-digit", hour12: false,
});
const dayFormat = new Intl.DateTimeFormat("zh-TW", {
  timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit",
});
const formatDate = (value) => value ? dateFormat.format(new Date(value)) : "—";

function setNotes(messages) {
  $("alerts").innerHTML = messages
    .map((message) => `<p>${escapeHtml(message)}</p>`)
    .join("");
}

function setConnection(text, warning = false) {
  $("liveText").textContent = text;
  $("live").classList.toggle("bad", warning);
}

function drawChart(element, points) {
  const available = points.filter((point) => point.price != null);
  if (!available.length) {
    element.innerHTML = '<div class="empty-state">尚無報價</div>';
    return;
  }

  const width = 660;
  const height = 226;
  const left = 60;
  const right = 17;
  const top = 18;
  const bottom = 37;
  const timestamps = points.map((point) => Date.parse(point.time));
  const start = Math.min(...timestamps);
  const end = Math.max(...timestamps);
  const prices = available.map((point) => point.price);
  const minimum = Math.min(...prices);
  const maximum = Math.max(...prices);
  const padding = Math.max((maximum - minimum) * 0.2, maximum * 0.015, 30);
  const low = Math.max(0, minimum - padding);
  const high = maximum + padding;

  const x = (point) => left + (end === start ? 0.5 :
    (Date.parse(point.time) - start) / (end - start)) * (width - left - right);
  const y = (price) => top + (high - price) / (high - low) * (height - top - bottom);

  const svg = [
    `<svg viewBox="0 0 ${width} ${height}" role="img"`,
    ` aria-label="價格走勢，最低 ${money(minimum)}，最高 ${money(maximum)}">`,
  ];

  for (let index = 0; index < 4; index += 1) {
    const price = low + (high - low) * index / 3;
    const position = y(price);
    svg.push(
      `<line class="chart-grid" x1="${left}" x2="${width - right}" y1="${position}" y2="${position}"/>`,
      `<text class="chart-label" x="${left - 9}" y="${position + 4}" text-anchor="end">${Math.round(price).toLocaleString("zh-TW")}</text>`,
    );
  }

  let segment = [];
  const finishSegment = () => {
    if (segment.length) {
      svg.push(`<polyline class="chart-line" points="${segment.join(" ")}"/>`);
      segment = [];
    }
  };

  for (const point of points) {
    if (point.price == null) {
      finishSegment();
    } else {
      segment.push(`${x(point)},${y(point.price)}`);
    }
  }
  finishSegment();

  for (const point of available) {
    svg.push(
      `<circle class="chart-point" cx="${x(point)}" cy="${y(point.price)}" r="${available.length > 35 ? 2 : 3.5}">`,
      `<title>${escapeHtml(formatDate(point.time))} · ${escapeHtml(money(point.price))}</title></circle>`,
    );
  }

  const labelIndices = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])];
  labelIndices.forEach((pointIndex, index) => {
    const point = points[pointIndex];
    const anchor = labelIndices.length === 1 ? "middle" :
      index === 0 ? "start" : index === labelIndices.length - 1 ? "end" : "middle";
    svg.push(`<text class="chart-label" x="${x(point)}" y="${height - 9}" text-anchor="${anchor}">${escapeHtml(formatDate(point.time))}</text>`);
  });
  svg.push("</svg>");
  element.innerHTML = svg.join("");
}

function drawTable() {
  const query = $("search").value.trim().toLowerCase();
  const flights = state.flights.filter((flight) => (flight.airline || "").toLowerCase().includes(query));
  const prices = state.flights.filter((flight) => flight.price != null).map((flight) => flight.price);
  const minimum = prices.length ? Math.min(...prices) : null;

  $("tableCount").textContent = `${flights.length} 班`;
  $("tableEmpty").hidden = flights.length > 0;
  $("flightTable").innerHTML = flights.map((flight) => {
    const index = state.flights.indexOf(flight);
    const change = flight.change;
    const changeText = change == null ? "—" : change === 0 ? "持平" :
      `${change < 0 ? "↓" : "↑"} ${money(Math.abs(change))}`;
    const changeClass = change == null || change === 0 ? "muted" :
      change < 0 ? "positive" : "negative";
    const arrivalDay = flight.arrival_day_offset
      ? `<small>+${flight.arrival_day_offset}</small>` : "";
    const duration = `${Math.floor(flight.duration_minutes / 60)}h ${flight.duration_minutes % 60}m`;
    const stops = flight.stops === 0 ? "直飛" : `${flight.stops} 次轉機`;
    const badge = minimum != null && flight.price === minimum
      ? '<span class="badge">最低</span>' : "";

    return `
      <tr class="${flight.key === selectedFlight ? "selected" : ""}">
        <td><button class="airline-button" data-flight="${index}" type="button">${escapeHtml(flight.airline)}</button></td>
        <td class="flight-time">${escapeHtml(flight.departure_time)} <small>→</small> ${escapeHtml(flight.arrival_time)} ${arrivalDay}</td>
        <td>${duration} <span class="muted">· ${stops}</span></td>
        <td><span class="${flight.price == null ? "muted" : "price"}">${flight.price == null ? "無報價" : money(flight.price)}</span>${badge}</td>
        <td class="${changeClass}">${changeText}</td>
        <td>${money(flight.history_min)}</td>
        <td><button class="detail-button" data-raw="${index}" type="button">原文</button></td>
      </tr>`;
  }).join("");
}

function drawFlight() {
  const series = state.series.find((item) => item.key === selectedFlight);
  const points = series?.points || [];
  const prices = points.filter((point) => point.price != null).map((point) => point.price);
  drawChart($("flightChart"), points);
  $("flightRange").innerHTML = prices.length
    ? `<span>最低 <b>${money(Math.min(...prices))}</b></span><span>最高 <b>${money(Math.max(...prices))}</b></span>`
    : "";
  drawTable();
}

function drawChecks() {
  const labels = { ok: "完成", partial: "部分資料", error: "失敗" };
  $("qualityTitle").textContent = `收集紀錄 · ${state.totals?.checks ?? state.checks.length} 次`;
  $("checksTable").innerHTML = state.checks.map((check) => `
    <tr>
      <td>#${check.id}</td>
      <td>${escapeHtml(formatDate(check.checked_at))}</td>
      <td class="${check.status === "error" ? "negative" : "muted"}">${escapeHtml(labels[check.status] || check.status)}</td>
      <td>${escapeHtml(check.error || "—")}</td>
    </tr>`).join("");
}

function clearData() {
  for (const id of ["currentPrice", "historyPrice", "quoteCount", "lastTime",
    "currentFlight", "historyTime", "quoteNote", "lastDate"]) {
    $(id).textContent = "—";
  }
  for (const id of ["comparisonTime", "historyCount", "flightRange"]) {
    $(id).textContent = "";
  }
  state.flights = [];
  state.series = [];
  selectedFlight = null;
  $("flightSelect").innerHTML = "";
  drawChart($("routeChart"), []);
  drawChart($("flightChart"), []);
  drawTable();
}

function render() {
  $("renderTime").textContent = `畫面更新 ${formatDate(new Date().toISOString())}`;
  if (!state.routes.length) {
    $("route").innerHTML = '<option value="">尚無航線</option>';
    $("routeTitle").textContent = "機票追蹤";
    $("routeDescription").textContent = "";
    state.checks = state.checks || [];
    clearData();
    drawChecks();
    setConnection("尚無資料");
    setNotes(["尚無收集紀錄"]);
    return;
  }

  $("route").innerHTML = state.routes.map((route, index) => `
    <option value="${index}">${escapeHtml(route.origin)} → ${escapeHtml(route.destination)} · ${escapeHtml(route.departure_date)}${route.return_date ? " ↔ " + escapeHtml(route.return_date) : ""}</option>
  `).join("");
  $("route").value = state.route_index;
  const route = state.routes[state.route_index];
  $("routeTitle").textContent = `${route.origin} → ${route.destination}`;
  $("routeDescription").textContent = route.departure_date.replaceAll("-", " / ") +
    (route.return_date ? ` — ${route.return_date.replaceAll("-", " / ")} · 來回` : " · 單程");

  const attempt = state.latest_attempt;
  const data = state.latest_data;
  let config = {};
  try { config = JSON.parse(attempt.config_json); } catch { /* 以預設間隔判斷更新狀態。 */ }
  const overdue = Date.now() - Date.parse(attempt.checked_at) >
    Math.max(2 * (config.interval_seconds || 3600) + 120, 600) * 1000;
  setConnection(overdue ? "尚未更新" : attempt.status === "error" ? "查詢失敗" : "本機資料",
    overdue || attempt.status === "error");

  const notes = [];
  if (overdue) notes.push("資料尚未更新");
  if (!data) {
    clearData();
    drawChecks();
    setNotes([...notes, "尚無航班資料"]);
    return;
  }
  if (attempt.id !== data.id) notes.push(`顯示最近可用資料：${formatDate(data.checked_at)}`);
  if (state.excluded) notes.push(`${state.excluded} 筆資料未納入統計`);
  setNotes(notes);

  const priced = state.flights.filter((flight) => flight.price != null && flight.price > 0);
  const cheapest = priced.reduce((best, flight) => !best || flight.price < best.price ? flight : best, null);
  const best = state.history.filter((point) => point.price != null).reduce(
    (result, point) => !result || point.price < result.price ? point : result, null,
  );

  $("currentPrice").innerHTML = cheapest ? `<small>TWD</small>${Number(cheapest.price).toLocaleString("zh-TW")}` : "—";
  $("currentFlight").textContent = cheapest ? `${cheapest.airline} · ${cheapest.departure_time}` : "尚無報價";
  $("historyPrice").innerHTML = best ? `<small>TWD</small>${Number(best.price).toLocaleString("zh-TW")}` : "—";
  $("historyTime").textContent = best ? formatDate(best.time) : "—";
  $("quoteCount").innerHTML = `${priced.length}<small> / ${state.flights.length} 班</small>`;
  $("quoteNote").textContent = `${state.flights.length - priced.length} 班無報價`;
  $("lastTime").textContent = timeFormat.format(new Date(data.checked_at));
  $("lastDate").textContent = dayFormat.format(new Date(data.checked_at));
  $("historyCount").textContent = `${state.totals.checks} 次觀測`;
  $("comparisonTime").textContent = state.previous_time ? `比較 ${formatDate(state.previous_time)} 的同一班次` : "";
  drawChart($("routeChart"), state.history);

  if (!state.series.some((series) => series.key === selectedFlight)) {
    selectedFlight = cheapest?.key || state.series[0]?.key || null;
  }
  $("flightSelect").innerHTML = state.series.map((series, index) =>
    `<option value="${index}">${escapeHtml(series.label)}</option>`,
  ).join("");
  $("flightSelect").value = state.series.findIndex((series) => series.key === selectedFlight);
  drawFlight();
  drawChecks();
}

async function refresh() {
  if (loading) return;
  loading = true;
  $("refresh").disabled = true;
  try {
    const params = new URLSearchParams({
      hours: $("hours").value,
      nonstop: $("nonstop").checked ? "1" : "0",
      duration: $("duration").value,
    });
    if (state && $("route").value !== "") params.set("route", $("route").value);
    const response = await fetch(`/api/data?${params}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "讀取失敗");
    state = data;
    render();
  } catch (error) {
    setConnection("更新失敗", true);
    setNotes([`更新失敗：${error.message}`, "畫面保留前次資料"]);
  } finally {
    loading = false;
    $("refresh").disabled = false;
  }
}

$("refresh").addEventListener("click", refresh);
for (const id of ["route", "hours", "duration", "nonstop"]) {
  $(id).addEventListener("change", () => {
    selectedFlight = null;
    refresh();
  });
}
$("search").addEventListener("input", () => { if (state) drawTable(); });
$("flightSelect").addEventListener("change", () => {
  if (!state) return;
  selectedFlight = state.series[Number($("flightSelect").value)]?.key;
  drawFlight();
});
$("flightTable").addEventListener("click", (event) => {
  const button = event.target.closest("[data-flight], [data-raw]");
  if (!button || !state) return;
  if (button.dataset.flight !== undefined) {
    selectedFlight = state.flights[Number(button.dataset.flight)].key;
    $("flightSelect").value = state.series.findIndex((series) => series.key === selectedFlight);
    drawFlight();
  } else {
    $("rawText").textContent = state.flights[Number(button.dataset.raw)].raw_text;
    $("rawDialog").showModal();
  }
});
$("closeDialog").addEventListener("click", () => $("rawDialog").close());
refresh();
setInterval(refresh, 60000);
