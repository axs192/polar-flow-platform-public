// Training plan page. Ported from the reviewed mock-up (issue #42) -- same
// layout/interaction, wired to the real /plan/data, /plan/edit, /plan/ask
// endpoints instead of fake in-memory data. Uses streamSSE (sse.js) and the
// vendored Chart.js (vendor/chart.umd.min.js), both loaded before this file.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const Y_AXIS_WIDTH = 46; // fixed reserved gutter (px) on every chart's y-axis, regardless of tick digit count -- keeps the bar chart and the elevation chart landing on the same x-per-week, without a dual-axis chart.
const LANE_H = 30; // px per theme lane, reserved at the bottom of the bar chart's own canvas -- room for both the colored line and its label above it
// 8-slot validated categorical palette (dataviz skill's default order) --
// offered as swatch choices for a theme's color. Reuses the same two hues as
// Planned/Actual, which is safe because both domains carry a direct label
// (the Planned/Actual legend + bar position; each theme's on-canvas label).
const THEME_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];

let plan = null; // {start_date, weeks: [{planned_distance_miles,...}], themes: [{label, weeks, color}], updated_at} | null
let actuals = []; // parallel to plan.weeks: [{actual_distance_miles, actual_duration_hr, actual_elevation_gain_ft} | nulls]
let axis = "distance"; // "distance" | "duration"
let chart = null;
let elevChart = null;
let themesEditMode = false;
let weeksEditMode = false;

// --- date helpers ------------------------------------------------------

function weekDate(index) {
  const d = new Date(plan.start_date + "T00:00:00");
  d.setDate(d.getDate() + 7 * index);
  return d;
}
function shortDate(index) {
  const d = weekDate(index);
  return d.getDate() + " " + MONTHS[d.getMonth()];
}
function wcLabel(index) {
  return "W/C " + shortDate(index);
}
function nextMonday() {
  const d = new Date();
  const addDays = (8 - d.getDay()) % 7 || 7;
  d.setDate(d.getDate() + addDays);
  return d;
}
function toISODate(d) {
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
}

// --- data helpers --------------------------------------------------------

const _ESCAPE_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
// theme.label is free text -- from the athlete's own edits, or from the LLM's
// save_training_plan tool call -- rendered back via innerHTML (both as text
// content and inside a value="..." attribute). Must be escaped or it's a
// stored-XSS / attribute-breakout vector, same OWASP class as any other
// user-controlled string reflected into HTML.
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => _ESCAPE_MAP[c]);
}

function fmt(n, unit) {
  if (n === null || n === undefined) return "&ndash;";
  return Math.round(n * 10) / 10 + " " + unit;
}
function unitFor(a) {
  return a === "distance" ? "mi" : "hr";
}
function plannedField(a) {
  return a === "distance" ? "planned_distance_miles" : "planned_duration_hr";
}
function actualField(a) {
  return a === "distance" ? "actual_distance_miles" : "actual_duration_hr";
}
function actualAt(i, field) {
  return actuals[i] ? actuals[i][field] : null;
}
function sumField(getter, onlyLogged) {
  let total = 0;
  for (let i = 0; i < plan.weeks.length; i++) {
    if (onlyLogged && actualAt(i, "actual_distance_miles") === null) continue;
    total += getter(i) || 0;
  }
  return total;
}

// Collapse a theme's (possibly non-contiguous) week list into [start,end]
// runs -- e.g. [0,1,2,3] -> [[0,3]]; [0,1,3] -> [[0,1],[3,3]] (the "week 1,
// gap week 2, week 3" case).
function contiguousRuns(weeksArr) {
  const sorted = weeksArr.slice().sort((a, b) => a - b);
  const runs = [];
  sorted.forEach((w) => {
    const last = runs[runs.length - 1];
    if (last && w === last[1] + 1) last[1] = w;
    else runs.push([w, w]);
  });
  return runs;
}
function weekRangeLabel(weeksArr) {
  if (!weeksArr.length) return "No weeks yet";
  return contiguousRuns(weeksArr)
    .map((r) => (r[0] === r[1] ? "Week " + (r[0] + 1) : "Weeks " + (r[0] + 1) + "–" + (r[1] + 1)))
    .join(", ");
}
function themeLanesHeight() {
  return Math.max(1, plan.themes.length) * LANE_H + 10;
}

