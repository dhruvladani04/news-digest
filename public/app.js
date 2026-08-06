/* Daily Digest — static dashboard.
   Reads data/index.json for the archive, then data/<date>.json for a day.
   No build step, no dependencies. */

const $ = (id) => document.getElementById(id);

const state = {
  index: null,
  date: null,
  digest: null,
};

/* ----------------------------------------------------------------- theme */

const THEME_KEY = "digest-theme";
function initTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  const prefersLight = window.matchMedia("(prefers-color-scheme: light)").matches;
  document.documentElement.dataset.theme = saved || (prefersLight ? "light" : "dark");
}
function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem(THEME_KEY, next);
}

/* ------------------------------------------------------------- utilities */

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function relTime(iso) {
  if (!iso) return "";
  const then = new Date(iso);
  if (isNaN(then)) return "";
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const h = Math.round(mins / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  return d === 1 ? "yesterday" : `${d}d ago`;
}

function prettyDate(ymd) {
  const [y, m, d] = ymd.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC",
  });
}

function shortDate(ymd) {
  const [y, m, d] = ymd.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    weekday: "short", day: "numeric", month: "short", timeZone: "UTC",
  });
}

/* -------------------------------------------------------------- rendering */

function storyCard(item, sectorId, isLead) {
  const tags = (item.tags || [])
    .map((t) => `<span class="tag tag-${esc(t)}">${esc(t)}</span>`).join("");

  const hot = item.corroboration >= 3
    ? `<span class="hot">${item.corroboration} outlets</span>` : "";

  const author = item.author ? `<span class="dot">·</span><span>${esc(item.author)}</span>` : "";
  const when = relTime(item.published);
  const whenEl = when ? `<span class="dot">·</span><span>${esc(when)}</span>` : "";

  const also = (item.also_in && item.also_in.length)
    ? `<div class="also"><b>Also covered by</b> ${esc(item.also_in.slice(0, 6).join(", "))}</div>`
    : "";

  const summary = item.summary ? `<p>${esc(item.summary)}</p>` : "";

  return `
<a class="card ${isLead ? "card-lead" : ""} s-${esc(sectorId)}"
   href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">
  <div class="card-meta">
    <span class="tier tier-${item.tier}" title="Source tier ${item.tier}"></span>
    <span class="src">${esc(item.source)}</span>
    ${whenEl}${author}
    ${tags}${hot}
  </div>
  <h3>${esc(item.title)}</h3>
  ${summary}
  ${also}
</a>`;
}

function sectionHtml(sec, i) {
  const lead = sec.top.slice(0, 3).map((it) => storyCard(it, sec.id, true)).join("");
  const rest = sec.top.slice(3).map((it) => storyCard(it, sec.id, false)).join("");
  const more = (sec.more || []).map((it) => storyCard(it, sec.id, false)).join("");

  const body = sec.top.length
    ? lead + rest
    : `<div class="empty">No stories cleared the bar for this sector today.</div>`;

  const moreBlock = more
    ? `<button class="more-btn" data-more="${esc(sec.id)}">
         Show ${sec.more.length} more from ${esc(sec.name)}
       </button>
       <div class="more-wrap" id="more-${esc(sec.id)}">${more}</div>`
    : "";

  return `
<section class="section s-${esc(sec.id)}" id="sec-${esc(sec.id)}">
  <div class="sec-head">
    <h2>${esc(sec.name)}</h2>
    <span class="sec-count">${sec.count} unique ${sec.count === 1 ? "story" : "stories"}</span>
  </div>
  <p class="sec-blurb">${esc(sec.blurb || "")}</p>
  ${body}
  ${moreBlock}
</section>`;
}

function renderNav(sectors) {
  $("sectorNav").innerHTML = sectors.map((s, i) => `
    <button class="navchip s-${esc(s.id)}" data-jump="sec-${esc(s.id)}">
      <span class="kbd">${i + 1}</span>${esc(s.name)}
    </button>`).join("");
}

