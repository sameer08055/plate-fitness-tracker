/*
  The whole app UI. Plain JavaScript, no framework or build step:
  each view has a render function, and every change re-fetches from the API.
*/
import { api } from "./api.js";
import { handleLoginRedirect, isSignedIn, login, logout } from "./auth.js";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => document.querySelectorAll(selector);

const state = {
  date: localDate(new Date()), // the day being viewed and logged
  goals: null,
  trendDays: 7,
  pendingFood: null, // a looked-up food waiting for a portion size
  pendingMeal: null, // an AI estimate waiting to be saved
  scanner: null,
};

// ---------- Small helpers ----------

/** "2026-10-11" in the user's own time zone (en-CA formats dates that way). */
function localDate(date) {
  return date.toLocaleDateString("en-CA");
}

function addDays(isoDate, days) {
  const d = new Date(`${isoDate}T12:00:00`); // noon avoids daylight-saving edge cases
  d.setDate(d.getDate() + days);
  return localDate(d);
}

function friendlyDate(isoDate) {
  const today = localDate(new Date());
  if (isoDate === today) return "Today";
  if (isoDate === addDays(today, -1)) return "Yesterday";
  return new Date(`${isoDate}T12:00:00`).toLocaleDateString(undefined, {
    weekday: "short", month: "short", day: "numeric",
  });
}

/** Escape text before putting it in HTML, so a meal named "<script>" can't run code. */
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function fmt(number, digits = 0) {
  return Number(number ?? 0).toLocaleString(undefined, { maximumFractionDigits: digits });
}

function percent(value, goal) {
  return goal ? Math.min(100, Math.max(0, (value / goal) * 100)) : 0;
}

function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("error", isError);
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el.hidden = true), isError ? 5000 : 2500);
}

function formData(form) {
  const data = Object.fromEntries(new FormData(form));
  for (const input of form.querySelectorAll("input[type=number]")) {
    data[input.name] = Number(input.value);
  }
  return data;
}