// Keep every theme's week-index list valid after weeks are added/removed:
// drop a removed index, shift every index above it down by one.
function reindexThemesAfterRemoval(removedIdx) {
  plan.themes.forEach((t) => {
    t.weeks = t.weeks.filter((w) => w !== removedIdx).map((w) => (w > removedIdx ? w - 1 : w));
  });
}

// --- persistence -----------------------------------------------------------

async function fetchPlan() {
  const resp = await fetch("/plan/data");
  if (resp.status === 401) {
    window.location.assign("/login");
    return;
  }
  if (!resp.ok) throw new Error("Failed to load plan: " + resp.status);
  const data = await resp.json();
  plan = data.plan;
  actuals = data.actuals || [];
}

async function savePlan() {
  const resp = await fetch("/plan/edit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ start_date: plan.start_date, weeks: plan.weeks, themes: plan.themes }),
  });
  if (resp.status === 401) {
    window.location.assign("/login");
    return;
  }
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error("Couldn't save the plan: " + detail);
  }
  plan = await resp.json();
}

async function withSaveErrorHandling(fn) {
  try {
    await fn();
  } catch (err) {
    // No toast system on this page -- a blocking alert is honest about a
    // save failing, not a silent no-op.
    alert(err.message);
    // Every call site already mutates local `plan`/`actuals` optimistically
    // before calling this, then re-renders unconditionally afterward. If the
    // save itself failed (e.g. removing the last week, which the backend
    // correctly rejects -- a plan needs at least one), that local mutation
    // was never actually persisted -- re-sync with the server's real state so
    // the re-render reflects what's actually stored, not a phantom edit.
    await fetchPlan();
  }
}

// --- rendering ---------------------------------------------------------

function renderSummary() {
  const loggedCount = actuals.filter((a) => a && a.actual_distance_miles !== null).length;
  const plannedDist = sumField((i) => plan.weeks[i].planned_distance_miles, true);
  const actualDist = sumField((i) => actualAt(i, "actual_distance_miles"), true);
  const plannedDur = sumField((i) => plan.weeks[i].planned_duration_hr, true);
  const actualDur = sumField((i) => actualAt(i, "actual_duration_hr"), true);
  const plannedElev = sumField((i) => plan.weeks[i].planned_elevation_gain_ft, true);
  const actualElev = sumField((i) => actualAt(i, "actual_elevation_gain_ft"), true);

  // No "% complete" or on-pace/behind-pace framing here -- a training plan
  // flexes routinely, and a colored pass/fail readout on every visit reads
  // as judgmental in exactly the weeks an athlete least needs that. The
  // actual/planned pairs below say the same thing neutrally.
  const pair = (actualV, plannedV, unit, decimals) => {
    const r = (n) => (decimals ? Math.round(n * 10) / 10 : Math.round(n));
    return r(actualV) + '<span class="sep">/</span>' + r(plannedV) + " " + unit;
  };

  const stats = [
    { label: "Plan length", value: plan.weeks.length + " weeks" },
    { label: "Distance &middot; actual / planned (" + loggedCount + " wk)", value: pair(actualDist, plannedDist, "mi") },
    { label: "Duration &middot; actual / planned", value: pair(actualDur, plannedDur, "hr", true) },
    { label: "Elevation &middot; actual / planned", value: pair(actualElev, plannedElev, "ft") },
  ];
  document.getElementById("summary-row").innerHTML = stats
    .map((s) => '<div class="stat"><div class="label">' + s.label + '</div><div class="value">' + s.value + "</div></div>")
    .join("");
}

function fixedYAxisWidth(scale) {
  scale.width = Y_AXIS_WIDTH;
}

function truncateToWidth(ctx, text, maxWidth) {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let t = text;
  while (t.length > 1 && ctx.measureText(t + "…").width > maxWidth) t = t.slice(0, -1);
  return t + "…";
}