function renderDigest(d) {
  state.digest = d;
  $("brandSub").textContent =
    `${prettyDate(d.date)} · built ${new Date(d.generated_at).toLocaleTimeString("en-GB",
      { hour: "2-digit", minute: "2-digit" })} IST`;

  renderNav(d.sectors);
  $("main").innerHTML = d.sectors.map(sectionHtml).join("");

  const m = d.meta || {};
  const failed = (m.failed_feeds || []).length;
  $("footMeta").textContent =
    `${m.items_published ?? 0} stories from ${m.feeds_ok ?? 0}/${m.feeds_total ?? 0} feeds` +
    ` · ${m.items_fetched ?? 0} items scanned over the last ${d.window_hours ?? 24}h` +
    (failed ? ` · ${failed} feed${failed === 1 ? "" : "s"} unreachable` : "");

  wireSectionEvents();
  observeSections();
  window.scrollTo({ top: 0 });
}

function wireSectionEvents() {
  document.querySelectorAll("[data-more]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const wrap = $(`more-${btn.dataset.more}`);
      const open = wrap.classList.toggle("open");
      btn.textContent = open
        ? "Show less"
        : `Show ${wrap.children.length} more`;
    });
  });
}

/* highlight the sector chip for whatever is on screen */
function observeSections() {
  const chips = [...document.querySelectorAll(".navchip")];
  const obs = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (!e.isIntersecting) return;
      chips.forEach((c) => c.classList.toggle(
        "active", c.dataset.jump === e.target.id));
    });
  }, { rootMargin: "-110px 0px -70% 0px" });
  document.querySelectorAll(".section").forEach((s) => obs.observe(s));
}

/* ------------------------------------------------------------------ data */

async function loadDate(date, push = true) {
  $("main").innerHTML =
    `<div class="loading"><div class="spinner"></div><p>Loading ${esc(prettyDate(date))}…</p></div>`;
  try {
    const res = await fetch(`data/${date}.json?v=${Date.now()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const d = await res.json();
    state.date = date;
    $("datePicker").value = date;
    updateArrows();
    if (push) history.replaceState(null, "", `?date=${date}`);
    renderDigest(d);
  } catch (err) {
    $("main").innerHTML = `<div class="err">
      <strong>Couldn't load ${esc(date)}</strong>
      ${esc(err.message)}. That day's digest may not have been built yet.
    </div>`;
  }
}

function updateArrows() {
  const i = state.index.dates.indexOf(state.date);
  $("nextDay").disabled = i <= 0;                       // dates are newest-first
  $("prevDay").disabled = i < 0 || i >= state.index.dates.length - 1;
}

function step(delta) {
  const i = state.index.dates.indexOf(state.date);
  const next = state.index.dates[i + delta];
  if (next) loadDate(next);
}

async function boot() {
  initTheme();

  $("themeToggle").addEventListener("click", toggleTheme);
  $("prevDay").addEventListener("click", () => step(1));   // older
  $("nextDay").addEventListener("click", () => step(-1));  // newer
  $("datePicker").addEventListener("change", (e) => loadDate(e.target.value));

  document.addEventListener("click", (e) => {
    const chip = e.target.closest("[data-jump]");
    if (chip) $(chip.dataset.jump)?.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "SELECT" || e.metaKey || e.ctrlKey) return;
    const n = parseInt(e.key, 10);
    if (n >= 1 && n <= 9) {
      document.querySelectorAll(".navchip")[n - 1]
        ?.dispatchEvent(new Event("click", { bubbles: true }));
    }
    if (e.key === "ArrowLeft") step(1);
    if (e.key === "ArrowRight") step(-1);
    if (e.key === "t") toggleTheme();
  });

  try {
    const res = await fetch(`data/index.json?v=${Date.now()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.index = await res.json();
  } catch (err) {
    $("main").innerHTML = `<div class="err">
      <strong>No digests found yet</strong>
      Run the workflow once (Actions → Daily news digest → Run workflow)
      to build the first day. <span>${esc(err.message)}</span>
    </div>`;
    return;
  }

  $("datePicker").innerHTML = state.index.dates
    .map((d) => `<option value="${d}">${shortDate(d)}</option>`).join("");

  const wanted = new URLSearchParams(location.search).get("date");
  const start = state.index.dates.includes(wanted) ? wanted : state.index.dates[0];
  if (!start) {
    $("main").innerHTML = `<div class="err"><strong>Archive is empty</strong>
      No digest files have been generated yet.</div>`;
    return;
  }
  loadDate(start, false);
}

boot();