/** Run an async action with its button disabled, showing any error as a toast. */
async function withButton(button, action) {
  if (button) button.disabled = true;
  try {
    await action();
  } catch (error) {
    if (error.status !== 401) toast(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}

// ---------- Navigation ----------

/** Run a render function and show any error as a toast instead of failing silently. */
function safely(render) {
  render().catch((error) => {
    if (error.status !== 401) toast(error.message, true);
  });
}

function showView(name) {
  for (const view of $$(".view")) view.hidden = view.id !== `view-${name}`;
  for (const tab of $$(".tabbar button")) {
    if (tab.dataset.view === name) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  }
  if (name === "today") safely(renderToday);
  if (name === "trends") safely(renderTrends);
  if (name === "goals") safely(renderGoals);
  if (name !== "log") stopScanner();
  window.scrollTo(0, 0);
}

function setDate(isoDate) {
  state.date = isoDate;
  $("#day-label").textContent = friendlyDate(isoDate);
  for (const el of $$(".log-day")) el.textContent = friendlyDate(isoDate).toLowerCase();
  $("#next-day").disabled = isoDate >= localDate(new Date());
  if (!$("#view-today").hidden) safely(renderToday);
}

// ---------- Today ----------

async function renderToday() {
  const day = await api("GET", `/days/${state.date}`);
  state.goals = day.goals;
  $("#goal-prompt").hidden = Boolean(day.goals);

  const goals = day.goals || {};
  const totals = day.totals;

  // Protein: the big number
  const left = goals.protein_g ? Math.max(0, goals.protein_g - totals.protein_g) : totals.protein_g;
  $("#protein-left").textContent = fmt(left, 1);
  $("#protein-caption").textContent = !goals.protein_g
    ? "protein so far"
    : left === 0 ? `protein goal hit: ${fmt(totals.protein_g, 1)}g` : `protein to go, of ${fmt(goals.protein_g)}g`;
  $("#protein-bar").style.width = `${percent(totals.protein_g, goals.protein_g)}%`;

  // Calories, sleep, training
  $("#calories-total").textContent = fmt(totals.calories);
  $("#calories-goal").textContent = goals.calories ? `of ${fmt(goals.calories)}` : "";
  $("#calories-bar").style.width = `${percent(totals.calories, goals.calories)}%`;

  $("#sleep-total").textContent = day.sleep ? `${fmt(day.sleep.hours, 2)} h` : "Not logged";
  $("#sleep-goal").textContent = goals.sleep_hours ? `of ${fmt(goals.sleep_hours, 2)} h` : "";
  $("#sleep-bar").style.width = `${percent(totals.sleep_hours, goals.sleep_hours)}%`;

  $("#volume-total").textContent = fmt(day.workout_volume);

  // Lists
  $("#meal-list").innerHTML = day.meals.length
    ? day.meals.map((m) => `
        <li>
          <div>${esc(m.name)}<div class="detail">${fmt(m.protein_g, 1)}g protein, ${fmt(m.calories)} cal</div></div>
          <button class="delete" data-delete="meals" data-id="${esc(m.id)}">Delete</button>
        </li>`).join("")
    : `<li class="empty">No meals logged. Add one from Log.</li>`;

  $("#workout-list").innerHTML = day.workouts.length
    ? day.workouts.map((w) => `
        <li>
          <div>${esc(w.exercise)}<div class="detail">${fmt(w.sets)} &times; ${fmt(w.reps)} at ${fmt(w.weight, 1)}</div></div>
          <button class="delete" data-delete="workouts" data-id="${esc(w.id)}">Delete</button>
        </li>`).join("")
    : `<li class="empty">No training logged.</li>`;
}

async function deleteEntry(button) {
  await withButton(button, async () => {
    await api("DELETE", `/days/${state.date}/${button.dataset.delete}/${button.dataset.id}`);
    toast("Deleted");
    await renderToday();
  });
}

// ---------- Log: meals ----------

async function saveMeal(meal) {
  await api("POST", "/meals", { date: state.date, ...meal });
  toast(`Meal saved for ${friendlyDate(state.date).toLowerCase()}`);
}

async function estimateMeal(button) {
  const text = $("#meal-text").value.trim();
  if (!text) return toast("Describe what you ate first.", true);

  await withButton(button, async () => {
    const estimate = await api("POST", "/meals/parse", { text });
    state.pendingMeal = estimate;
    const rows = estimate.items.map((item) => `
      <tr>
        <td>${item.matched_name ? esc(item.matched_name) : `<span class="unmatched">${esc(item.food)}: not found, counted as 0</span>`}</td>
        <td class="num">${fmt(item.grams)} g</td>
        <td class="num">${fmt(item.protein_g, 1)} g</td>
        <td class="num">${fmt(item.calories)}</td>
      </tr>`).join("");

    $("#estimate-result").innerHTML = `
      <table class="estimate-table">
        <thead><tr><th>Food</th><th class="num">Amount</th><th class="num">Protein</th><th class="num">Cal</th></tr></thead>
        <tbody>${rows}</tbody>
        <tfoot><tr><th>Total</th><th></th><th class="num">${fmt(estimate.protein_g, 1)} g</th><th class="num">${fmt(estimate.calories)}</th></tr></tfoot>
      </table>
      <p class="hint">Amounts are estimates. If something's off, enter the meal yourself below.</p>
      <div class="button-row">
        <button class="button primary" id="save-estimate">Save meal</button>
        <button class="button" id="discard-estimate">Discard</button>
      </div>`;
    $("#estimate-result").hidden = false;
  });
}

async function saveEstimate(button) {
  const estimate = state.pendingMeal;
  await withButton(button, async () => {
    await saveMeal({
      name: estimate.text.slice(0, 100),
      calories: estimate.calories,
      protein_g: estimate.protein_g,
    });
    discardEstimate();
    $("#meal-text").value = "";
  });
}

function discardEstimate() {
  state.pendingMeal = null;
  $("#estimate-result").hidden = true;
  $("#estimate-result").innerHTML = "";
}

// ---------- Log: food search and barcodes ----------

async function searchFoods(form) {
  const query = $("#food-query").value.trim();
  await withButton(form.querySelector("button"), async () => {
    const { results } = await api("GET", `/foods/search?q=${encodeURIComponent(query)}`);
    state.searchResults = results;
    $("#food-results").innerHTML = results.length
      ? results.map((food, i) => `
          <li>
            <div>${esc(food.name)}<div class="detail">per 100 g: ${fmt(food.protein_per_100g, 1)}g protein, ${fmt(food.calories_per_100g)} cal</div></div>
            <button class="button" data-pick="${i}">Use</button>
          </li>`).join("")
      : `<li class="empty">No matches. Try a simpler name, like "salmon" or "oats".</li>`;
  });
}

function choosePortion(food) {
  state.pendingFood = food;
  const grams = food.serving_g || 100;
  $("#portion").innerHTML = `
    <p><strong>${esc(food.name)}</strong></p>
    <form id="portion-form" class="inline-form">
      <input name="grams" type="number" min="1" max="2000" value="${grams}" required aria-label="Amount in grams">
      <button class="button primary">Save ${food.serving_g ? "(1 serving = " + fmt(food.serving_g) + " g)" : "meal"}</button>
    </form>`;
  $("#portion").hidden = false;
  $("#portion input").focus();
}

async function savePortion(form) {
  const food = state.pendingFood;
  const grams = Number(form.grams.value);
  await withButton(form.querySelector("button"), async () => {
    await saveMeal({
      name: `${food.name} (${fmt(grams)} g)`.slice(0, 100),
      calories: Math.round((food.calories_per_100g * grams) / 100),
      protein_g: Math.round((food.protein_per_100g * grams) / 10) / 10,
    });
    state.pendingFood = null;
    $("#portion").hidden = true;
    $("#food-results").innerHTML = "";
  });
}

async function findBarcode(code) {
  try {
    const product = await api("GET", `/barcode/${encodeURIComponent(code)}`);
    choosePortion(product);
  } catch (error) {
    if (error.status !== 401) toast(error.message, true);
  }
}

/** The barcode library (~370 KB) only loads when you first tap "Scan". */
function loadScannerLibrary() {
  if (window.Html5Qrcode) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://cdn.jsdelivr.net/npm/html5-qrcode@2.3.8/html5-qrcode.min.js";
    script.onload = resolve;
    script.onerror = () => reject(new Error("Couldn't load the barcode scanner. Type the number instead."));
    document.head.appendChild(script);
  });
}