// Draws each theme's week-range(s) as a colored, labeled line segment
// directly on the bar chart's own canvas, in the space reserved by
// layout.padding.bottom. Reading pixel positions from THIS chart's own
// xScale and painting on THIS chart's own canvas makes misalignment
// structurally impossible -- there's no second coordinate system (a
// separately-measured DOM grid) left to ever disagree with the first.
const themeLanesPlugin = {
  id: "themeLanes",
  afterDraw(c) {
    const ctx = c.ctx;
    const xScale = c.scales.x;
    const half = (plan.weeks.length > 1 ? xScale.getPixelForValue(1) - xScale.getPixelForValue(0) : xScale.width) / 2 - 3;
    const laneTop = xScale.bottom + 6;
    ctx.save();
    ctx.lineCap = "round";
    ctx.font = "600 10px ui-sans-serif, system-ui, -apple-system, sans-serif";
    ctx.textBaseline = "alphabetic";
    plan.themes.forEach((t, laneIdx) => {
      const laneY = laneTop + laneIdx * LANE_H;
      const lineY = laneY + LANE_H - 6;
      const runs = contiguousRuns(t.weeks);
      if (!runs.length) return;

      ctx.strokeStyle = t.color;
      ctx.lineWidth = 6;
      let widest = null;
      runs.forEach((run) => {
        const x0 = xScale.getPixelForValue(run[0]) - half;
        const x1 = xScale.getPixelForValue(run[1]) + half;
        ctx.beginPath();
        ctx.moveTo(x0, lineY);
        ctx.lineTo(x1, lineY);
        ctx.stroke();
        if (!widest || x1 - x0 > widest.w) widest = { x0, w: x1 - x0 };
      });

      ctx.fillStyle = t.color;
      ctx.fillText(truncateToWidth(ctx, t.label, Math.max(widest.w - 4, 28)), widest.x0 + 2, laneY + 10);
    });
    ctx.restore();
  },
};

function renderChart() {
  const labels = plan.weeks.map((_, i) => shortDate(i));
  const pField = plannedField(axis);
  const aField = actualField(axis);
  const planned = plan.weeks.map((w) => w[pField]);
  const actual = plan.weeks.map((_, i) => actualAt(i, aField));
  const textColor = "#8b97a7";
  const gridColor = "rgba(139, 151, 167, 0.15)";
  const lanesH = themeLanesHeight();

  // The extra bottom space for theme lanes has to come from a taller
  // container, not just chart padding, or it eats into the bars' own
  // plotting area instead of adding room below it.
  document.querySelector(".chart-wrap").style.height = 200 + lanesH + "px";

  if (chart) chart.destroy();
  const ctx = document.getElementById("plan-chart").getContext("2d");
  chart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Planned", data: planned, backgroundColor: "#3987e5", borderRadius: 4, maxBarThickness: 22 },
        { label: "Actual", data: actual, backgroundColor: "#d95926", borderRadius: 4, maxBarThickness: 22 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      layout: { padding: { right: 4, bottom: lanesH } },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#222b37",
          borderColor: "#2c3643",
          borderWidth: 1,
          titleColor: "#e6edf3",
          bodyColor: "#e6edf3",
          padding: 10,
          callbacks: {
            label(item) {
              const v = item.raw;
              if (v === null || v === undefined) return item.dataset.label + ": not run yet";
              return item.dataset.label + ": " + Math.round(v * 10) / 10 + " " + unitFor(axis);
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: textColor, font: { size: 10 } } },
        y: { beginAtZero: true, grid: { color: gridColor }, ticks: { color: textColor }, afterFit: fixedYAxisWidth },
      },
    },
    plugins: [themeLanesPlugin],
  });
}

// Elevation as its own small-multiple chart sharing the bar chart's x-axis,
// not a second y-scale on the same chart -- a dual-axis chart makes the two
// measures' relative magnitudes impossible to read honestly.
function renderElevationChart() {
  const labels = plan.weeks.map((_, i) => shortDate(i));
  const planned = plan.weeks.map((w) => w.planned_elevation_gain_ft);
  const actual = plan.weeks.map((_, i) => actualAt(i, "actual_elevation_gain_ft"));
  const textColor = "#8b97a7";
  const gridColor = "rgba(139, 151, 167, 0.15)";

  if (elevChart) elevChart.destroy();
  const ctx = document.getElementById("elevation-chart").getContext("2d");
  elevChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Planned", data: planned, borderColor: "#3987e5", backgroundColor: "#3987e5", pointRadius: 3, pointHoverRadius: 5, borderWidth: 2, tension: 0.25, spanGaps: false },
        { label: "Actual", data: actual, borderColor: "#d95926", backgroundColor: "#d95926", pointRadius: 3, pointHoverRadius: 5, borderWidth: 2, tension: 0.25, spanGaps: false },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      layout: { padding: { right: 4 } },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#222b37",
          borderColor: "#2c3643",
          borderWidth: 1,
          titleColor: "#e6edf3",
          bodyColor: "#e6edf3",
          padding: 10,
          callbacks: {
            label(item) {
              const v = item.raw;
              if (v === null || v === undefined) return item.dataset.label + ": not run yet";
              return item.dataset.label + ": " + Math.round(v) + " ft";
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { display: false } },
        y: { beginAtZero: true, grid: { color: gridColor }, ticks: { color: textColor, maxTicksLimit: 3 }, afterFit: fixedYAxisWidth },
      },
    },
  });
}

// Read-only: a plain legend list (swatch + name + week range text) -- the
// per-week visual is drawn on the chart itself. Edit mode swaps each row for
// a label input + color/delete controls + a wrapped row of week-toggle
// chips; the chips are a plain list, not grid-aligned to anything, since
// editing doesn't need to visually line up with the chart the way the
// read-only display does.
function renderThemesLegend() {
  const el = document.getElementById("themes-legend");
  el.innerHTML =
    plan.themes
      .map((t, tIdx) => {
        if (!themesEditMode) {
          return (
            '<div class="theme-row"><span class="dot" style="background:' + t.color + '"></span>' +
            '<span class="txt">' + escapeHtml(t.label) + '</span><span class="week-range">' + weekRangeLabel(t.weeks) + "</span></div>"
          );
        }
        const chips = plan.weeks
          .map((_, i) => {
            const on = t.weeks.indexOf(i) !== -1;
            const style = on ? "background:" + t.color + ";border-color:transparent;color:#fff" : "";
            return '<button type="button" class="week-chip" style="' + style + '" data-action="toggle-week" data-theme="' + tIdx + '" data-week="' + i + '">' + shortDate(i) + "</button>";
          })
          .join("");
        return (
          '<div class="theme-row editing">' +
          '<div class="theme-row-head">' +
          '<input class="cell-input" data-action="theme-label" data-idx="' + tIdx + '" value="' + escapeHtml(t.label) + '">' +
          '<button class="swatch-btn" data-action="cycle-color" data-idx="' + tIdx + '" style="background:' + t.color + '"></button>' +
          '<button class="icon-btn" data-action="delete-theme" data-idx="' + tIdx + '">&times;</button>' +
          "</div>" +
          '<div class="week-chips">' + chips + "</div>" +
          "</div>"
        );
      })
      .join("") || '<p class="card-sub">No themes yet.</p>';
  document.getElementById("add-theme").hidden = !themesEditMode;
}

function renderWeeksTable() {
  const thead = document.getElementById("weeks-thead");
  const body = document.getElementById("weeks-body");
  const cols = weeksEditMode
    ? ["Week", "Planned distance (mi)", "Planned duration (hr)", "Planned elevation (ft)", "Actual", ""]
    : ["Week", "Planned distance", "Planned duration", "Planned elevation", "Actual dist. / dur. / elev."];
  thead.innerHTML = "<tr>" + cols.map((c) => "<th>" + c + "</th>").join("") + "</tr>";

  body.innerHTML = plan.weeks
    .map((w, idx) => {
      const naDist = actualAt(idx, "actual_distance_miles") === null;
      const weekCell = '<td class="wc-label">' + wcLabel(idx) + '<div class="muted-sub">Week ' + (idx + 1) + "</div></td>";
      let plannedDist, plannedDur, plannedElev;
      if (weeksEditMode) {
        plannedDist = '<td><input class="cell-input plan-num" type="number" step="0.5" min="0" data-action="planned-distance" data-idx="' + idx + '" value="' + w.planned_distance_miles + '"></td>';
        plannedDur = '<td><input class="cell-input plan-num" type="number" step="0.1" min="0" data-action="planned-duration" data-idx="' + idx + '" value="' + w.planned_duration_hr + '"></td>';
        plannedElev = '<td><input class="cell-input plan-num" type="number" step="50" min="0" data-action="planned-elevation" data-idx="' + idx + '" value="' + w.planned_elevation_gain_ft + '"></td>';
      } else {
        plannedDist = "<td>" + fmt(w.planned_distance_miles, "mi") + "</td>";
        plannedDur = "<td>" + fmt(w.planned_duration_hr, "hr") + "</td>";
        plannedElev = "<td>" + fmt(w.planned_elevation_gain_ft, "ft") + "</td>";
      }
      const actualSummary = naDist
        ? '<td class="actual-cell na">&ndash;</td>'
        : '<td class="actual-cell">' + fmt(actualAt(idx, "actual_distance_miles"), "mi") + " / " + fmt(actualAt(idx, "actual_duration_hr"), "hr") + " / " + fmt(actualAt(idx, "actual_elevation_gain_ft"), "ft") + "</td>";
      // A plan needs at least one week (the backend rejects an empty list),
      // so the remove control doesn't appear on the last remaining one --
      // otherwise clicking it round-trips to a save failure.
      const removeCell = weeksEditMode
        ? "<td>" + (plan.weeks.length > 1 ? '<button class="icon-btn" data-action="remove-week" data-idx="' + idx + '">&times;</button>' : "") + "</td>"
        : "";
      return "<tr>" + weekCell + plannedDist + plannedDur + plannedElev + actualSummary + removeCell + "</tr>";
    })
    .join("");

  document.getElementById("add-week").hidden = !weeksEditMode;
}