async function toggleScanner(button) {
  if (state.scanner) return stopScanner();
  await withButton(button, async () => {
    await loadScannerLibrary();
    $("#scanner").hidden = false;
    const scanner = new window.Html5Qrcode("scanner");
    try {
      await scanner.start(
        { facingMode: "environment" }, // the back camera
        { fps: 10, qrbox: { width: 260, height: 120 } },
        async (code) => {
          await stopScanner();
          await findBarcode(code);
        },
        () => {}, // called on every frame without a barcode; nothing to do
      );
    } catch {
      $("#scanner").hidden = true;
      throw new Error("Couldn't open the camera. Allow camera access, or type the number.");
    }
    state.scanner = scanner;
    button.textContent = "Stop scanning";
  });
}

async function stopScanner() {
  if (!state.scanner) return;
  try {
    await state.scanner.stop();
  } catch {
    // already stopped
  }
  state.scanner = null;
  $("#scanner").hidden = true;
  $("#scan-barcode").textContent = "Scan a barcode";
}

// ---------- Log: sleep and training ----------

async function saveSleep(form) {
  await withButton(form.querySelector("button"), async () => {
    await api("POST", "/sleep", { date: state.date, hours: Number(form.hours.value) });
    toast("Sleep saved");
    form.reset();
  });
}

async function saveWorkout(form) {
  await withButton(form.querySelector("button"), async () => {
    await api("POST", "/workouts", { date: state.date, ...formData(form) });
    toast("Exercise added");
    // Keep the exercise name, since you often log several sets of the same lift.
    const exercise = form.exercise.value;
    form.reset();
    form.exercise.value = exercise;
  });
}

// ---------- Trends ----------

async function renderTrends() {
  const today = localDate(new Date());
  const data = await api("GET", `/insights?end=${today}&days=${state.trendDays}`);
  const goal = state.goals || {};

  const stat = (cls, value, label) =>
    `<div class="stat ${cls}"><strong>${value}</strong><span>${label}</span></div>`;

  const good = data.avg_volume_after_good_sleep;
  const short = data.avg_volume_after_short_sleep;
  const sleepEffect = good !== null && short !== null
    ? stat("training wide", `${fmt(good)} vs ${fmt(short)}`,
        `average training volume after ${fmt(data.sleep_target, 2)}+ hours of sleep vs less`)
    : stat("training wide", "Not enough data",
        "log sleep on training days to compare your volume after full and short nights");

  $("#trend-stats").innerHTML = [
    stat("protein", data.avg_protein_g === null ? "None" : `${fmt(data.avg_protein_g, 1)} g`, "average daily protein"),
    stat("protein", data.protein_goal_days === null ? "Set a goal" : `${data.protein_goal_days} of ${data.days_with_meals}`, "days protein goal hit"),
    stat("sleep", data.avg_sleep_hours === null ? "None" : `${fmt(data.avg_sleep_hours, 1)} h`, "average sleep"),
    stat("training", `${data.workout_days}`, "training days"),
    sleepEffect,
  ].join("");

  // A tiny chart: one red bar (protein) and one blue bar (sleep) per day.
  $("#trend-chart").innerHTML = data.daily.map((d) => {
    const p = d.protein_g === null ? null : percent(d.protein_g, goal.protein_g || 150);
    const s = d.sleep_hours === null ? null : percent(d.sleep_hours, goal.sleep_hours || 8);
    const bar = (cls, value) => value === null
      ? `<span class="none" style="height:2px"></span>`
      : `<span class="${cls}" style="height:${value}%"></span>`;
    // Weekday letters fit under 7 days; 28 days would be too crowded.
    const label = state.trendDays <= 7
      ? `<small>${new Date(`${d.date}T12:00:00`).toLocaleDateString(undefined, { weekday: "narrow" })}</small>`
      : "";
    return `<div class="trend-day" title="${esc(friendlyDate(d.date))}">
      <div class="trend-bars">${bar("p", p)}${bar("s", s)}</div>${label}</div>`;
  }).join("");
}