function renderPlanView() {
  renderSummary();
  renderChart();
  renderElevationChart();
  renderThemesLegend();
  renderWeeksTable();
}

function renderAll() {
  const hasPlan = plan !== null;
  document.getElementById("empty-state-card").hidden = hasPlan;
  document.getElementById("plan-view").hidden = !hasPlan;
  if (hasPlan) renderPlanView();
}

// --- interaction wiring ------------------------------------------------

document.getElementById("start-date-input").value = toISODate(nextMonday());

document.getElementById("start-plan-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const chosen = document.getElementById("start-date-input").value;
  if (!chosen) return;
  plan = {
    start_date: chosen,
    weeks: [{ planned_distance_miles: 30, planned_duration_hr: 4.0, planned_elevation_gain_ft: 1800 }],
    themes: [],
  };
  actuals = [{ actual_distance_miles: null, actual_duration_hr: null, actual_elevation_gain_ft: null }];
  await withSaveErrorHandling(savePlan);
  renderAll();
});

document.getElementById("axis-toggle").addEventListener("click", function (e) {
  const btn = e.target.closest("button[data-axis]");
  if (!btn) return;
  axis = btn.getAttribute("data-axis");
  this.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
  renderChart();
});

document.getElementById("themes-edit-toggle").addEventListener("click", async function () {
  if (themesEditMode) await withSaveErrorHandling(savePlan); // leaving edit mode: persist
  themesEditMode = !themesEditMode;
  this.classList.toggle("active", themesEditMode);
  this.textContent = themesEditMode ? "Done" : "Edit";
  renderThemesLegend();
});

document.getElementById("weeks-edit-toggle").addEventListener("click", async function () {
  if (weeksEditMode) await withSaveErrorHandling(savePlan); // leaving edit mode: persist
  weeksEditMode = !weeksEditMode;
  this.classList.toggle("active", weeksEditMode);
  this.textContent = weeksEditMode ? "Done" : "Edit";
  renderWeeksTable();
});

document.getElementById("weeks-body").addEventListener("input", (e) => {
  const el = e.target;
  const action = el.getAttribute("data-action");
  const idx = parseInt(el.getAttribute("data-idx"), 10);
  if (action === "planned-distance") plan.weeks[idx].planned_distance_miles = parseFloat(el.value) || 0;
  if (action === "planned-duration") plan.weeks[idx].planned_duration_hr = parseFloat(el.value) || 0;
  if (action === "planned-elevation") plan.weeks[idx].planned_elevation_gain_ft = parseFloat(el.value) || 0;
  renderSummary();
  renderChart();
  renderElevationChart();
});

document.getElementById("weeks-body").addEventListener("click", async (e) => {
  const el = e.target.closest('button[data-action="remove-week"]');
  if (!el) return;
  const idx = parseInt(el.getAttribute("data-idx"), 10);
  plan.weeks.splice(idx, 1);
  actuals.splice(idx, 1);
  reindexThemesAfterRemoval(idx);
  await withSaveErrorHandling(savePlan);
  renderAll();
});

document.getElementById("add-week").addEventListener("click", async () => {
  plan.weeks.push({ planned_distance_miles: 30, planned_duration_hr: 4.0, planned_elevation_gain_ft: 1800 });
  actuals.push({ actual_distance_miles: null, actual_duration_hr: null, actual_elevation_gain_ft: null });
  await withSaveErrorHandling(savePlan);
  renderAll();
});