// ---------- Goals ----------

async function renderGoals() {
  if (!state.goals) {
    try {
      state.goals = await api("GET", "/goals");
    } catch (error) {
      if (error.status !== 404) throw error;
    }
  }
  const form = $("#goals-form");
  if (state.goals) {
    form.protein_g.value = state.goals.protein_g;
    form.calories.value = state.goals.calories;
    form.sleep_hours.value = state.goals.sleep_hours;
    form.reminders.checked = state.goals.reminders !== false;
  }
}

async function saveGoals(form) {
  await withButton(form.querySelector("button"), async () => {
    const data = formData(form);
    state.goals = await api("PUT", "/goals", {
      calories: data.calories,
      protein_g: data.protein_g,
      sleep_hours: data.sleep_hours,
      reminders: form.reminders.checked,
      // Lets the server work out "today" for your evening email.
      utc_offset_minutes: -new Date().getTimezoneOffset(),
    });
    toast("Goals saved");
  });
}

// ---------- Wiring it all up ----------

function bindEvents() {
  for (const tab of $$(".tabbar button")) tab.addEventListener("click", () => showView(tab.dataset.view));
  $("#goal-prompt button").addEventListener("click", () => showView("goals"));
  $("#prev-day").addEventListener("click", () => setDate(addDays(state.date, -1)));
  $("#next-day").addEventListener("click", () => setDate(addDays(state.date, 1)));
  $("#sign-out").addEventListener("click", logout);

  // Clicks on buttons that are created later (delete, use, save estimate)
  document.addEventListener("click", (event) => {
    const target = event.target.closest("button");
    if (!target) return;
    if (target.dataset.delete) deleteEntry(target);
    if (target.dataset.pick) choosePortion(state.searchResults[Number(target.dataset.pick)]);
    if (target.id === "save-estimate") saveEstimate(target);
    if (target.id === "discard-estimate") discardEstimate();
  });

  $("#estimate-meal").addEventListener("click", (e) => estimateMeal(e.currentTarget));
  $("#scan-barcode").addEventListener("click", (e) => toggleScanner(e.currentTarget));

  const onSubmit = (selector, handler) =>
    $(selector).addEventListener("submit", (event) => {
      event.preventDefault();
      handler(event.target);
    });

  onSubmit("#food-search", searchFoods);
  onSubmit("#barcode-form", (form) => findBarcode(form.querySelector("input").value.trim()));
  onSubmit("#manual-meal", (form) => withButton(form.querySelector("button"), async () => {
    await saveMeal(formData(form));
    form.reset();
  }));
  onSubmit("#sleep-form", saveSleep);
  onSubmit("#workout-form", saveWorkout);
  onSubmit("#goals-form", saveGoals);
  document.addEventListener("submit", (event) => {
    if (event.target.id === "portion-form") {
      event.preventDefault();
      savePortion(event.target);
    }
  });

  for (const button of $$(".segmented button")) {
    button.addEventListener("click", () => {
      state.trendDays = Number(button.dataset.days);
      for (const b of $$(".segmented button")) b.setAttribute("aria-pressed", String(b === button));
      safely(renderTrends);
    });
  }
}

async function start() {
  try {
    await handleLoginRedirect();
  } catch (error) {
    toast(error.message, true);
  }

  if (!isSignedIn()) {
    $("#signed-out").hidden = false;
    $("#sign-in").addEventListener("click", login);
    return;
  }

  $("#app").hidden = false;
  bindEvents();
  setDate(state.date); // also loads today's data
}

start();