document.getElementById("themes-legend").addEventListener("input", (e) => {
  const el = e.target;
  if (el.getAttribute("data-action") !== "theme-label") return;
  const idx = parseInt(el.getAttribute("data-idx"), 10);
  plan.themes[idx].label = el.value;
});

document.getElementById("themes-legend").addEventListener("click", async (e) => {
  const chip = e.target.closest('[data-action="toggle-week"]');
  if (chip) {
    const tIdx = parseInt(chip.getAttribute("data-theme"), 10);
    const wIdx = parseInt(chip.getAttribute("data-week"), 10);
    const t = plan.themes[tIdx];
    const pos = t.weeks.indexOf(wIdx);
    if (pos === -1) t.weeks.push(wIdx);
    else t.weeks.splice(pos, 1);
    renderChart();
    renderThemesLegend();
    return;
  }
  const colorBtn = e.target.closest('[data-action="cycle-color"]');
  if (colorBtn) {
    const cIdx = parseInt(colorBtn.getAttribute("data-idx"), 10);
    const current = THEME_COLORS.indexOf(plan.themes[cIdx].color);
    plan.themes[cIdx].color = THEME_COLORS[(current + 1) % THEME_COLORS.length];
    renderChart();
    renderThemesLegend();
    return;
  }
  const delBtn = e.target.closest('[data-action="delete-theme"]');
  if (delBtn) {
    const dIdx = parseInt(delBtn.getAttribute("data-idx"), 10);
    plan.themes.splice(dIdx, 1);
    await withSaveErrorHandling(savePlan);
    renderChart();
    renderThemesLegend();
  }
});

document.getElementById("add-theme").addEventListener("click", async () => {
  plan.themes.push({ label: "New theme", weeks: [], color: THEME_COLORS[plan.themes.length % THEME_COLORS.length] });
  await withSaveErrorHandling(savePlan);
  renderChart();
  renderThemesLegend();
});

// --- chat ----------------------------------------------------------------

const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const conversationEl = document.getElementById("conversation");

function appendChatTurn(question) {
  const turn = document.createElement("div");
  turn.className = "turn";
  const q = document.createElement("div");
  q.className = "question";
  q.textContent = question;
  const answerEl = document.createElement("div");
  answerEl.className = "answer";
  const textNode = document.createElement("span");
  answerEl.appendChild(textNode);
  turn.appendChild(q);
  turn.appendChild(answerEl);
  conversationEl.appendChild(turn);
  turn.scrollIntoView({ behavior: "smooth", block: "start" });
  return { answerEl, textNode };
}

function handleChatEvent(event, answerEl, textNode) {
  switch (event.type) {
    case "tool": {
      const pill = document.createElement("div");
      pill.className = "tool";
      pill.textContent = "🔧 " + event.name + "(" + JSON.stringify(event.input) + ")";
      answerEl.appendChild(pill);
      if (!textNode.isConnected) answerEl.appendChild(textNode);
      break;
    }
    case "text":
      if (!textNode.isConnected) answerEl.appendChild(textNode);
      textNode.textContent += event.text;
      break;
    case "error": {
      const e = document.createElement("div");
      e.className = "error";
      e.textContent = "Error: " + event.message;
      answerEl.appendChild(e);
      break;
    }
    case "done":
      break;
  }
}

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = chatInput.value.trim();
  if (!question) return;
  chatInput.value = "";
  const { answerEl, textNode } = appendChatTurn(question);

  try {
    const resp = await fetch("/plan/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    if (resp.status === 401) {
      window.location.assign("/login");
      return;
    }
    if (resp.status === 429) throw new Error("Rate limit reached — please slow down and try again shortly.");
    if (!resp.ok) throw new Error("Request failed: " + resp.status);

    let sawDone = false;
    await streamSSE(resp, (event) => {
      handleChatEvent(event, answerEl, textNode);
      if (event.type === "done") sawDone = true;
    });
    // The plan-building agent may have called save_training_plan this turn --
    // re-fetch and re-render so the chart/themes/table above reflect it.
    if (sawDone) {
      await fetchPlan();
      renderAll();
    }
  } catch (err) {
    const e = document.createElement("div");
    e.className = "error";
    e.textContent = "Error: " + err.message;
    answerEl.appendChild(e);
  }
});

// --- init ------------------------------------------------------------------

fetchPlan().then(renderAll);
