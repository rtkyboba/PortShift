const NAMES = {0: "Not scored", 1: "Clear", 2: "Watch", 3: "At risk", 4: "Severe", 5: "Critical"};
const MODE_ICONS = { // one icon per mode, drawn on a 24 x 24 grid
  ship: "M3 17l1.5-5h15L21 17c-1.5 1.5-3 1.5-4.5 0-1.5 1.5-3 1.5-4.5 0-1.5 1.5-3 1.5-4.5 0-1.5 1.5-3 1.5-4.5 0zM7 11V7h4V4h2v3h4v4z",
  truck: "M2 6h11v9H2zM14 9h4l3 3v3h-7zM6.5 19a2 2 0 100-4 2 2 0 000 4zM17.5 19a2 2 0 100-4 2 2 0 000 4z",
  plane: "M21 16v-2l-8-5V3.5a1.5 1.5 0 00-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z",
};
const COST_NOTE = "estimate, illustrative rates";
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const COLORS = {};
for (let i = 0; i <= 5; i++) COLORS[i] = css("--risk-" + i);

const $ = id => document.getElementById(id);
const el = (tag, props = {}, ...kids) => {
  const e = Object.assign(document.createElement(tag), props);
  kids.flat().forEach(k => e.append(k));
  return e;
};
const getJSON = async url => (await fetch(url)).json();

// ---- motion: a window opens out of what opened it and closes back into it (scale + fade, a slight spring),
// closing faster than opening; transform and opacity only; reopening interrupts a close; off for reduced motion ----
const calm = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const EASE_OPEN = "cubic-bezier(0.2, 0.9, 0.3, 1.1)", EASE_CLOSE = "cubic-bezier(0.4, 0, 1, 1)";
function originFrom(win, trigger) {
  if (!trigger) return "50% 0%";
  const w = win.getBoundingClientRect(), t = trigger.getBoundingClientRect();
  return `${t.left + t.width / 2 - w.left}px ${t.top + t.height / 2 - w.top}px`;
}
function openWindow(win, trigger) { // after the window is shown and placed
  if (win._closing) { win._closing.cancel(); win._closing = null; }
  if (calm()) return;
  win.style.transformOrigin = originFrom(win, trigger);
  win.animate([{transform: "scale(0.12)", opacity: 0}, {opacity: 1, offset: 0.45}, {transform: "scale(1)", opacity: 1}], {duration: 380, easing: EASE_OPEN});
}
function closeWindow(win, trigger, hide) { // shrink into the trigger, then hide; the timer makes the end state certain
  if (calm() || win.hidden) return hide();
  win.style.transformOrigin = originFrom(win, trigger);
  const a = win.animate([{transform: "scale(1)", opacity: 1}, {transform: "scale(0.12)", opacity: 0}], {duration: 220, easing: EASE_CLOSE, fill: "forwards"});
  win._closing = a;
  const end = () => { if (win._closing !== a) return; win._closing = null; hide(); a.cancel(); };
  a.onfinish = end; setTimeout(end, 300);
}
const lvlOf = s => s.risk.level || 0;
const dt = iso => iso ? new Date(iso).toLocaleString([], {day: "numeric", month: "short", hour: "2-digit", minute: "2-digit"}) : "unknown";
const day = iso => new Date(iso).toLocaleDateString([], {day: "numeric", month: "short"});
const money = (v, c) => `${c || "EUR"} ${Math.round(v).toLocaleString()}`;
const cap = t => t.charAt(0).toUpperCase() + t.slice(1).replaceAll("_", " ");
function span(iso) { // "12 min", "3 h", "2 days" between now and a time, either direction
  const m = Math.round(Math.abs(Date.now() - new Date(iso)) / 60000);
  return m < 60 ? `${m} min` : m < 2880 ? `${Math.round(m / 60)} h` : `${Math.round(m / 1440)} days`;
}
const ago = iso => `retrieved ${span(iso)} ago`;
// Links come from stored evidence: only http(s) is followed, so a "javascript:" url in a source cannot run.
const safeHref = u => /^https?:\/\//i.test(String(u || "")) ? u : "#";
const link = (href, text) => el("a", {href: safeHref(href), target: "_blank", rel: "noopener noreferrer"}, text);

// A flight is drawn along the great circle between its points, not as a straight line on the map projection
// (Frankfurt to Los Angeles goes over Greenland, not across the Atlantic at 45 degrees north). Other modes keep
// their stored line. Worked out once per leg.
function greatCircle(g, steps = 48) {
  const rad = Math.PI / 180, out = [];
  for (let i = 0; i < g.length - 1; i++) {
    const [la1, lo1, la2, lo2] = [g[i][0] * rad, g[i][1] * rad, g[i + 1][0] * rad, g[i + 1][1] * rad];
    const d = 2 * Math.asin(Math.sqrt(Math.sin((la2 - la1) / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin((lo2 - lo1) / 2) ** 2));
    if (d < 0.08) { out.push(g[i]); continue; } // under about 500 km a straight line is the same thing
    for (let k = 0; k < steps; k++) { const f = k / steps, a = Math.sin((1 - f) * d) / Math.sin(d), b = Math.sin(f * d) / Math.sin(d);
      const x = a * Math.cos(la1) * Math.cos(lo1) + b * Math.cos(la2) * Math.cos(lo2), y = a * Math.cos(la1) * Math.sin(lo1) + b * Math.cos(la2) * Math.sin(lo2), z = a * Math.sin(la1) + b * Math.sin(la2);
      let lon = Math.atan2(y, x) / rad; const prev = out.length ? out[out.length - 1][1] : g[i][1];
      while (lon - prev > 180) lon -= 360; while (lon - prev < -180) lon += 360; // keep the line continuous across the date line
      out.push([Math.atan2(z, Math.hypot(x, y)) / rad, lon]); }
  }
  return [...out, g[g.length - 1]];
}
const lineOf = leg => leg.mode !== "plane" ? leg.geometry : (leg._line ||= greatCircle(leg.geometry));

// Where the vehicle is now, from leg times and the leg geometry (demo fleet, planned positions).
function position(s, now = Date.now()) {
  const legs = s.legs; if (!legs.length) return null;
  // walk the polyline by distance so uneven waypoint spacing does not distort speed
  const at = (g, t) => {
    const d = (p, q) => Math.hypot(q[0] - p[0], (q[1] - p[1]) * Math.cos((p[0] + q[0]) * Math.PI / 360));
    const seg = g.slice(1).map((q, i) => d(g[i], q)), total = seg.reduce((x, y) => x + y, 0);
    let rem = Math.min(1, Math.max(0, t)) * total;
    for (let i = 0; i < seg.length; i++) {
      if (rem <= seg[i] || i === seg.length - 1) { const k = seg[i] ? Math.min(1, rem / seg[i]) : 0;
        return [g[i][0] + (g[i + 1][0] - g[i][0]) * k, g[i][1] + (g[i + 1][1] - g[i][1]) * k]; }
      rem -= seg[i];
    }
  };
  if (now <= new Date(legs[0].planned_start)) return [legs[0].from_lat, legs[0].from_lon];
  for (let i = 0; i < legs.length; i++) {
    const a = new Date(legs[i].planned_start), b = new Date(legs[i].planned_end);
    if (now <= b) return now >= a ? at(lineOf(legs[i]), (now - a) / (b - a)) : [legs[i - 1].to_lat, legs[i - 1].to_lon];
  }
  const l = legs[legs.length - 1]; return [l.to_lat, l.to_lon];
}

const esc = t => String(t).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const svgIcon = mode => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${MODE_ICONS[mode] || ""}"/></svg>`;
const FREIGHT = {ship: "Ocean freight", truck: "Road freight", plane: "Air freight"};
const riskLabel = lvl => lvl ? `R${lvl} · ${NAMES[lvl]}` : NAMES[0];
const postJSON = async (url, body) => {
  const r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
};
// What each level means, in the operator's words (the scoring rules themselves are in AGENTS.md).
const MEANING = {
  1: "No known disruption anywhere on the remaining route.",
  2: "An unconfirmed report on the route, more than 3 days before the shipment gets there.",
  3: "An unconfirmed report within 3 days, or a confirmed disruption close to the route but not on it.",
  4: "A confirmed disruption on a later leg, more than a day away.",
  5: "A confirmed closure or strike on the current or next leg, while the shipment is due there.",
};
// What accepting each level means when rescheduling: the trade between safety, money and time.
const ACCEPT = {
  1: "Avoid the disruption completely. Lowest chance of being held up; usually the longest delay or detour and the highest cost.",
  2: "Accept an unconfirmed report that is still days away. Small chance of a second disruption; often cheaper than avoiding everything.",
  3: "Accept an unconfirmed report close in time, or a confirmed disruption near the route. Moderate chance of delay; less added cost and time.",
  4: "Accept a confirmed disruption on a later leg. Cheapest change now, but expect to reschedule again before the shipment gets there.",
  5: "Accept the disruption as it stands. No extra cost now; expect the shipment to be held when it arrives.",
};

// ---- map: flat vector countries when zoomed out (the design's look), street tiles when zoomed in ----
const map = L.map("map", {zoomControl: false, minZoom: 2, zoomSnap: 0.5, maxBounds: [[-80, -220], [86, 220]], maxBoundsViscosity: 0.7}).setView([52.6, -5.5], 5.5); // opens on the UK and north-west Europe, clear of the left panel
L.control.zoom({position: "bottomright"}).addTo(map);
map.createPane("land").style.zIndex = 250;
const TILE_FROM = 6;
const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {attribution: "&copy; OpenStreetMap contributors", maxZoom: 18, minZoom: TILE_FROM}).addTo(map);
let land = null;
const landStyle = () => { const far = map.getZoom() < TILE_FROM;
  return {color: css("--land-line"), weight: 0.8, fillColor: css("--land"), fillOpacity: far ? 1 : 0, opacity: far ? 1 : 0}; };
fetch("https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-50m.json").then(r => r.json()).then(t => {
  const world = topojson.feature(t, t.objects.countries);
  world.features = world.features.filter(f => f.properties.name !== "Antarctica");
  // Shapes that cross the date line jump from +180 to -180 and draw a line across the whole map: keep them continuous.
  const unwrap = ring => { for (let i = 1; i < ring.length; i++) { const d = ring[i][0] - ring[i - 1][0]; if (d > 180) ring[i][0] -= 360; else if (d < -180) ring[i][0] += 360; } };
  world.features.forEach(f => (f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates).forEach(poly => poly.forEach(unwrap)));
  land = L.geoJSON(world, {pane: "land", interactive: false, style: landStyle}).addTo(map);
}).catch(() => { tiles.remove(); tiles.options.minZoom = 0; tiles.addTo(map); }); // no shapes: fall back to tiles at every zoom
map.on("zoomend", () => land && land.setStyle(landStyle()));
const eventLayer = L.layerGroup().addTo(map), shipLayer = L.layerGroup().addTo(map);
// Small origin/destination dots for every shipment, only once zoomed in far enough that they don't clutter the overview.
const END_DOTS_FROM = 6, endLayer = L.layerGroup();
const toggleEndDots = () => map.getZoom() >= END_DOTS_FROM ? endLayer.addTo(map) : endLayer.remove();
map.on("zoomend", toggleEndDots); toggleEndDots();
// Keep whatever is fitted clear of the floating left panel.
const fit = (bounds, maxZoom = 8) => { map.invalidateSize(); map.fitBounds(bounds, {paddingTopLeft: [430, 90], paddingBottomRight: [70, 90], maxZoom}); };

let ships = [], events = [], summary = null, decisions = [], rates = null;
let selected = null, detail = null, ptab = "details", focusEvent = null, hoverId = null, view = "map";
let optRoutes = null; // what to draw for each option of the open shipment (POST /api/options/routes)
// What the map shows, ticked in the map key. Everything is on to start with; the choice is kept in this browser.
const SHOW_KEYS = ["warehouse", "depots", "customer", "port", "airport", "ship", "truck", "plane", "lvl1", "lvl2", "lvl3", "lvl4", "lvl5", "confirmed", "suspected", "done", "ahead", "ends"];
const mapShow = Object.fromEntries(SHOW_KEYS.map(k => [k, true]));
try { for (const k of JSON.parse(localStorage.getItem("portshift.mapshow") || "[]")) if (k in mapShow) mapShow[k] = false; } catch { /* all on */ }
const saveShow = () => { try { localStorage.setItem("portshift.mapshow", JSON.stringify(SHOW_KEYS.filter(k => !mapShow[k]))); } catch { /* not stored */ } };
const optimising = () => !!(selected && ptab === "plan" && opts && !opts.error && opts.options?.length); // choosing between options for one shipment
const lossText = v => `−${money(Math.abs(v))}`; // a cost to the operator: shown with a minus and in red (.loss)
const deltaText = h => !h ? "no delay" : h < 48 ? `+${Math.round(h)} h` : `+${+(h / 24).toFixed(1)} days`;
let opts = null, pickedId = null;           // reschedule options for the open shipment, and the one picked
const logs = {};                            // chat thread per shipment
const filter = {levels: new Set(), modes: new Set(), q: "", status: "all"};
const sort = {map: "risk", evt: "time"};

// The operator's limits on risk, cost and delay, sent with every chat message and options request
// (CONTRACTS.md section 5). A preset is a named set of limits plus how to pick among the options.
const PRESETS = {
  balanced: {label: "Balanced", desc: "Lower the risk without overpaying.", prefs: {max_risk: 2, max_extra_cost: 5000, max_delay_hours: null}},
  low_cost: {label: "Low cost", desc: "Spend as little as possible; accept more risk.", prefs: {max_risk: 4, max_extra_cost: 1500, max_delay_hours: null}},
  low_risk: {label: "Low risk", desc: "Avoid the disruption; cost and time come second.", prefs: {max_risk: 1, max_extra_cost: null, max_delay_hours: null}},
};
let preset = "balanced", limits = {...PRESETS.balanced.prefs};
try { const saved = JSON.parse(localStorage.getItem("portshift.prefs") || "null");
  if (saved && saved.limits) { preset = saved.preset || "custom"; limits = {...limits, ...saved.limits}; } } catch { /* keep defaults */ }
const COST_MAX = 10000; // slider top = no limit
const DELAYS = [[null, "Any delay"], [12, "12 h"], [24, "24 h"], [48, "2 days"], [72, "3 days"], [168, "7 days"]];
const hours = h => h == null ? "any delay" : h % 24 === 0 && h >= 48 ? `${h / 24} days` : `${h} h`;
const presetName = () => PRESETS[preset]?.label || "Custom";
const pickName = () => draft.urgency === "fastest" ? "Fastest" : draft.urgency === "deadline" ? `On time · ${presetName()}` : `Best for ${presetName()}`;
const limitsText = () => `risk ≤ ${limits.max_risk} ${NAMES[limits.max_risk]} · ${limits.max_extra_cost == null ? "any cost" : "≤ " + money(limits.max_extra_cost)} · ${limits.max_delay_hours == null ? "any delay" : "delay ≤ " + hours(limits.max_delay_hours)}`;

// ---- sorting: what an operator triages by ----
const far = v => v == null ? Infinity : +new Date(v);
const SORT_SHIP = {
  risk: ["Highest risk", (a, b) => lvlOf(b) - lvlOf(a) || far(a.impact_at) - far(b.impact_at)],
  time: ["Most time-critical", (a, b) => far(a.impact_at) - far(b.impact_at) || lvlOf(b) - lvlOf(a)],
  cost: ["Highest cost", (a, b) => (b.wait_out?.cost || 0) - (a.wait_out?.cost || 0) || lvlOf(b) - lvlOf(a)],
  eta: ["Arriving soonest", (a, b) => far(a.eta) - far(b.eta)],
};
const evLevel = e => Math.max(0, ...e.shipments.map(x => x.level || 0));
const evOver = e => Date.now() > +new Date(e.window_end);
const SORT_EVT = {
  time: ["Most time-critical", (a, b) => evOver(a) - evOver(b) || far(a.window_start) - far(b.window_start)],
  cost: ["Highest cost", (a, b) => b.exposure - a.exposure],
  risk: ["Highest risk", (a, b) => evLevel(b) - evLevel(a) || far(a.window_start) - far(b.window_start)],
  ships: ["Most shipments hit", (a, b) => b.shipments.length - a.shipments.length],
  recent: ["Most recently reported", (a, b) => far(b.detected_at) - far(a.detected_at)],
};
function evWhen(e) {
  const now = Date.now(), a = +new Date(e.window_start), b = +new Date(e.window_end);
  return now < a ? [`Starts in ${span(e.window_start)}`, a - now < 864e5] : now <= b ? [`Under way · ends in ${span(e.window_end)}`, true] : ["Window has passed", false];
}

function visible() {
  const q = filter.q.toLowerCase();
  return ships.filter(s =>
    (!filter.levels.size || filter.levels.has(lvlOf(s))) &&
    (!filter.modes.size || filter.modes.has(s.mode)) &&
    (!q || [s.shipment_id, s.origin, s.destination, s.cargo, s.mode, NAMES[lvlOf(s)], s.risk.reason, ...s.legs.map(l => l.to_name)].join(" ").toLowerCase().includes(q)))
    .sort((a, b) => SORT_SHIP[sort.map][1](a, b) || a.shipment_id.localeCompare(b.shipment_id));
}
const visibleEvents = () => events.filter(e => filter.status === "all" || e.status === filter.status)
  .sort((a, b) => SORT_EVT[sort.evt][1](a, b) || a.event_id.localeCompare(b.event_id));

// Route as two lines: what has been travelled (drawn solid) and what is still ahead (drawn dotted).
function splitRoute(s, now = Date.now()) {
  const dist = (p, q) => Math.hypot(q[0] - p[0], (q[1] - p[1]) * Math.cos((p[0] + q[0]) * Math.PI / 360));
  const done = [], ahead = [];
  s.legs.forEach(leg => {
    const g = lineOf(leg), a = new Date(leg.planned_start), b = new Date(leg.planned_end);
    if (now >= b) return done.push(...g);
    if (now <= a) return ahead.push(...g);
    const seg = g.slice(1).map((q, i) => dist(g[i], q));
    let rem = (now - a) / (b - a) * seg.reduce((x, y) => x + y, 0);
    for (let i = 0; i < seg.length; i++) {
      if (rem <= seg[i] || i === seg.length - 1) {
        const k = seg[i] ? Math.min(1, rem / seg[i]) : 0;
        const p = [g[i][0] + (g[i + 1][0] - g[i][0]) * k, g[i][1] + (g[i + 1][1] - g[i][1]) * k];
        done.push(...g.slice(0, i + 1), p); ahead.push(p, ...g.slice(i + 1)); return;
      }
      rem -= seg[i];
    }
  });
  return [done, ahead];
}

// Time and money against the current plan, as the map shows them: red when it adds, green when it saves.
const timeDelta = h => !h || Math.abs(h) < 0.5 ? ["same time", ""] : [`${h > 0 ? "+" : "−"}${Math.abs(h) < 48 ? `${Math.round(Math.abs(h))} h` : `${+(Math.abs(h) / 24).toFixed(1)} days`}`, h > 0 ? "bad" : "good"];
const costDelta = (v, cur) => !v || Math.abs(v) < 0.5 ? ["no extra cost", ""] : v > 0 ? [`+${money(v, cur)}`, "bad"] : [`saves ${money(-v, cur)}`, "good"];
const kmOf = o => o.km_delta ?? o.extra_km; // the whole change in distance (extra_km is the road part a truck reroute is priced on)
const chip = ([text, tone]) => `<span class="dchip ${tone}">${esc(text)}</span>`;
function fitOption(id) { // bring the picked option into view: its own stretch for a reroute, the whole route otherwise
  const r = optRoutes?.options[id], s = ships.find(x => x.shipment_id === selected); if (!r || !s) return;
  const pts = r.same_line ? s.legs.flatMap(l => l.geometry) : r.changed.flatMap(seg => seg.geometry);
  if (pts.length) fit(L.latLngBounds(pts).pad(0.25), 8);
}
function drawOptions(s) { // the options for the open shipment, on the map: where each goes, and what it adds or saves
  const rt = optRoutes?.shipment_id === s.shipment_id ? optRoutes.options : null; if (!rt) return;
  const cur = opts.currency;
  const line = o => `<b>${esc(o.label)}</b><small>${chip(timeDelta(o.delay_hours))} ${chip(costDelta(o.extra_cost, cur))}${kmOf(o) ? ` · ${kmOf(o) > 0 ? "+" : "−"}${Math.abs(kmOf(o)).toLocaleString()} km` : ""}</small><small>arrives ${dt(rt[o.id].eta)} · risk after: ${o.resulting_risk} ${NAMES[o.resulting_risk]}${o.within_limits ? "" : " · outside your limits"}</small>${rt[o.id].from ? `<small>${esc(rt[o.id].from)} → ${esc(rt[o.id].to)}${rt[o.id].via ? `, via ${esc(rt[o.id].via)}` : ""}${rt[o.id].indicative ? " · sea part indicative" : ""}</small>` : ""}`;
  const pick = o => { pickedId = o.id; renderPlan(); draw(); fitOption(o.id); };
  const same = opts.options.filter(o => rt[o.id]?.same_line), picked = opts.options.find(o => o.id === pickedId);
  if (same.length) { // keep and reschedule use the route as it is: one hover target over it lists them
    L.polyline(s.legs.map(l => l.geometry), {color: "#000", weight: 18, opacity: 0, interactive: true})
      .bindTooltip(`<small>On the current route</small>${same.map(line).join("")}`, {sticky: true, className: "tip opt-tip"})
      .on("click", () => pick(same.find(o => o.id === pickedId) || same.find(o => o.kind !== "keep") || same[0])).addTo(shipLayer);
  }
  const alts = opts.options.filter(o => rt[o.id] && !rt[o.id].same_line);
  [...alts.filter(o => o.id !== pickedId), ...alts.filter(o => o.id === pickedId)].forEach(o => { // the picked one last, so it is on top
    const r = rt[o.id], on = o.id === pickedId, c = COLORS[o.resulting_risk] || css("--accent");
    r.changed.forEach(seg => {
      L.polyline(seg.geometry, {color: css("--surface"), weight: on ? 9 : 6, opacity: on ? 0.95 : 0.7, interactive: false}).addTo(shipLayer); // casing, so it reads over the map
      L.polyline(seg.geometry, {color: c, weight: on ? 5 : 3, opacity: on ? 1 : 0.75, dashArray: on ? (seg.mode === "ship" ? "10 7" : null) : "4 9", lineCap: "round", interactive: false}).addTo(shipLayer);
      L.polyline(seg.geometry, {color: "#000", weight: 18, opacity: 0, interactive: true})
        .bindTooltip(line(o), {sticky: true, className: "tip opt-tip"}).on("click", () => pick(o)).addTo(shipLayer);
    });
    const pts = r.changed.flatMap(seg => seg.geometry), mid = pts[Math.floor(pts.length / 2)];
    if (on) { // the picked reroute always says where it leaves the planned route and where it rejoins it
      [[r.from_point, `Leaves the planned route at ${r.from}`, "top"], [r.to_point, `Rejoins at ${r.to}`, "bottom"]].forEach(([p, text, dir]) => { if (!p) return;
        L.circleMarker(p, {radius: 7, color: css("--surface"), weight: 2.5, fillColor: c, fillOpacity: 1, interactive: false})
          .bindTooltip(esc(text), {permanent: true, direction: dir, offset: [0, dir === "top" ? -9 : 9], className: "stop-label opt-label on"}).addTo(shipLayer); });
      r.changed.slice(0, -1).forEach(seg => L.circleMarker(seg.geometry.at(-1), {radius: 5, color: css("--surface"), weight: 2, fillColor: c, fillOpacity: 1, interactive: false})
        .bindTooltip(esc(seg.to_name || ""), {permanent: true, direction: "right", offset: [8, 0], className: "stop-label"}).addTo(shipLayer));
    }
    if (mid) L.tooltip({permanent: true, direction: "top", offset: [0, -6], className: "bare-tip", interactive: false}).setLatLng(mid)
      .setContent(`<div class="delta-card${on ? " on" : ""}"><b>${esc(o.label.replace(/^Reroute /, ""))}</b><span>${chip(timeDelta(o.delay_hours))}${chip(costDelta(o.extra_cost, cur))}</span></div>`).addTo(shipLayer);
  });
  if (picked && rt[picked.id]?.same_line) { // keep or reschedule: the line does not move, the time does. Say it large, on the route.
    const pts = s.legs.flatMap(l => l.geometry), mid = pts[Math.floor(pts.length / 2)], [t, tone] = timeDelta(picked.delay_hours);
    const big = picked.kind === "keep" ? "no change" : picked.delay_days ? `+${picked.delay_days}` : t;
    L.tooltip({permanent: true, direction: "center", className: "bare-tip", interactive: false}).setLatLng(mid) // a tooltip, so it sits above the stop names
      .setContent(`<div class="big-delta ${picked.kind === "keep" ? "" : tone}"><b>${esc(big)}</b>${picked.kind !== "keep" && picked.delay_days ? `<i>day${picked.delay_days === 1 ? "" : "s"}</i>` : ""}<span>${esc(picked.label)} · arrives ${dt(rt[picked.id].eta)}</span><span>${chip(costDelta(picked.extra_cost, cur))}</span></div>`).addTo(shipLayer);
  }
}
function draw() {
  eventLayer.clearLayers(); shipLayer.clearLayers(); endLayer.clearLayers();
  const hitBySel = selected && new Set(ships.find(s => s.shipment_id === selected)?.risk.event_ids);
  const shownEvents = view === "evt" ? new Set(visibleEvents().map(e => e.event_id)) : null;
  // Disruption areas: solid outline = confirmed, dashed = suspected.
  const optim = optimising(); // then the map shows only this shipment, its disruption and the options
  $("ws").classList.toggle("optimising", optim); // the map key folds away while options are on the map
  events.forEach(e => {
    const confirmed = e.status === "confirmed", c = confirmed ? COLORS[5] : COLORS[3];
    const on = focusEvent === e.event_id || (hitBySel && hitBySel.has(e.event_id));
    if (!on && (optim || !mapShow[confirmed ? "confirmed" : "suspected"])) return;
    const dim = ((focusEvent || selected) && !on) || (shownEvents && !shownEvents.has(e.event_id));
    L.circle([e.lat, e.lon], {radius: e.radius_km * 1000, color: c, weight: on ? 2.5 : 1.5,
      dashArray: confirmed ? null : "6 6", fillColor: c, fillOpacity: dim ? 0.03 : 0.14, opacity: dim ? 0.3 : 0.9, interactive: false})
      .addTo(eventLayer);
    const icon = L.divIcon({className: "", iconSize: [22, 22],
      html: `<div class="event-icon ${e.status}${on ? " pulse" : ""}" style="background:${c};opacity:${dim ? 0.4 : 1}"></div>`});
    L.marker([e.lat, e.lon], {icon, keyboard: false, zIndexOffset: on ? 500 : -100})
      .bindTooltip(`<b>${esc(cap(e.type))} · ${esc(e.location)}</b><small>${esc(cap(e.status))}${e.is_fixture ? " · sample" : ""} · ${esc(evWhen(e)[0])}</small><small>${e.shipments.length} shipment${e.shipments.length === 1 ? "" : "s"} hit</small>`,
        {direction: "top", offset: [0, -10], className: "tip"})
      .on("click", () => openEvent(e.event_id)).addTo(eventLayer);
  });
  drawWhatIf();
  if (!optim) drawPlanned();
  if (view === "new") return drawPlanner();
  if (!optim && (view === "flt" || mapShow.depots)) drawFleet(view === "flt");
  if (view === "flt") return;
  if (!optim && mapShow.customer) customers.forEach(p => L.marker([p.lat, p.lon], {icon: L.divIcon({className: "", iconSize: [18, 18], html: glyph("customer")}), keyboard: false, zIndexOffset: -200})
    .bindTooltip(`<b>${esc(p.name)}</b><small>Customer site${p.customer ? ` · ${esc(p.customer)}` : ""}</small><small>Click to plan a delivery here</small>`, {direction: "top", offset: [0, -8], className: "tip"})
    .on("click", () => deliverTo(p)).addTo(shipLayer));
  const show = new Set(visible().map(s => s.shipment_id));
  const evHit = focusEvent && new Set(events.find(e => e.event_id === focusEvent)?.shipments.map(x => x.shipment_id));
  ships.forEach(s => {
    const id = s.shipment_id, lvl = lvlOf(s), c = COLORS[lvl], sel = selected === id;
    const strong = sel || hoverId === id || (!selected && evHit && evHit.has(id));
    const faded = selected ? !sel : hoverId ? hoverId !== id : evHit ? !evHit.has(id) : !show.has(id);
    if (!sel && (optim || !mapShow[s.mode] || !mapShow["lvl" + lvl])) return; // hidden by the map key, or not the shipment being worked on
    if (s.legs.length) {
      const [done, ahead] = splitRoute(s), o = faded ? 0.1 : strong ? 1 : 0.7, w = strong ? 3.5 : 2;
      if (sel) L.polyline([...done, ...ahead], {color: c, weight: 11, opacity: 0.18, interactive: false}).addTo(shipLayer); // glow
      if (done.length > 1 && (sel || mapShow.done)) L.polyline(done, {color: c, weight: w, opacity: o, interactive: false}).addTo(shipLayer);
      if (ahead.length > 1 && (sel || mapShow.ahead)) L.polyline(ahead, {color: c, weight: w, opacity: o, dashArray: "2 8", lineCap: "round", interactive: false}).addTo(shipLayer);
    }
    if (!sel && s.legs.length && mapShow.ends) { // origin and destination, filled in the shipment's risk colour (zoomed in only, see endLayer)
      const a = s.legs[0], b = s.legs[s.legs.length - 1], op = faded ? 0.25 : 1;
      [[a.from_name, a.from_lat, a.from_lon, "Origin"], [b.to_name, b.to_lat, b.to_lon, "Destination"]]
        .forEach(([n, la, lo, what]) => L.circleMarker([la, lo], {radius: 4.5, color: css("--surface"), weight: 2, opacity: op, fillColor: c, fillOpacity: op})
          .bindTooltip(`<b>${esc(n)}</b><small>${what} · ${esc(id)} · ${esc(riskLabel(lvl))}</small>`, {direction: "top", offset: [0, -5], className: "tip"})
          .on("click", () => select(id)).addTo(endLayer));
    }
    if (sel && s.legs.length) { // every stop on the route, named
      const stops = [[s.legs[0].from_name, s.legs[0].from_lat, s.legs[0].from_lon],
        ...s.legs.map(l => [l.to_name, l.to_lat, l.to_lon])];
      stops.forEach(([n, la, lo]) => L.circleMarker([la, lo], {radius: 4.5, color: css("--surface"), weight: 2, fillColor: c, fillOpacity: 1})
        .bindTooltip(esc(n), {permanent: true, direction: "top", offset: [0, -6], className: "stop-label"}).addTo(shipLayer));
    }
    if (sel && optim) drawOptions(s); // after the stop names, so what the options say sits on top of them
    const pos = position(s);
    if (pos) {
      const icon = L.divIcon({className: "", iconSize: [28, 28], html:
        `<div class="shipment-icon${lvl === 2 || lvl === 3 ? " dark" : ""}${strong ? " big" : ""}" style="background:${c};opacity:${faded ? 0.25 : 1}">${svgIcon(s.mode)}</div>`});
      L.marker(pos, {icon, keyboard: false, zIndexOffset: strong ? 1000 : lvl * 10})
        .bindTooltip(`<b>${esc(id)}</b> · ${esc(riskLabel(lvl))}<small>${esc(s.origin)} → ${esc(s.destination)}</small><small>${esc(s.risk.reason)}</small><small>ETA ${dt(s.eta)}</small>`,
          {direction: "top", offset: [0, -14], className: "tip"})
        .on("click", () => select(id)).addTo(shipLayer);
    }
  });
}

// ---- map key: every kind of mark on the map, always on screen (top right of the map, collapsible) ----
function renderLegend() {
  const tick = key => el("input", {type: "checkbox", checked: mapShow[key], ariaLabel: "Show on the map", onchange: e => { mapShow[key] = e.target.checked; saveShow(); renderLegend(); draw(); }});
  const row = (mark, label, key) => el("li", {}, el("label", {className: "lg-row" + (key && !mapShow[key] ? " off" : "")}, key ? tick(key) : el("span", {className: "lg-nobox"}),
    el("span", {className: "lg-mark", innerHTML: mark}), el("span", {}, label)));
  const ship = (mode, color = css("--risk-0")) => `<div class="shipment-icon mini" style="background:${color}">${svgIcon(mode)}</div>`;
  const line = dash => `<svg viewBox="0 0 26 8" aria-hidden="true"><path d="M2 4h22" stroke="var(--text)" stroke-width="2.5" stroke-linecap="round"${dash ? ` stroke-dasharray="${dash}"` : ""} fill="none"/></svg>`;
  const sec = (title, items) => el("div", {className: "lg-sec"}, el("h4", {}, title), el("ul", {}, items));
  const off = SHOW_KEYS.filter(k => !mapShow[k]).length;
  $("legend-body").replaceChildren(
    el("p", {className: "lg-hint"}, off ? `${off} hidden. ` : "Untick to hide from the map. ",
      off ? el("button", {className: "textbtn", onclick: () => { SHOW_KEYS.forEach(k => mapShow[k] = true); saveShow(); renderLegend(); draw(); }}, "Show everything") : ""),
    sec("Places", [row(glyph("warehouse"), "Our warehouse", "warehouse"), row(`<div class="depot-icon mini">${svgIcon("truck")}<b>2</b></div>`, "Our trucks free at a depot", "depots"),
      row(glyph("customer"), "Customer site", "customer"), row(glyph("port"), "Port", "port"), row(glyph("airport"), "Airport", "airport")]),
    sec("Shipments", [row(ship("ship"), "Ship", "ship"), row(ship("truck"), "Truck", "truck"), row(ship("plane"), "Plane", "plane")]),
    el("div", {className: "lg-sec"}, el("h4", {}, "Risk (shipment colour)"), el("ol", {className: "lg-risk"},
      [1, 2, 3, 4, 5].map(n => el("li", {}, el("label", {className: "lg-row" + (mapShow["lvl" + n] ? "" : " off")}, tick("lvl" + n), el("i", {style: `background:${COLORS[n]}`}), `Level ${n}: ${NAMES[n]}`))))),
    sec("Disruptions", [row(`<div class="event-icon confirmed mini" style="background:${COLORS[5]}"></div>`, "Confirmed", "confirmed"),
      row(`<div class="event-icon suspected mini" style="background:${COLORS[3]}"></div>`, "Suspected", "suspected"),
      row(`<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.5" fill="${COLORS[5]}33" stroke="${COLORS[5]}" stroke-width="1.5"/></svg>`, "Area affected")]),
    sec("Routes", [row(line(null), "Travelled", "done"), row(line("1 5"), "Still to go", "ahead"),
      row(`<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="4.5" fill="${css("--risk-0")}" stroke="var(--surface)" stroke-width="2"/></svg>`, "Origin / destination (zoom in)", "ends")]),
    el("p", {className: "lg-hint"}, "Warehouses, ports and airports show in Plan a shipment. An open shipment is always shown."));
}
let legendOpen = true;
try { legendOpen = localStorage.getItem("portshift.legend") !== "closed"; } catch { /* default open */ } // open unless the operator closed it
if (matchMedia("(max-width: 600px)").matches) legendOpen = false; // phones: start collapsed so the map is visible
function setLegend(open) {
  legendOpen = open; $("legend").classList.toggle("closed", !open); $("legend-toggle").setAttribute("aria-expanded", String(open));
  $("legend-toggle").title = open ? "Hide the map key" : "Show the map key";
  try { localStorage.setItem("portshift.legend", open ? "open" : "closed"); } catch { /* not stored */ }
}
$("legend-toggle").onclick = () => setLegend(!legendOpen);

// ---- top bar, heading and risk legend ----
function renderChrome(s) {
  const toggle = i => { filter.levels.has(i) ? filter.levels.delete(i) : filter.levels.add(i); refresh(); };
  // Filters live with the list they filter, under search and sort: one row for risk, one for mode.
  const row = (label, kids) => el("div", {className: "frow", role: "group", ariaLabel: `Filter by ${label.toLowerCase()}`}, kids);
  const any = filter.levels.size || filter.modes.size || filter.q;
  $("levels").replaceChildren(
    row("Risk", [1, 2, 3, 4, 5, ...(s.levels["0"] ? [0] : [])].map(i => el("button", {
      className: "chip", ariaPressed: String(filter.levels.has(i)), disabled: !s.levels[String(i)],
      ariaLabel: `${NAMES[i]}: ${s.levels[String(i)]} shipments`, title: i ? `${i} ${NAMES[i]}: ${MEANING[i]}` : "Not scored yet", onclick: () => toggle(i),
    }, el("b", {}, el("span", {className: "dot", style: `background:${COLORS[i]}`}), String(s.levels[String(i)])), el("small", {}, NAMES[i])))),
    row("Mode", [...Object.keys(MODE_ICONS).filter(m => ships.some(x => x.mode === m)).map(m => el("button", {
      className: "chip", ariaPressed: String(filter.modes.has(m)), title: `Show ${FREIGHT[m].toLowerCase()} only`,
      onclick: () => { filter.modes.has(m) ? filter.modes.delete(m) : filter.modes.add(m); refresh(); },
    }, el("span", {className: "micon", innerHTML: svgIcon(m)}), cap(m), el("strong", {}, String(ships.filter(x => x.mode === m).length))))]),
    el("div", {className: "fclear"}, el("span", {className: "note"}, any ? `Showing ${visible().length} of ${ships.length} shipments` : `Showing all ${ships.length} shipments`),
      el("button", {className: "btn small clearall", disabled: !any, title: any ? "Reset risk, mode and search" : "No filter is on",
        onclick: clearFilters}, "Clear all filters")));
  $("n-map").textContent = `${s.shipments} active shipments`;
  const hitting = events.filter(e => e.shipments.length && !evOver(e)).length;
  $("n-evt").textContent = hitting; $("n-evt").hidden = !hitting;
  const live = s.source === "databricks";
  const found = s.events.live || 0; // events from a live search, shown over the demo fleet
  const mixed = found && s.events.sample; // live and sample events side by side (PORTSHIFT_SAMPLE_EVENTS=keep)
  $("live").textContent = found ? (mixed ? `${found} live · ${s.events.sample} sample` : "Live sources") : "Sample disruptions";
  $("live").title = found ? `${found} disruption${found === 1 ? "" : "s"} from live web search, each with its sources.${mixed ? " Sample events are marked sample." : ""}`
    : "No live search has run yet: the disruptions shown are samples, each marked sample. Ask PortShifter to check for disruptions.";
  $("live").className = "live" + (found ? "" : " sample");
  $("fresh").textContent = s.evidence.newest_retrieved_at ? `Sources checked ${span(s.evidence.newest_retrieved_at)} ago` : "No sources yet";
  const urgent = s.levels["4"] + s.levels["5"], exposure = events.reduce((t, e) => t + e.exposure, 0);
  const [kicker, title, sub] =
    view === "evt" ? ["Watchlist", "Possible disruptions", `${s.events.confirmed} confirmed · ${s.events.suspected} suspected · ${hitting} hitting shipments`]
    : view === "pln" ? ["Planning", "Planned shipments", planned.length ? `${planned.length} approved plan${planned.length === 1 ? "" : "s"} · tentative, nothing booked` : "Approved plans appear here"]
    : view === "ins" ? ["Statistics", "Insights", "Demo fleet, current data"]
    : view === "new" ? ["Planning", "Plan a shipment", "Send warehouse stock or test any cargo · suggested routes · estimates"]
    : view === "rat" ? ["Costing", "My rates", "Your contract rates replace the defaults in every estimate"]
    : view === "flt" ? ["Resources", "Fleet", fleetView ? `${fleetView.counts.available} available · ${fleetView.counts.allocated} allocated · ${fleetView.counts.in_transit} in transit · ${fleetView.counts.off_road} off road` : "Your vehicles and booked capacity"]
    : ["Global operations", "Fleet overview", `${s.shipments} shipments · ${urgent} require attention`];
  $("view-kicker").textContent = kicker; $("view-title").textContent = title; $("view-sub").textContent = sub;
  const f = $("focus"); f.hidden = !selected;
  if (selected) f.replaceChildren("Focused route · other routes dimmed", el("button", {className: "btn small", onclick: deselect}, "Show all routes (Esc)"));
}

function clearFilters() { filter.levels.clear(); filter.modes.clear(); filter.q = ""; $("q").value = ""; refresh(); }

const vehicle = (mode, lvl) => el("span", {className: "veh" + (lvl === 2 || lvl === 3 ? " dark" : ""), style: `--c:${COLORS[lvl]}`, innerHTML: svgIcon(mode)});
const hoverer = v => () => { if (hoverId !== v) { hoverId = v; draw(); } };

// ---- live operations: every shipment, sorted the way the operator chose ----
// The three shipments to deal with first: confirmed disruptions only, soonest first, then the dearest to wait out.
function needsNow() {
  const top = ships.filter(s => lvlOf(s) >= 4 && s.impact_at).sort((a, b) =>
    Math.max(Date.now(), far(a.impact_at)) - Math.max(Date.now(), far(b.impact_at)) || lvlOf(b) - lvlOf(a) || (b.wait_out?.cost || 0) - (a.wait_out?.cost || 0)).slice(0, 3);
  if (!top.length || filter.levels.size || filter.modes.size || filter.q) return null;
  return el("li", {className: "now"}, el("div", {className: "nhead"}, el("span", {className: "eyebrow"}, "Needs you now"), el("span", {className: "note"}, "soonest confirmed disruption first")),
    ...top.map((s, i) => el("button", {className: "need", style: `--c:${COLORS[lvlOf(s)]}`, onclick: () => { ptab = "plan"; select(s.shipment_id); }, onmouseenter: hoverer(s.shipment_id), onmouseleave: hoverer(null)},
      el("span", {className: "ix"}, String(i + 1)),
      el("span", {className: "t"}, s.shipment_id, el("em", {}, new Date(s.impact_at) > Date.now() ? `disruption in ${span(s.impact_at)}` : "disruption under way")),
      el("span", {className: "s"}, s.risk.reason),
      el("span", {className: "s"}, s.wait_out ? `About ${money(s.wait_out.cost, s.wait_out.currency)} to wait out (estimate)` : "Open the options"))));
}

function renderList() {
  const rows = visible(), first = needsNow();
  $("list").replaceChildren(...(first ? [first] : []), ...rows.map(s => {
    const lvl = lvlOf(s), id = s.shipment_id;
    const when = !s.impact_at ? "" : new Date(s.impact_at) > Date.now() ? ` · event in ${span(s.impact_at)}` : " · event under way";
    return el("li", {}, el("button", {className: "row", style: `--c:${COLORS[lvl]}`, ariaCurrent: String(selected === id), onclick: () => select(id),
      onmouseenter: hoverer(id), onmouseleave: hoverer(null), onfocus: hoverer(id), onblur: hoverer(null)},
      vehicle(s.mode, lvl),
      el("span", {className: "t"}, id, el("em", {}, el("i", {}), riskLabel(lvl))),
      el("span", {className: "s"}, `${s.origin} → ${s.destination} · ETA ${day(s.eta)}${when}`),
      el("span", {className: "why"}, s.risk.reason)));
  }));
  if (!rows.length) $("list").append(el("li", {className: "empty"}, "No shipments match. ",
    el("button", {className: "textbtn", onclick: clearFilters}, "Clear all filters")));
}

// ---- possible disruptions: one card per disruption with the shipments it hits ----
function openEvent(id) { // opening a disruption opens the sidebar on the shipment it hits hardest
  const e = events.find(x => x.event_id === id); if (!e) return;
  if (view === "new") { // while planning, a disruption just shows where it is
    return fit(L.latLng(e.lat, e.lon).toBounds(Math.max(e.radius_km, 150) * 5000), 7);
  }
  focusEvent = id; if (view !== "evt") tab("evt");
  if (e.shipments.length) return select(e.shipments[0].shipment_id, id);
  selected = null; detail = null; refresh();
  fit(L.latLng(e.lat, e.lon).toBounds(Math.max(e.radius_km, 150) * 5000), 7);
}

function renderEvents() {
  $("evt-filter").replaceChildren(...[["all", "All"], ["confirmed", "Confirmed"], ["suspected", "Suspected"]].map(([k, label]) =>
    el("button", {type: "button", ariaPressed: String(filter.status === k), onclick: () => { filter.status = k; refresh(); }}, label)));
  const rows = visibleEvents();
  $("evt").replaceChildren(...rows.map(e => {
    const open = focusEvent === e.event_id, confirmed = e.status === "confirmed", [when, urgent] = evWhen(e);
    return el("div", {className: "dis" + (open ? " open" : "")},
      el("button", {ariaExpanded: String(open), onclick: () => openEvent(e.event_id)},
        el("span", {className: `mark ${e.status}`, style: `background:${confirmed ? COLORS[5] : COLORS[3]}`}),
        el("span", {className: "t"}, `${cap(e.type)} · ${e.location}`),
        el("span", {}, el("span", {className: `badge badge-${e.status}`}, e.status), " ", e.is_fixture ? el("span", {className: "badge badge-sample"}, "sample") : ""),
        el("span", {className: "s"}, el("span", {className: urgent ? "urgent" : ""}, when), ` · ${day(e.window_start)} – ${day(e.window_end)}`),
        el("span", {className: "s"}, el("b", {}, `${e.shipments.length} shipment${e.shipments.length === 1 ? "" : "s"}`),
          e.exposure ? ` · about ${money(e.exposure)} to wait out (estimate)` : " · no shipment hit"),
        (() => { const shared = e.shipments.filter(x => x.wait_out && events.filter(o => o.shipments.some(y => y.shipment_id === x.shipment_id)).length > 1).map(x => x.shipment_id);
          return shared.length ? el("span", {className: "s shared"}, `${shared.join(", ")} ${shared.length === 1 ? "is" : "are"} also under other disruptions and counted once in the fleet total (Insights), so these cards do not add up.`) : ""; })()),
      e.shipments.length ? el("div", {className: "hits"}, e.shipments.map(x => {
        const s = ships.find(y => y.shipment_id === x.shipment_id) || {};
        return el("button", {className: "hit", ariaCurrent: String(selected === x.shipment_id), title: `Open ${x.shipment_id}`,
          onclick: () => { focusEvent = e.event_id; select(x.shipment_id, e.event_id); },
          onmouseenter: hoverer(x.shipment_id), onmouseleave: hoverer(null)},
          el("span", {className: "dot", style: `background:${COLORS[x.level || 0]}`}),
          el("span", {}, el("b", {}, x.shipment_id), ` ${s.origin || ""} → ${s.destination || ""}`),
          el("span", {}, x.wait_out ? money(x.wait_out.cost, x.wait_out.currency) : ""));
      })) : "");
  }));
  if (!rows.length) $("evt").append(el("p", {className: "empty"}, "No disruptions match this filter."));
}

// ---- shipment sidebar: Shipment details, Ask agent, Options ----
async function select(id, fromEvent = null) {
  if (whatIf?.state === "done") { // the shipment panel shows real data, so in a what-if a click only points the route out
    hoverId = id; draw(); const s = ships.find(x => x.shipment_id === id);
    if (s?.legs.length) fit(s.legs.flatMap(l => l.geometry), 7); return; }
  hoverId = null; focusEvent = fromEvent; selected = id; detail = null; opts = null; pickedId = null; optRoutes = null;
  if (view === "ins" || view === "new" || view === "pln" || view === "rat" || view === "flt") tab("map");
  refresh();
  const d = await getJSON(`/api/shipments/${id}`);
  if (selected !== id) return;
  detail = d; renderDetail();
  const pts = d.legs.flatMap(l => l.geometry);
  if (pts.length) fit(pts);
  if (ptab === "plan") loadOptions();
}
function deselect() { selected = null; detail = null; focusEvent = null; refresh(); map.invalidateSize(); if (brief) renderBriefing(); }

function citeRow(v, i, sample) {
  return el("a", {className: "cite", href: safeHref(v.url), target: "_blank", rel: "noopener noreferrer",
    title: v.published_at ? `Published ${dt(v.published_at)}. Opens the source.` : "Publication date unknown. Opens the source."},
    el("span", {className: "ix"}, String(i + 1).padStart(2, "0")), el("b", {}, v.title),
    sample ? el("span", {className: "badge badge-sample"}, "sample") : el("span", {}),
    el("small", {}, `${v.domain}${v.is_official ? " · official" : ""} · ${ago(v.retrieved_at)}`),
    el("span", {className: "claim"}, v.claim));
}

function riskCard(e) {
  return el("div", {className: "risk-card"},
    el("div", {className: "rhead"}, el("span", {className: "eyebrow dim"}, "Disruption"),
      el("span", {}, el("span", {className: `badge badge-${e.status}`}, e.status), " ", e.is_fixture ? el("span", {className: "badge badge-sample"}, "sample") : "")),
    el("b", {className: "title"}, `${cap(e.type)} · ${e.location}`),
    el("p", {}, e.summary),
    el("p", {className: "note"}, `${dt(e.window_start)} to ${dt(e.window_end)} · ${evWhen(e)[0].toLowerCase()}`),
    el("div", {className: "basis"}, el("span", {}, "Evidence"), el("b", {}, `${cap(e.status)} · ${e.basis.text}`)));
}

// The journey as a line of stops. Passed stops are greyed; the current position sits between them.
// With delayHours, every stop not yet reached shows its planned time struck through and the new time.
function journey(d, delayHours = null) {
  const now = Date.now(), legs = d.legs, items = [];
  const shifted = t => new Date(+new Date(t) + (delayHours || 0) * 36e5).toISOString();
  const time = (t, passed, verb) => passed || !delayHours ? el("span", {className: "time"}, `${verb} ${dt(t)}`)
    : el("span", {className: "time"}, `${verb} `, el("s", {}, dt(t)), " → ", el("span", {className: "new"}, dt(shifted(t))));
  const here = text => el("li", {className: "here"}, el("b", {}, "Now"), el("span", {className: "time"}, text));
  if (!legs.length) return el("ol", {className: "journey"});
  const start = +new Date(legs[0].planned_start);
  items.push(el("li", {className: now >= start ? "passed" : ""}, el("b", {}, legs[0].from_name), time(legs[0].planned_start, now >= start, now >= start ? "Departed" : "Departs")));
  if (now < start) items.push(here(`Not departed yet · leaves in ${span(legs[0].planned_start)}`));
  legs.forEach((l, i) => {
    const a = +new Date(l.planned_start), b = +new Date(l.planned_end), passed = now >= b, last = i === legs.length - 1;
    if (now >= a && now < b) items.push(here(`${Math.round(100 * (now - a) / (b - a))}% of the way from ${l.from_name} to ${l.to_name}`));
    const names = (l.event_ids || []).map(x => d.events.find(e => e.event_id === x)?.location || x);
    items.push(el("li", {className: [passed ? "passed" : "", names.length && !passed ? "disrupted" : "", last ? "end" : ""].join(" ").trim()},
      el("b", {}, l.to_name), time(l.planned_end, passed, passed ? "Arrived" : last ? "Arrives" : "ETA"),
      names.length && !passed ? el("span", {className: "flag"}, `Disruption on this leg: ${names.join(", ")}`) : ""));
    const next = legs[i + 1];
    if (next && now >= b && now < +new Date(next.planned_start)) items.push(here(`Waiting at ${l.to_name} · leaves in ${span(next.planned_start)}`));
  });
  return el("ol", {className: "journey"}, items);
}

function renderDetail() {
  const s = ships.find(x => x.shipment_id === selected);
  $("detail").hidden = !selected; $("ws").classList.toggle("has-detail", !!selected);
  if (botOpen) placeBot(); // the assistant window steps aside when the shipment panel opens
  if (!s) return;
  const d = detail, lvl = lvlOf(s), now = Date.now();
  $("detail").style.setProperty("--hit", COLORS[lvl]);
  const ev = focusEvent && events.find(e => e.event_id === focusEvent);
  $("detail-head").replaceChildren(
    el("div", {}, el("div", {className: "eyebrow"}, el("span", {className: "dot", style: `background:${COLORS[lvl]}`}), lvl ? `Risk ${lvl} · ${NAMES[lvl]}` : NAMES[0]),
      el("h2", {}, s.shipment_id), el("p", {}, `${s.origin} → ${s.destination} · ${FREIGHT[s.mode] || cap(s.mode)}`)),
    el("button", {className: "iconbtn", ariaLabel: "Close panel", title: "Close (Esc)", onclick: deselect, innerHTML: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/></svg>'}));
  document.querySelector(".ctx")?.remove();
  if (ev && ev.shipments.length > 1) $("detail-head").after(el("div", {className: "ctx"}, el("b", {}, `${cap(ev.type)} · ${ev.location}`), "hits",
    ...ev.shipments.map(x => el("button", {ariaCurrent: String(x.shipment_id === selected), onclick: () => select(x.shipment_id, ev.event_id)}, x.shipment_id))));
  for (const t of ["details", "chat", "plan"]) $("ptab-" + t).setAttribute("aria-selected", String(ptab === t));
  $("panel").hidden = ptab !== "details"; $("chat-host").hidden = ptab !== "chat"; $("plan").hidden = ptab !== "plan";
  if (!d) { $("panel").replaceChildren(el("p", {className: "empty"}, "Loading…")); return; }
  const cur = d.legs.find(l => now >= new Date(l.planned_start) && now <= new Date(l.planned_end));
  const first = d.legs[0] ? +new Date(d.legs[0].planned_start) : now, eta = +new Date(d.eta);
  const status = now < first ? "Not departed" : now > eta ? "Arrived" : cur ? `In transit to ${cur.to_name}` : "Waiting at a stop";
  const pct = Math.round(100 * Math.min(1, Math.max(0, (now - first) / (eta - first || 1))));
  const done = decisions.filter(x => x.shipment_id === selected).at(-1);
  let n = 0;
  $("panel").replaceChildren(
    done ? el("div", {className: "submitted"}, el("b", {}, `Submitted: ${done.label}`),
      `${done.extra_cost ? "+" + money(done.extra_cost) : "No extra cost"} · ${dt(done.submitted_at)} · tentative, nothing is booked`) : "",
    el("dl", {className: "facts"},
      el("div", {}, el("dt", {}, "Carrying"), el("dd", {}, d.cargo)),
      el("div", {}, el("dt", {}, "Current status"), el("dd", {}, status))),
    el("h3", {}, "Risk"),
    ...(d.events.length ? d.events.map(riskCard) : [el("div", {className: "risk-card none"},
      el("span", {className: "eyebrow dim"}, lvl ? "No active disruption" : "Not scored"), el("p", {}, d.risk.reason))]),
    lvl ? el("div", {className: "why-level"}, el("b", {}, `Why level ${lvl} · ${NAMES[lvl]}`), d.risk.reason,
      el("div", {className: "note"}, `Level ${lvl} means: ${MEANING[lvl]}`)) : "",
    d.risk_check ? el("p", {className: "warn"}, "Rule check: " + d.risk_check) : "",
    el("h3", {}, "Journey", el("span", {}, "planned times, demo fleet")),
    el("div", {className: "box", style: "margin-top:0"},
      el("div", {className: "bhead"}, eta > now ? `Arrives in ${span(d.eta)}` : "Arrived", el("span", {}, `${pct}% of the journey · ETA ${dt(d.eta)}`)),
      el("div", {className: "progress"}, el("i", {style: `width:${pct}%`})),
      journey(d)),
    el("h3", {}, "Sources and citations", el("span", {}, `${d.evidence.length} source${d.evidence.length === 1 ? "" : "s"}`)),
    ...(d.evidence.length ? d.evidence.map(v => citeRow(v, n++, d.events.find(e => e.event_id === v.event_id)?.is_fixture))
      : [el("p", {className: "note"}, "No disruption on this route, so there is nothing to cite.")]),
    el("div", {className: "cta"},
      el("button", {className: "btn primary", onclick: () => setPtab("plan")}, "See the options"),
      el("button", {className: "btn", onclick: () => setPtab("chat")}, "Ask PortShifter about this")));
  if (ptab === "plan") renderPlan();
}
function setPtab(t) {
  ptab = t; placeChat(); renderDetail(); draw();
  if (t === "chat") $("msg").focus();
  if (t === "plan" && !opts) loadOptions();
}
for (const t of ["details", "chat", "plan"]) $("ptab-" + t).onclick = () => setPtab(t);

// ---- reschedule: say what matters, see the options, see the new schedule, submit ----
function savePrefs() { try { localStorage.setItem("portshift.prefs", JSON.stringify({preset, limits})); } catch { /* not stored */ } }
function setPreset(k) { preset = k; limits = {...PRESETS[k].prefs}; savePrefs(); placeChat(); loadOptions(); reoffer(); }
function setLimit(patch) { preset = "custom"; limits = {...limits, ...patch}; savePrefs(); placeChat(); loadOptions(); reoffer(); }

// The controls for what the operator accepts: a preset, the risk level, and the cost and delay limits.
// Used in the Options tab and, opened from the chip, inside Ask agent.
function limitsEditor(idp = "") {
  const range = el("input", {type: "range", id: idp + "lim-cost", min: 0, max: COST_MAX, step: 250, value: limits.max_extra_cost ?? COST_MAX,
    oninput: e => { $(idp + "lim-cost-val").textContent = +e.target.value >= COST_MAX ? "No limit" : money(+e.target.value); },
    onchange: e => setLimit({max_extra_cost: +e.target.value >= COST_MAX ? null : +e.target.value})});
  return [
    el("div", {className: "presets", role: "group", ariaLabel: "Presets"}, Object.entries(PRESETS).map(([k, p]) =>
      el("button", {className: "preset", type: "button", ariaPressed: String(preset === k), onclick: () => setPreset(k)}, el("b", {}, p.label), el("span", {}, p.desc)))),
    el("div", {className: "limits-box"},
      el("div", {className: "field"}, el("span", {className: "lab"}, "Risk I accept"),
        el("div", {className: "seg", role: "group", ariaLabel: "Highest risk level accepted after the change"}, [1, 2, 3, 4, 5].map(i => el("button", {type: "button",
          className: i <= limits.max_risk ? "in" : "off", style: `--c:${COLORS[i]}`, ariaPressed: String(i === limits.max_risk), title: `${NAMES[i]}: ${ACCEPT[i]}`,
          onclick: () => setLimit({max_risk: i})}, String(i))))),
      el("div", {className: "meaning", style: "margin-top:8px"}, el("b", {}, `Up to ${limits.max_risk} · ${NAMES[limits.max_risk]}. `), ACCEPT[limits.max_risk],
        el("details", {}, el("summary", {}, "What each level means"),
          el("ul", {}, [1, 2, 3, 4, 5].map(i => el("li", {className: i <= limits.max_risk ? "" : "no"},
            el("span", {className: "dot", style: `background:${COLORS[i]}`}), el("b", {}, ` ${i} ${NAMES[i]} `), ACCEPT[i],
            el("i", {}, i <= limits.max_risk ? " Accepted." : " Not accepted.")))))),
      el("details", {className: "more", open: !!idp}, el("summary", {}, `Cost and delay limits: ${limits.max_extra_cost == null ? "any cost" : "≤ " + money(limits.max_extra_cost)}, ${limits.max_delay_hours == null ? "any delay" : "≤ " + hours(limits.max_delay_hours)}`),
        el("div", {className: "field"}, el("label", {htmlFor: idp + "lim-cost"}, "Max extra cost"),
          el("div", {}, range, el("div", {className: "val", id: idp + "lim-cost-val"}, limits.max_extra_cost == null ? "No limit" : money(limits.max_extra_cost)))),
        el("div", {className: "field"}, el("label", {htmlFor: idp + "lim-delay"}, "Max delay"),
          el("select", {id: idp + "lim-delay", onchange: e => setLimit({max_delay_hours: e.target.value === "" ? null : +e.target.value})},
            DELAYS.map(([h, label]) => el("option", {value: h ?? "", selected: (h ?? null) === (limits.max_delay_hours ?? null)}, label))))))];
}

function recommend(o) { // which option the chosen setting points at
  const pool = o.options.filter(x => x.within_limits);
  const from = pool.length ? pool : o.options;
  if (preset === "low_risk") return [...from].sort((a, b) => a.resulting_risk - b.resulting_risk || a.delay_hours - b.delay_hours || a.extra_cost - b.extra_cost)[0].id;
  if (preset === "low_cost") return [...from].sort((a, b) => a.extra_cost - b.extra_cost || a.resulting_risk - b.resulting_risk)[0].id;
  return o.recommended_id || from[0].id;
}

async function loadOptions() {
  if (!selected) return;
  const id = selected;
  try {
    const o = await postJSON("/api/options", {shipment_id: id, preferences: limits});
    if (selected !== id) return;
    opts = o; pickedId = recommend(o);
    optRoutes = null;
    postJSON("/api/options/routes", {shipment_id: id, preferences: limits}).then(r => { if (selected !== id) return; optRoutes = r; draw();
      if (optimising()) { const pts = [...ships.find(x => x.shipment_id === id).legs.flatMap(l => l.geometry), ...Object.values(r.options).flatMap(x => x.changed.flatMap(seg => seg.geometry))];
        if (pts.length) fit(L.latLngBounds(pts), 7); } }).catch(() => {});
  } catch (err) { opts = {error: err.message, options: []}; }
  draw();
  if (ptab === "plan") renderPlan();
}

const costText = (v, c) => v > 0 ? `↑ +${money(v, c)}` : v < 0 ? `↓ −${money(-v, c)} cheaper` : "No extra cost";
const optFacts = (o, c) => `${costText(o.extra_cost, c)} · ${o.delay_hours ? "+" + hours(o.delay_hours) : "no delay"} · risk after ${o.resulting_risk} ${NAMES[o.resulting_risk] || ""}`;

// How a cost was worked out: one row per charge with its arithmetic and where the rate came from.
// The server sends the lines (app/costing.py); nothing is recomputed here.
const SOURCE = {default: ["Default rate", ""], operator: ["Your rate", ""], shipment: ["Shipment terms", ""], none: ["No rate", ""]};
function costLine(l, cur) {
  const [name, extra] = SOURCE[l.rate_source] || SOURCE.default;
  return el("div", {className: "cl"}, el("b", {}, l.label), el("span", {className: "amt"}, money(l.amount, cur)),
    el("small", {}, l.formula),
    el("small", {className: "src"}, el("span", {className: `badge src-${l.rate_source}`}, l.rate_source === "operator" && l.partner ? `${name} · ${l.partner}` : name),
      [extra, l.note].filter(Boolean).join(" · ")));
}
function costTable(groups, total, cur, note) { // groups: [[heading or null, lines]]
  return el("div", {className: "costs"},
    el("div", {className: "chead"}, "How this cost was worked out", el("span", {}, note || COST_NOTE)),
    ...groups.flatMap(([head, lines]) => [head ? el("div", {className: "cgroup"}, head) : "", ...lines.map(l => costLine(l, cur))]),
    el("div", {className: "ctotal"}, "Total", el("b", {}, money(total, cur))),
    el("div", {className: "cfoot"}, "Rates are looked up, never generated. ",
      el("button", {className: "textbtn", onclick: () => $("tab-rat").click()}, "Use your own rates →")));
}

async function submit(option) {
  const id = selected;
  const row = await postJSON("/api/decisions", {shipment_id: id, option, preset});
  decisions.push(row); renderDetail(); if (summary) renderInsights(summary);
  return row;
}

let noticeOpen = false;
function noticeText(d, picked, cur) {
  const eta = new Date(+new Date(d.eta) + picked.delay_hours * 36e5).toISOString();
  const lines = [`Subject: ${d.shipment_id} ${d.origin} to ${d.destination}: ${picked.kind === "keep" ? "no change to plan" : "revised plan"}`, "",
    `Shipment ${d.shipment_id} (${d.cargo}), ${d.origin} to ${d.destination}.`,
    ...d.events.map(e => `${cap(e.type)} at ${e.location}, ${e.status} (${e.basis.text}): ${e.summary} Window ${dt(e.window_start)} to ${dt(e.window_end)}.`),
    picked.kind === "keep" ? `We are keeping the current plan. Planned arrival stays ${dt(d.eta)}.`
      : `Proposed change: ${picked.label.toLowerCase()}. Planned arrival moves from ${dt(d.eta)} to ${dt(eta)}.`,
    picked.extra_cost ? `Estimated extra cost: ${money(picked.extra_cost, cur)} (${picked.cost_note || COST_NOTE}; an estimate, not a quote).` : "",
    "This is a proposal. Nothing has been booked or changed with the carrier.", "",
    d.evidence.length ? "Sources:" : "", ...d.evidence.map(v => `- ${v.title} (${v.domain}, retrieved ${dt(v.retrieved_at)}): ${v.url}`),
    d.events.some(e => e.is_fixture) ? "Note: these are sample events on a demo fleet." : ""];
  return lines.filter((l, i) => l !== "" || lines[i - 1] !== "").join("\n").trim();
}

function renderPlan() {
  const d = detail, host = $("plan");
  if (!d) return host.replaceChildren(el("p", {className: "empty"}, "Loading…"));
  const wasOpen = !!host.querySelector("details.more[open]"), wasMeaning = !!host.querySelector(".meaning details[open]");
  const kids = [
    el("h3", {style: "margin-top:0"}, "What matters most", el("span", {}, preset === "custom" ? "Custom" : "")),
    ...limitsEditor(),
    el("h3", {}, "Options", el("span", {}, opts && !opts.error ? `${opts.options.filter(o => o.within_limits).length} of ${opts.options.length} inside your limits` : ""))];
  if (!opts) kids.push(el("p", {className: "empty"}, "Finding options…"));
  else if (opts.error) kids.push(el("p", {className: "warn"}, `Could not load options (${opts.error}).`));
  else {
    const cur = opts.currency, rec = recommend(opts), picked = opts.options.find(o => o.id === pickedId) || opts.options[0];
    kids.push(el("div", {role: "radiogroup", ariaLabel: "Options"}, opts.options.map(o => el("button", {className: "opt", role: "radio", ariaChecked: String(o === picked),
      onclick: () => { pickedId = o.id; renderPlan(); draw(); fitOption(o.id); },
      onmouseenter: () => { const was = pickedId; if (was !== o.id && optRoutes?.options[o.id] && !optRoutes.options[o.id].same_line) { pickedId = o.id; draw(); pickedId = was; } },
      onmouseleave: () => draw()},
      el("span", {className: "radio"}),
      el("span", {className: "name"}, o.label, " ",
        o.id === rec ? el("span", {className: "badge badge-rec"}, `Best for ${presetName()}`) : "",
        o.within_limits ? "" : el("span", {className: "badge badge-out"}, "Outside limits")),
      el("span", {className: "cost " + (o.extra_cost > 0 ? "worse" : o.extra_cost < 0 ? "better" : "same")}, o.extra_cost < 0 ? `saves ${money(-o.extra_cost, cur)}` : costText(o.extra_cost, cur)),
      el("span", {className: "f"},
        el("span", {}, timeDelta(o.delay_hours)[0] === "same time" ? "No delay" : `${timeDelta(o.delay_hours)[0]}${o.delay_hours < 0 ? " (sooner)" : ""}`),
        kmOf(o) ? el("span", {}, `${kmOf(o) > 0 ? "+" : "−"}${Math.abs(kmOf(o)).toLocaleString()} km`) : "",
        el("span", {}, "Risk after: ", el("span", {className: "dot", style: `background:${COLORS[o.resulting_risk || 0]}`}), ` ${o.resulting_risk} ${NAMES[o.resulting_risk] || ""}`),
        ...(o.violations || []).map(v => el("span", {className: "out"}, cap(v))))))));
    if (opts.no_reroute && !opts.options.some(o => o.kind === "reroute")) kids.push(el("p", {className: "note", style: "margin-top:8px"}, el("b", {}, "No reroute offered. "), opts.no_reroute));
    if (opts.options.length < 2) kids.push(el("p", {className: "note", style: "margin-top:8px"}, "No disruption on this route, so there is nothing to move."));
    const eta = new Date(+new Date(d.eta) + picked.delay_hours * 36e5).toISOString();
    const done = decisions.filter(x => x.shipment_id === selected).at(-1);
    kids.push(el("h3", {}, "If you choose this"),
      el("div", {className: "newplan"},
        el("div", {className: "nhead"}, el("b", {}, picked.label), picked.detail ? el("div", {className: "note"}, picked.detail) : ""),
        el("dl", {className: "figs"},
          el("div", {}, el("dt", {}, "New ETA"), el("dd", {}, dt(eta), el("small", {}, picked.delay_hours ? `was ${dt(d.eta)}` : "unchanged"))),
          el("div", {}, el("dt", {}, "Extra cost"), el("dd", {}, picked.extra_cost > 0 ? `+${money(picked.extra_cost, cur)}` : picked.extra_cost < 0 ? `saves ${money(-picked.extra_cost, cur)}` : "None", el("small", {}, picked.cost_basis === "default" ? "estimate" : "estimate, your rates"))),
          el("div", {}, el("dt", {}, "Risk after"), el("dd", {}, `${picked.resulting_risk} ${NAMES[picked.resulting_risk] || ""}`, el("small", {}, `now ${opts.current_risk}`)))),
        picked.cost_lines?.length ? costTable([[null, picked.cost_lines]], picked.extra_cost, cur, picked.cost_note) : "",
        opts.terms?.carrier ? el("p", {className: "note terms"}, `Carrier ${opts.terms.carrier}${opts.terms.promised_by ? ` · promised to the customer by ${dt(opts.terms.promised_by)}` : ""} · demo fleet terms`) : "",
        journey(d, picked.delay_hours),
        el("div", {className: "foot"},
          done && done.option_id === picked.id ? el("div", {className: "submitted", style: "margin:0"}, el("b", {}, "Submitted"), `${dt(done.submitted_at)} · tentative, nothing is booked`)
            : el("button", {className: "btn primary", onclick: async e => { e.currentTarget.disabled = true; try { await submit(picked); renderPlan(); } catch { e.currentTarget.textContent = "Could not submit, try again"; e.currentTarget.disabled = false; } }}, `Submit: ${picked.label}`),
          el("button", {className: "btn", style: "margin-top:8px", onclick: () => { noticeOpen = !noticeOpen; renderPlan(); }}, noticeOpen ? "Hide the notice" : "Draft a notice for the customer or carrier"),
          noticeOpen ? el("div", {className: "notice"},
            el("textarea", {id: "notice-text", rows: 12, ariaLabel: "Draft notice", value: noticeText(d, picked, cur)}),
            el("div", {className: "note"}, "A draft from a fixed template: the facts, figures and sources above, no model. Edit it, then copy. Nothing is sent. ",
              el("button", {className: "textbtn", onclick: async e => { const b = e.currentTarget; try { await navigator.clipboard.writeText($("notice-text").value); b.textContent = "Copied"; } catch { $("notice-text").select(); b.textContent = "Selected: press Ctrl+C"; } }}, "Copy"))) : "",
          el("p", {className: "note", style: "margin-top:8px"}, "An estimate, not a quote. Stop times move by the option's delay. Submitting records your choice as tentative; nothing is booked or sent to a carrier."))));
  }
  host.replaceChildren(...kids);
  if (wasOpen) host.querySelector("details.more").open = true;
  if (wasMeaning) host.querySelector(".meaning details").open = true;
}

// ---- Ask PortShifter: one assistant, in every view. It answers, and it does three jobs on request:
// plan the whole fleet, plan new shipments from a sentence, and check the live web for new disruptions.
// Each job shows its steps and comes back for approval before anything is recorded. ----
let runs = [], check = null, botOpen = false, pendingNew = null, planned = [];
const WHO = "PORTSHIFTER";
const botLog = () => $("bot-log");
const botDown = () => { botLog().scrollTop = 1e9; };
const botSay = (...kids) => { const m = el("div", {className: "msg"}, el("span", {className: "by"}, WHO), ...kids); botLog().append(m); botDown(); return m; };
const botYou = text => { botLog().append(el("div", {className: "msg you"}, text)); botDown(); };
const botWait = text => { const m = el("div", {className: "msg muted"}, text); botLog().append(m); botDown(); return m; };
const NEW_EXAMPLE = "Plan these new shipments with my current fleet: London warehouse to Southampton port, 20 pallets, arriving by Friday 17:00; Brussels warehouse to London warehouse and end at Glasgow, 4 reefers, leaving tomorrow 08:00";
// Suggestions stay under the conversation, so any of them can be picked again at any time.
const BOT_CHIPS = [
  ["What needs me now?", "The shipments to deal with first", () => botAsk("What needs me now?")],
  ["Optimise the fleet", "I plan every affected shipment and bring you one plan to approve", () => botAsk("Optimise everything for the least cost")],
  ["Plan new shipments", "Puts an example in the box for you to edit", () => { $("bot-msg").value = NEW_EXAMPLE; $("bot-msg").focus(); }],
  ["Check for disruptions", "I search the live web for one corridor and rescore the fleet", () => botAsk("Check for new disruptions")],
  ["What if…?", "Try a hypothetical disruption against the fleet. Nothing is saved", () => { $("bot-msg").value = "What if Dover closes tomorrow for 3 days?"; $("bot-msg").focus(); }],
  ["Brief me", "What I found and what I propose, step by step", () => botAsk("Brief me")],
  ["What can you do?", "", () => botAsk("What can you do?")],
];
const botHistory = []; // the turns sent with each question, so a follow-up ("why?", "and the cost?") makes sense
const chipRow = items => el("span", {className: "chips"}, items.map(([label, title, go]) => el("button", {type: "button", className: "chipbtn", title: title || "", onclick: go}, label)));
function botGreeting() {
  return el("div", {className: "msg"}, el("span", {className: "by"}, WHO),
    "Hi, I am PortShifter. Ask me anything about your shipments, disruptions, routes and costs, in your own words. I can also plan the whole fleet, plan new shipments from a sentence, or check for new disruptions: I show my steps and ask before anything is recorded.");
}
// Where the window sits. By default over the map, just right of the left panel and at the bottom: the one area
// with no primary actions. It never covers the shipment panel on the right: if that is open, the window is
// kept to its left, wherever it was dragged.
function placeBot() {
  const box = $("bot"), ws = $("ws"), w = box.offsetWidth, h = box.offsetHeight;
  let pos = null; try { pos = JSON.parse(localStorage.getItem("portshift.bot2") || "null"); } catch { /* default place */ }
  const detail = $("detail").hidden ? 0 : $("detail").offsetWidth;
  const maxLeft = Math.max(8, ws.clientWidth - detail - w - 12);
  box.style.left = Math.min(Math.max(8, pos ? pos.left : 410), maxLeft) + "px";
  box.style.top = Math.min(Math.max(8, pos ? pos.top : ws.clientHeight - h - 22), Math.max(8, ws.clientHeight - h - 8)) + "px";
}
function renderBot() {
  const win = $("bot"), shown = !win.hidden && !win._closing;
  $("bot-open").setAttribute("aria-expanded", String(botOpen));
  $("bot-open").classList.toggle("on", botOpen);
  if (!botOpen) { if (shown) closeWindow(win, $("bot-open"), () => { if (!botOpen) win.hidden = true; }); else if (!win._closing) win.hidden = true; return; }
  win.hidden = false;
  if (!botLog().children.length) botLog().append(botGreeting());
  if (!$("bot-chips").children.length) $("bot-chips").append(chipRow(BOT_CHIPS));
  const last = runs[0];
  $("bot-sub").textContent = lastRead ? (lastRead.source === "model" ? "Requests read by the fine-tuned reader, checked against your words" : "Requests read by fixed patterns")
    : last?.finished_at ? `Last live check ${span(last.finished_at)} ago · ${last.corridor}` : "Asks before it acts · drag to move";
  $("bot-sub").title = lastRead?.why || "";
  placeBot();
  if (!shown) openWindow(win, $("bot-open"));
}
function openBot(message) { botOpen = true; renderBot(); if (message) botAsk(message); else $("bot-msg").focus(); }
$("bot-open").onclick = () => { botOpen = !botOpen; renderBot(); if (botOpen) $("bot-msg").focus(); };
$("bot-close").onclick = () => { botOpen = false; renderBot(); };
$("bot-clear").onclick = () => { botLog().replaceChildren(); botHistory.length = 0; pendingNew = pendingDetails = null; renderBot(); };
$("bot-form").onsubmit = e => { e.preventDefault(); const m = $("bot-msg").value.trim(); if (!m) return; $("bot-msg").value = ""; botAsk(m); };
{ // drag the window by its header
  const head = $("bot-head"); let start = null;
  head.onpointerdown = e => { if (e.target.closest("button")) return; const b = $("bot");
    start = {x: e.clientX, y: e.clientY, left: b.offsetLeft, top: b.offsetTop}; head.setPointerCapture(e.pointerId); };
  head.onpointermove = e => { if (!start) return; const b = $("bot"), ws = $("ws");
    const detail = $("detail").hidden ? 0 : $("detail").offsetWidth; // cannot be dropped onto the shipment panel
    b.style.left = Math.min(Math.max(8, start.left + e.clientX - start.x), Math.max(8, ws.clientWidth - detail - b.offsetWidth - 12)) + "px";
    b.style.top = Math.min(Math.max(8, start.top + e.clientY - start.y), ws.clientHeight - b.offsetHeight - 8) + "px"; };
  head.onpointerup = () => { if (!start) return; start = null;
    try { localStorage.setItem("portshift.bot2", JSON.stringify({left: $("bot").offsetLeft, top: $("bot").offsetTop})); } catch { /* not stored */ } };
  addEventListener("resize", () => { if (botOpen) placeBot(); });
}

let lastRead = null; // how the last message was read: {request, source: model | patterns, why}
async function botAsk(message) {
  if (!botOpen) { botOpen = true; renderBot(); }
  botYou(message);
  botHistory.push({role: "user", text: message});
  const note = text => botHistory.push({role: "assistant", text});
  try {
    if (pendingNew && /^\s*(yes|yep|yeah|ok(ay)?|sure|go|do it|please|plan (it|them)|go ahead)\b/i.test(message)) return startNewPlan(pendingNew);
    if ((pendingNew || pendingDetails) && /^\s*(no|nope|cancel|not now|stop|never ?mind|forget it)\b/i.test(message)) { pendingNew = pendingDetails = null; return botSay("No problem. Nothing was created."); }
    if (/^\s*(open stock|send stock)/i.test(message)) { $("tab-new").click(); setSource("stock"); return botSay("Opened Plan a shipment with warehouse stock. Pick the warehouse as the first stop, say how much of each line to send and where, and I will suggest routes for it."); }
    if (/last (check|run)|what (did|have) you (check|do|done)|your activity/i.test(message)) return botLastRun();
    if (/^\s*(and )?(what if|what happens if|suppose|imagine)\b/i.test(message)) { note("Ran a what-if."); botSay("Let me run that against the fleet. It is hypothetical: nothing is saved."); return askWhatIf(message); }
    if (/\bbrief(ing)? ?(me)?\b|catch me up|while i was (out|away)|where (do )?things stand/i.test(message)) { note("Opened the briefing."); botSay("Here is the briefing."); return openBriefing(); }
    // One reading of the message decides what happens: by the fine-tuned request reader when it is running
    // (its answer is checked against the message), else by fixed patterns. See app/router.py.
    const wait = botWait("…");
    lastRead = await postJSON("/api/route", {message, expecting: pendingDetails ? "shipment_details" : null});
    renderBot();
    if (lastRead.understood_as) { // a slip of the keyboard was put right: say how it was read, and work from that
      botLog().append(el("div", {className: "readas"}, `Read as: ${lastRead.understood_as}`)); botDown();
      message = lastRead.understood_as;
    }
    const q = lastRead.request;
    if (pendingDetails) { // the chat is waiting for the cargo or timing of shipments it is planning
      if (q.intent === "shipment_details") { wait.remove(); note("Added cargo or timing to the new shipments."); return newShipments(pendingDetails.request, pendingDetails.shipments, q.details); }
      if (["greeting", "help", "out_of_scope", "fleet_question"].includes(q.intent)) { wait.remove();
        return botSay("I did not find a cargo or a date in that. For the shipments I am planning I still need what each one carries (for example \"20 pallets\") and when (for example \"arrive by Friday 17:00\", \"as soon as possible\" or \"no deadline\"). Say \"cancel\" to drop them."); }
      if (q.intent === "plan_new_shipments") pendingDetails = null; // a fresh request replaces the one in progress
    }
    if (q.intent === "plan_fleet") { wait.remove();
      note("Planning the whole fleet for approval.");
      botSay("On it. I am going through every shipment a disruption touches and will open one plan for you to approve. Nothing changes until you approve it.");
      return fleetPlan(message, q);
    }
    if (q.intent === "live_check") { wait.remove(); note("Live check."); return botCheck(q.corridor); }
    if (q.intent === "plan_new_shipments") { wait.remove(); note("Planning new shipments."); return newShipments(message, lastRead.source === "model" ? q.shipments : []); }
    if (q.intent === "shipment_details") { wait.remove(); return botSay("That looks like cargo or timing, but I am not planning a shipment right now. Tell me the stops too, for example: \"London warehouse to Southampton port, 20 pallets, arriving by Friday 17:00\"."); }
    if (q.intent === "needs_attention") { wait.remove(); note("Listed the shipments needing attention."); return botTop(); }
    if (q.intent === "out_of_scope") { wait.remove();
      const text = "Sorry, that is outside what I can help with. I can answer questions about your shipments, disruptions, routes, costs and stock, and plan them with you.";
      note(text); return botSay(text, chipRow([["What can you do?", "", () => botAsk("What can you do?")]]));
    }
    const r = await postJSON("/api/assistant", {message, history: botHistory.slice(-7, -1), selected, known_in_scope: lastRead.source === "model"});
    wait.remove(); note(r.text);
    const cites = (r.citations || []).map(c => el("div", {}, link(c.url, c.title), el("span", {className: "muted"}, ` · ${ago(c.retrieved_at)}`)));
    botSay(r.text,
      cites.length > 2 ? el("details", {}, el("summary", {}, `${cites.length} sources`), cites) : cites.length ? el("span", {className: "cites"}, cites) : "",
      r.shipment_ids?.length ? el("span", {className: "chips"}, r.shipment_ids.map(id => el("button", {type: "button", className: "chipbtn id", title: `Open ${id}`, onclick: () => { ptab = "details"; select(id); }}, id))) : "",
      r.chips?.length ? chipRow(r.chips.map(c => [c, "", () => botAsk(c)])) : "",
      r.records?.length ? el("details", {className: "used"}, el("summary", {}, `${r.records.length} record${r.records.length === 1 ? "" : "s"} retrieved for this answer${r.retrieval === "hybrid" ? " · BM25 + embeddings" : r.retrieval === "bm25" ? " · BM25" : ""}`),
        el("span", {className: "cites faint"}, r.records.map(x => `[${x.ref}] ${x.kind}: ${x.title}`).join(" · "))) : "",
      r.used_model ? el("span", {className: "cites faint"}, "Worded by a language model from the records retrieved for your question. Figures are checked against them; open the shipments it names to confirm.") : "");
  } catch (err) { botLog().querySelector(".msg.muted")?.remove(); botSay(el("span", {className: "warn"}, `That did not work (${err.message}). Nothing was changed.`)); }
}
function botTop() {
  const top = ships.filter(s => lvlOf(s) >= 4 && s.impact_at).sort((a, b) => Math.max(Date.now(), far(a.impact_at)) - Math.max(Date.now(), far(b.impact_at)) || lvlOf(b) - lvlOf(a)).slice(0, 3);
  if (!top.length) return botSay("Nothing is Severe or Critical right now.");
  botSay(`${top.length} shipment${top.length === 1 ? "" : "s"} to deal with first, soonest confirmed disruption first:`,
    el("span", {className: "opts"}, top.map(s => el("span", {className: "optline"}, el("b", {}, `${s.shipment_id} · ${NAMES[lvlOf(s)]}`),
      el("small", {}, `${s.risk.reason}. ${new Date(s.impact_at) > Date.now() ? `Disruption in ${span(s.impact_at)}` : "Disruption under way"}${s.wait_out ? ` · about ${money(s.wait_out.cost, s.wait_out.currency)} to wait out (estimate)` : ""}.`),
      el("button", {className: "btn small", onclick: () => { ptab = "plan"; select(s.shipment_id); }}, "Options")))),
    chipRow([["Optimise everything for the least cost", "I plan all of them and bring you one plan to approve", () => botAsk("Optimise everything for the least cost")]]));
}
function botLastRun() {
  const r = runs[0];
  if (!r) return botSay("I have not run a live check here yet. Say \"check for new disruptions\" and I will, if live search is set up on this server.");
  let steps = []; try { steps = JSON.parse(r.steps_json || "[]"); } catch { /* summary only */ }
  botSay(`My last live check was ${span(r.finished_at)} ago on ${r.corridor}: ${r.queries_run} searches, ${r.results_seen} results, ${r.events_extracted} events kept${r.events_dropped ? `, ${r.events_dropped} dropped` : ""}.${r.error ? ` It ended with an error: ${r.error}.` : ""}`,
    steps.length ? el("span", {className: "cites"}, steps.map(st => el("div", {}, `Searched "${st.query}": ${st.results} results, ${st.extracted} kept`))) : "");
}
// A live check: which corridor, what it will search, then the result or the plain reason it could not run.
function botCheck(corridor) {
  if (!check) return botSay("I could not reach the check service. Nothing was run.");
  if (!corridor) return botSay("Which corridor should I check? A corridor is a group of ports and routes your fleet uses, each with its own fixed set of web searches. I run those searches, keep only events with a source, cross-check them, and rescore the fleet.",
    chipRow(check.corridors.map(c => [c, `Searches: ${(check.corridor_queries?.[c] || []).join(" · ")}`, () => botAsk(`Check ${c}`)])),
    el("span", {className: "cites"}, "Hover a corridor to see its searches."),
    check.can_run ? "" : el("span", {className: "cites"}, `Heads-up: ${check.reason}`));
  return runBotCheck(corridor);
}
async function runBotCheck(corridor) {
  const queries = check.corridor_queries?.[corridor] || [];
  if (!check.can_run) return botSay(`I did not run the check on ${corridor}. ${check.reason}`,
    el("span", {className: "cites"}, `With live search set up, I would search: ${queries.join(" · ")}.`));
  const wait = botWait(`Searching the live web for ${corridor}: ${queries.join(" · ")}…`);
  const res = await postJSON("/api/check", {corridor});
  wait.remove();
  if (!res.ran) return botSay(`I did not run the check. ${res.reason}`);
  [ships, events, summary, runs] = await Promise.all(["/api/shipments", "/api/events", "/api/summary", "/api/runs"].map(getJSON));
  opts = null; refresh(); if (selected) select(selected);
  const run = res.run;
  botSay(run.error ? `The check on ${corridor} ended with an error: ${run.error}.` : `Checked ${corridor}: ${run.queries_run} searches, ${run.results_seen} results, ${run.events_extracted} event${run.events_extracted === 1 ? "" : "s"} kept${run.events_dropped ? `, ${run.events_dropped} dropped` : ""}.`,
    el("span", {className: "cites"}, (run.steps || []).map(st => el("div", {}, `Searched "${st.query}": ${st.results} results, ${st.extracted} kept`))),
    res.changed.length ? el("span", {className: "opts"}, res.changed.map(c => el("span", {className: "optline"}, el("b", {}, `${c.shipment_id}: ${NAMES[c.from || 0]} → ${NAMES[c.to || 0]}`),
        el("small", {}, "Its level changed after this check."), el("button", {className: "btn small", onclick: () => select(c.shipment_id)}, "Open"))))
      : el("span", {className: "cites"}, res.rescored ? "I rescored the fleet: no shipment changed level." : "Events are written to Delta; the risk job rescores the fleet."));
}
// New shipments from a sentence: say what was understood, offer to plan in full, then the plans for approval.
// A shipment is planned only once it has its stops, its cargo and its timing. While any of those is missing the
// chat asks for it, and asks again, and `pendingDetails` holds what is known so far.
let pendingDetails = null; // {request, shipments: [{stops, cargo, when}]}
const whenText = w => !w ? "" : w.kind === "arrive_by" ? `arrive by ${w.at ? dt(w.at) : w.text}` : w.kind === "depart_at" ? `leave ${w.at ? dt(w.at) : w.text}`
  : w.kind === "asap" ? "as soon as possible" : "no deadline";
const cargoText = c => c ? `${c.units} ${CARGO[c.unit_type] || c.unit_type}` : "";
async function newShipments(message, shipments = [], details = []) { // shipments: already split (by the reader, or kept from the last round); details: a reply filling gaps
  const wait = botWait(details.length ? "Adding that to the shipments…" : "Reading the shipments and placing the stops…");
  const d = await postJSON("/api/plan-new", {message, shipments, details, preferences: limits, places: ownPlaces()});
  wait.remove();
  if (!d.shipments.length) return botSay("I could not find a shipment in that. Give me the stops, what it carries and when, for example: \"London warehouse to Southampton port, 20 pallets, arriving by Friday 17:00\".");
  d.request = pendingDetails?.request || message;
  const ready = d.shipments.filter(x => !x.problem && !x.missing.length);
  const understood = el("span", {className: "opts"}, d.shipments.map(x => { const r = x.routes.find(y => y.id === x.recommended_id);
    return el("span", {className: "optline wide"}, el("b", {}, `${x.ref} · ${x.label}`),
      x.problem ? el("small", {className: "out"}, x.problem) : el("small", {},
        el("span", {className: x.cargo ? "" : "out"}, x.cargo ? cargoText(x.cargo) : "cargo not given"), " · ",
        el("span", {className: x.when && !x.when.problem ? "" : "out"}, x.when && !x.when.problem ? whenText(x.when) : x.when?.problem || "timing not given")),
      r ? el("small", {}, `${r.label}: ${Math.round(r.km).toLocaleString()} km, ${durText(r.hours)}, about ${money(r.cost, r.currency)}, risk ${r.risk.level} ${NAMES[r.risk.level || 0]}; leaves ${dt(r.depart_at)}, arrives ${dt(r.eta)}`
        + (r.slack_hours != null ? (r.slack_hours >= 0 ? `, ${durText(r.slack_hours)} before the deadline` : `, ${durText(-r.slack_hours)} AFTER the deadline`) : "") + "."
        + (x.routes.length > 1 ? ` ${x.routes.length - 1} other route${x.routes.length === 2 ? "" : "s"} to compare.` : "")) : "",
      ...x.same_lane.map(sl => el("small", {}, `${sl.shipment_id} already runs this lane (${sl.cargo}, leaves ${dt(sl.departs)}).`))); }));
  if (d.needs.length) { // ask for what is missing, and keep what is known
    const first = !pendingDetails;
    pendingDetails = {request: d.request, shipments: d.shipments.map(x => x.request)}; pendingNew = null;
    return botSay(first ? `I read ${d.shipments.length} new shipment${d.shipments.length === 1 ? "" : "s"}. Before I plan ${d.shipments.length === 1 ? "it" : "them"} I need to know what each one carries and when it should happen, so the plan fits the load and the date:`
        : "Thanks, noted. I still need:", understood,
      el("span", {}, d.needs.map(n => `${n.ref}: ${n.missing.map(k => k === "cargo" ? "the cargo" : n.problem ? "a date I can read" : "the timing").join(" and ")}`).join("; ") + "."),
      el("span", {className: "cites"}, `Cargo: ${d.need_text.cargo}. Timing: ${d.need_text.when}. Answer for all at once ("20 pallets, arrive by Friday 17:00") or one by one ("NEW-1: 12 reefers, leaving tomorrow 08:00; NEW-2: 4 pallets, no deadline").`),
      d.needs.some(n => n.missing.includes("when")) ? chipRow([["As soon as possible", "Timing for every shipment still missing one", () => botAsk("as soon as possible")], ["No deadline", "", () => botAsk("no deadline")],
        ["Cancel", "Stop planning these shipments", () => botAsk("cancel")]]) : chipRow([["Cancel", "Stop planning these shipments", () => botAsk("cancel")]]));
  }
  pendingDetails = null;
  // Every shipment has its stops, cargo and timing: plan them all and open the one panel to review and approve.
  botSay(`${details.length ? "Thanks, that is everything. " : ""}I have ${d.shipments.length} new shipment${d.shipments.length === 1 ? "" : "s"} with cargo and timing:`, understood,
    ready.length ? el("span", {}, `I have picked a route for ${ready.length === 1 ? "it" : "each"} (the cheapest that meets its date and your risk limit) and opened the plan${ready.length === 1 ? "" : "s"} for you. Open any one to see it on the map, then approve them all with one click. Nothing is saved until you do.`) : "",
    ready.length ? el("span", {className: "yesno"}, el("button", {className: "btn small", onclick: () => startNewPlan(d)}, "Open the plans again")) : "");
  pendingNew = null;
  if (ready.length) startNewPlan(d);
}
function startNewPlan(d) {
  pendingNew = null;
  if (!d) return;
  const ok = d.shipments.filter(x => !x.problem && !x.missing.length);
  const late = x => !!x.routes.find(y => y.id === x.recommended_id)?.late;
  if (selected) deselect();
  // Every plan is ticked except one that cannot meet its arrive-by date: "Approve all" never saves a late plan unasked.
  proposal = {kind: "new", request: d.request, data: d, picked: new Set(ok.filter(x => !late(x)).map(x => x.ref)), route: Object.fromEntries(ok.map(x => [x.ref, x.recommended_id])),
    focus: null, shown: 0, state: "working", error: null};
  stepThrough(d);
}
function stepThrough(d) { // show the work step by step, then the proposal
  renderProposal();
  const tick = setInterval(() => {
    if (!proposal || proposal.data !== d) return clearInterval(tick);
    if (++proposal.shown >= d.steps.length) { clearInterval(tick); proposal.state = "review";
      const want = new URLSearchParams(location.search).get("view"); // ?view=NEW-2 opens that plan on the map
      const x = want && proposal.kind === "new" && d.shipments.find(y => y.ref === want && y.routes.length);
      if (x) { proposal.focus = x.ref; fit(x.routes.find(y => y.id === proposal.route[x.ref]).legs.flatMap(l => l.geometry), 8); }
      draw(); }
    renderProposal();
  }, 380);
}
const pause = ms => new Promise(r => setTimeout(r, ms));
function drawPlanned() { // approved plans (grey, dashed) and the plans being reviewed (accent)
  const line = (legs, color, label, strong) => {
    legs.forEach(l => L.polyline(l.geometry, {color, weight: strong ? 3.5 : 2.5, opacity: strong ? 1 : 0.8, dashArray: "7 7", lineCap: "round", interactive: false}).addTo(shipLayer));
    const last = legs[legs.length - 1];
    L.circleMarker([last.to_lat, last.to_lon], {radius: 4.5, color: css("--surface"), weight: 2, fillColor: color, fillOpacity: 1, interactive: false})
      .bindTooltip(esc(label), {permanent: true, direction: "top", offset: [0, -6], className: "stop-label"}).addTo(shipLayer);
  };
  planned.forEach(x => line(x.legs, css("--muted"), `${x.plan_id} planned`, false));
  if (proposal?.kind === "new" && proposal.state !== "working" && proposal.state !== "done") proposal.data.shipments.forEach(x => {
    const r = x.routes.find(y => y.id === proposal.route[x.ref]); if (!r) return;
    if (proposal.focus !== x.ref) { if (proposal.picked.has(x.ref)) line(r.legs, css("--accent"), x.ref, !proposal.focus); return; }
    const c = COLORS[r.risk.level || 0]; // the plan being viewed: its whole route in its risk colour, every stop numbered
    r.legs.forEach(l => { L.polyline(l.geometry, {color: c, weight: 10, opacity: 0.18, interactive: false}).addTo(shipLayer);
      L.polyline(l.geometry, {color: c, weight: 4, dashArray: l.mode === "ship" ? "8 7" : l.mode === "plane" ? "2 8" : null, lineCap: "round", interactive: false}).addTo(shipLayer); });
    [[r.legs[0].from_name, r.legs[0].from_lat, r.legs[0].from_lon], ...r.legs.map(l => [l.to_name, l.to_lat, l.to_lon])].forEach(([n, la, lo], i) =>
      L.circleMarker([la, lo], {radius: 5.5, color: css("--surface"), weight: 2, fillColor: c, fillOpacity: 1, interactive: false})
        .bindTooltip(`${i + 1}. ${esc(n)}`, {permanent: true, direction: "top", offset: [0, -7], className: "stop-label"}).addTo(shipLayer)); });
}

// ---- market rates: what freight rates are being reported at, each line with its source ----
async function loadRates(refresh = false) {
  try { rates = await getJSON("/api/rates" + (refresh ? "?refresh=true" : "")); } catch { rates = null; }
  if (summary) renderInsights(summary);
}
function ratesBlock() {
  if (!rates) return [el("h3", {}, "Market rates"), el("p", {className: "muted"}, "Could not load market rates.")];
  return [
    el("h3", {}, el("span", {style: "display:flex;gap:8px;align-items:center;letter-spacing:.14em;text-transform:uppercase;font-weight:700"}, "Market rates",
        el("span", {className: "badge " + (rates.live ? "badge-rec" : "badge-sample")}, rates.live ? "live search" : "sample")),
      el("button", {className: "textbtn", title: "Search again", onclick: e => { e.currentTarget.textContent = "Searching…"; loadRates(true); }}, "Refresh")),
    ...rates.topics.map(t => el("div", {className: "rate"},
      el("div", {className: "rate-h"}, el("span", {className: "micon", innerHTML: svgIcon(t.mode)}), t.label),
      ...(t.items.length ? t.items.map(i => el("div", {className: "src"}, i.claim,
        el("div", {className: "note"}, link(i.url, i.title), ` · ${i.domain} · ${ago(i.retrieved_at)}`, i.is_fixture ? el("span", {className: "badge badge-sample", style: "margin-left:6px"}, "sample") : "")))
        : [el("p", {className: "note"}, "Nothing found for this search.")]))),
    el("p", {className: "note", style: "margin-top:10px"}, rates.note),
    el("div", {className: "rate"}, el("div", {className: "rate-h"}, "What PortShift's estimates use"),
      el("p", {className: "note"}, rateView && (rateView.mine.rate_cards.length || rateView.mine.delay_charges.length || rateView.mine.surcharges.length)
        ? "Your own rates where one applies, and illustrative defaults for everything else. Market rates above are never used to price a shipment."
        : "Illustrative default rates. Enter your own contract rates and they are used instead. Market rates above are never used to price a shipment."),
      el("button", {className: "textbtn", onclick: () => $("tab-rat").click()}, "Open My rates →"))];
}

// ---- insights: statistics over the tables already loaded ----
function renderInsights(s) {
  const n = s.shipments || 1, pct = v => `${Math.round(100 * v / n)}%`;
  const kpi = (label, value, sub) => el("div", {className: "kpi"}, el("dt", {}, label), el("dd", {}, el("b", {}, value), el("span", {}, sub)));
  const bar = counts => el("div", {className: "bar"}, [5, 4, 3, 2, 1, 0].map(i => el("i", {style: `width:${100 * (counts[i] || 0) / (Object.values(counts).reduce((a, b) => a + b, 0) || 1)}%;background:${COLORS[i]}`})));
  const levels = Object.fromEntries(Object.entries(s.levels).map(([k, v]) => [Number(k), v]));
  const modes = {}; ships.forEach(x => { (modes[x.mode] ||= {})[lvlOf(x)] = (modes[x.mode][lvlOf(x)] || 0) + 1; });
  const types = {}; events.forEach(e => { types[e.type] = (types[e.type] || 0) + 1; });
  const next = ships.filter(x => x.impact_at && new Date(x.impact_at) > Date.now() && lvlOf(x) >= 3)
    .sort((a, b) => new Date(a.impact_at) - new Date(b.impact_at))[0];
  const urgent = levels[4] + levels[5];
  $("ins").replaceChildren(
    el("dl", {className: "kpis"},
      kpi("Require attention", String(urgent), `Severe or Critical · ${pct(urgent)}`),
      kpi("Affected", `${s.affected} of ${s.shipments}`, "at Watch or above"),
      kpi("Disruptions", String(s.events.total), `${s.events.confirmed} confirmed · ${s.events.suspected} suspected`),
      kpi("Cost to wait out", money(s.exposure.amount, s.exposure.currency), `${s.exposure.shipments} shipments · ${s.exposure.note}`)),
    ...ratesBlock(),
    el("h3", {}, "Risk distribution"), bar(levels),
    el("div", {className: "risk-key"}, [5, 4, 3, 2, 1, ...(levels[0] ? [0] : [])].map(i =>
      el("span", {}, el("span", {className: "dot", style: `background:${COLORS[i]}`}), ` ${NAMES[i]} `, el("b", {}, String(levels[i]))))),
    el("h3", {}, "By mode"),
    ...Object.entries(modes).map(([m, c]) => { const tot = Object.values(c).reduce((a, b) => a + b, 0), hit = Object.entries(c).filter(([l]) => l >= 3).reduce((a, [, v]) => a + v, 0);
      return el("div", {className: "stat"}, el("span", {}, cap(m)), bar(c), el("span", {className: "v"}, `${hit} of ${tot} at risk`)); }),
    el("h3", {}, "Disruptions by type"),
    ...Object.entries(types).map(([t, c]) => el("div", {className: "stat"}, el("span", {}, cap(t)),
      el("div", {className: "bar"}, el("i", {style: `width:${100 * c / events.length}%;background:var(--accent)`})), el("span", {className: "v"}, String(c)))),
    el("h3", {}, "Next impact"),
    next ? el("button", {className: "btn impact" + (lvlOf(next) === 3 ? " dark" : ""), style: `--lv:${COLORS[lvlOf(next)]}`, onclick: () => select(next.shipment_id)},
        el("b", {}, next.shipment_id), ` · ${NAMES[lvlOf(next)]} · event starts in ${span(next.impact_at)}`, el("span", {className: "go", ariaHidden: "true"}, "→"))
      : el("p", {className: "muted"}, "No upcoming event window on an at-risk shipment."),
    el("h3", {}, "Submitted plans", el("span", {}, "tentative, nothing booked")),
    ...(decisions.length ? decisions.slice().reverse().map(x => el("div", {className: "stat", style: "grid-template-columns:70px 1fr auto"},
      el("button", {className: "textbtn", onclick: () => select(x.shipment_id)}, x.shipment_id), el("span", {}, x.label), el("span", {className: "v"}, x.extra_cost ? `+${money(x.extra_cost)}` : "No cost")))
      : [el("p", {className: "muted"}, "None yet.")]),
    el("h3", {}, "Planned shipments", el("span", {}, "approved plans · tentative, nothing booked")),
    ...(planned.length ? planned.slice().reverse().map(x => el("div", {className: "stat", style: "grid-template-columns:44px 1fr auto"},
      el("b", {}, x.plan_id), el("span", {}, `${x.label} · ${x.route_label}`), el("span", {className: "v"}, money(x.cost, x.currency))))
      : [el("div", {className: "empty-cta"}, el("p", {className: "muted"}, "None yet. Ask PortShifter to schedule shipments for you, or plan new shipments yourself."),
          el("div", {className: "acts"},
            el("button", {className: "btn small primary", onclick: () => openBot()}, "Ask PortShifter"),
            el("button", {className: "btn small", onclick: () => $("tab-new").click()}, "Plan a shipment")))]),
    el("h3", {}, "Evidence freshness"),
    el("p", {}, s.evidence.newest_retrieved_at ? `Newest source ${ago(s.evidence.newest_retrieved_at)}, oldest ${ago(s.evidence.oldest_retrieved_at)}.` : "No sources yet."),
    el("p", {className: "note", style: "margin-top:14px"}, `Demo fleet: synthetic shipments, real disruptions.${s.events.sample ? ` ${s.events.sample} of ${s.events.total} disruptions are samples.` : ""} Costs are estimates at illustrative rates.`));
}

// ---- plan a shipment: build a route from known or own places, get suggested routes ----
const KIND = {warehouse: ["Warehouse", "--text"], customer: ["Customer site", "--kind-customer"], port: ["Port", "--link"], airport: ["Airport", "--kind-air"]};
const kindColor = k => k === "port" ? "#2463c7" : k === "airport" ? "#7a4fd6" : k === "customer" ? "#c0357a" : css("--text");
// One mark per kind of place, used on the map, in the palette and in the map key. Customer sites are a house shape.
const glyph = (kind, on = false) => kind === "customer"
  ? `<svg class="place-icon customer${on ? " on" : ""}" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.6 14.6 7v7.4H1.4V7z" fill="${kindColor("customer")}"/></svg>`
  : `<div class="place-icon ${kind}${on ? " on" : ""}" style="--k:${kindColor(kind)}"></div>`;
let places = [], myPlaces = [], customers = []; // customers: customer sites from /api/customers (samples + the operator's own)
try { myPlaces = JSON.parse(localStorage.getItem("portshift.places") || "[]"); } catch { /* none stored */ }
const draft = {stops: [], modes: [], depart: "", arrive: "", planFrom: "depart", urgency: "none", result: null, picked: null, pending: null, busy: false, error: null,
  cargo: {units: 20, unit_type: "pallet", weight_kg: null}, source: "cargo", fleet: null, needs: {reefer: false, adr: false}}; // source: "cargo" (anything) or "stock" (from a warehouse)
const CARGO = {pallet: "pallets", container_20: "20 ft containers", container_40: "40 ft containers", reefer: "reefer containers", trailer: "trailers", tonne: "tonnes"};
const allPlaces = () => [...myPlaces, ...customers, ...places];
const ownPlaces = () => [...myPlaces, ...customers]; // places the server's planner does not know by itself
async function loadCustomers() { try { customers = await getJSON("/api/customers"); } catch { customers = []; } }
async function addCustomer(p) {
  const res = await fetch("/api/customers", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(p)});
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`);
  customers.push(body); return body;
}
async function removeCustomer(name) {
  const res = await fetch(`/api/customers/${encodeURIComponent(name)}`, {method: "DELETE"});
  if (res.ok) customers = await res.json();
}
function deliverTo(p) { // from a customer site on the map: open Plan a shipment with it as the last stop
  $("tab-new").click();
  if (draft.stops.length < 2) draft.stops = [draft.stops[0] || placeBy("Birmingham warehouse"), p].filter(Boolean);
  else draft.stops[draft.stops.length - 1] = p;
  draft.modes = draft.modes.slice(0, draft.stops.length - 1); while (draft.modes.length < draft.stops.length - 1) draft.modes.push("truck");
  draft.modes[draft.modes.length - 1] = "truck"; changedDraft();
}
const placeBy = name => allPlaces().find(p => p.name === name);
const saveMine = () => { try { localStorage.setItem("portshift.places", JSON.stringify(myPlaces)); } catch { /* not stored */ } };
const durText = h => h >= 48 ? `${(h / 24).toFixed(1)} days` : h < 1 ? `${Math.round(h * 60)} min` : `${Math.round(h)} h`;

function plannerPick(r) { // which suggested route the chosen setting (and how urgent it is) points at
  const ok = r.routes.filter(x => !x.problems.length);
  const pool = ok.filter(x => x.within_limits);
  const soonest = list => [...list].sort((a, b) => a.eta.localeCompare(b.eta) || a.cost - b.cost)[0]?.id;
  if (draft.urgency === "fastest") { const safe = ok.filter(x => (x.risk.level || 9) <= limits.max_risk); return soonest(safe.length ? safe : ok.length ? ok : r.routes); }
  if (draft.urgency === "deadline" && !pool.length) return soonest(ok.length ? ok : r.routes); // nothing makes it: the least late
  const from = pool.length ? pool : ok.length ? ok : r.routes;
  if (preset === "low_risk") return [...from].sort((a, b) => (a.risk.level || 9) - (b.risk.level || 9) || a.hours - b.hours || a.cost - b.cost)[0]?.id;
  return [...from].sort((a, b) => a.cost - b.cost || (a.risk.level || 9) - (b.risk.level || 9))[0]?.id;
}

const isoOf = local => local ? new Date(local).toISOString().slice(0, 19) + "Z" : null; // datetime-local (browser time) to UTC
const spanText = h => durText(Math.abs(h));
async function findRoutes() {
  if (draft.stops.length < 2) return;
  draft.busy = true; draft.error = null; renderPlanner();
  try {
    const r = await postJSON("/api/routes", {stops: draft.stops, modes: draft.modes, places: ownPlaces(), preferences: limits, cargo: draft.source === "stock" ? stockCargo() : draft.cargo,
      depart_at: isoOf(draft.depart), arrive_by: draft.urgency === "deadline" ? isoOf(draft.arrive) : null,
      plan_from: draft.urgency === "deadline" ? draft.planFrom : "depart"});
    draft.result = r; draft.picked = plannerPick(r);
  } catch (err) { draft.error = err.message; draft.result = null; }
  draft.busy = false; renderPlanner(); draw();
  const route = draft.result?.routes.find(x => x.id === draft.picked);
  if (route) fit(route.legs.flatMap(l => l.geometry), 7);
}
const localInput = d => new Date(d.getTime() - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 16); // value for a datetime-local input
function dateField(label, key, hint, required = false) {
  return el("label", {className: "when"}, label + (required ? " *" : ""), el("input", {type: "datetime-local", value: draft[key], title: hint, required,
    ariaLabel: `${label}: ${hint}`, onchange: e => { draft[key] = e.target.value; changedDraft(); }}));
}
// Keep the chosen route as a planned shipment (tentative, nothing booked); shows up in Planned shipments.
function savePlanBox(x) {
  const key = `${draft.stops.map(st => st.name).join(">")}|${x.id}`, done = draft.saved?.key === key ? draft.saved : null;
  const save = async () => {
    draft.saving = true; draft.saveError = null; renderPlanner();
    try {
      const first = draft.stops[0].name, last = draft.stops[draft.stops.length - 1].name;
      const when = draft.urgency === "deadline" && draft.arrive ? {kind: "arrive_by", text: `Arrive by ${dt(isoOf(draft.arrive))}`}
        : draft.depart ? {kind: "depart_at", text: `Leave ${dt(isoOf(draft.depart))}`} : {kind: "asap", text: "As soon as possible"};
      const [row] = await postJSON("/api/planned", {plans: [{label: `${first} → ${last}`, source: "planner", cargo: draft.cargo || null, when, route: x}]});
      planned.push(row); draft.saved = {key, plan_id: row.plan_id};
    } catch (err) { draft.saveError = err.message; }
    draft.saving = false; refresh();
  };
  return el("div", {className: "box save-plan"},
    done ? el("p", {}, el("b", {}, `Added to planned shipments as ${done.plan_id}.`), " ",
             el("button", {className: "textbtn", onclick: () => $("tab-pln").click()}, "View planned shipments →"))
      : el("button", {className: "btn primary", disabled: draft.saving || !!x.problems.length, onclick: save},
          draft.saving ? "Adding…" : "Add to planned shipments"),
    draft.saveError ? el("p", {className: "warn"}, `Could not add: ${draft.saveError}`) : "",
    el("p", {className: "note"}, "Tentative: nothing is booked with a carrier. Costs are estimates."));
}
function changedDraft() { draft.result = null; draft.picked = null; draft.saved = null; dsp.error = null; renderPlanner(); draw(); }
function addStop(p) { draft.stops.push(p); if (draft.stops.length > 1) draft.modes.push("truck"); changedDraft(); }

function renderPlanner() {
  if (!places.length) return;
  if (!draft.stops.length) { draft.stops = ["Glasgow warehouse", "London warehouse (Hayes)"].map(placeBy).filter(Boolean); draft.modes = ["truck"]; }
  const group = (label, list) => list.length ? el("optgroup", {label}, list.map(p => el("option", {value: p.name}, p.name))) : "";
  const fromStock = draft.source === "stock", whs = stockWarehouses();
  if (fromStock && whs.length && !whs.some(w => w.warehouse === draft.stops[0]?.name)) draft.stops[0] = placeBy(whs[0].warehouse);
  const picker = (i) => { const sel = el("select", {ariaLabel: `Stop ${i + 1}`, onchange: e => { draft.stops[i] = placeBy(e.target.value); if (fromStock && !i) { dsp.qty = {}; dsp.done = null; } changedDraft(); }},
    ...(fromStock && !i && whs.length ? [group("Warehouses with stock", whs.map(w => placeBy(w.warehouse)))] : [
    group("My places", myPlaces), group("Customer sites", customers), group("Warehouses", places.filter(p => p.kind === "warehouse")),
    group("Ports", places.filter(p => p.kind === "port")), group("Airports", places.filter(p => p.kind === "airport"))]));
    sel.value = draft.stops[i].name; return sel; };
  const rows = [];
  draft.stops.forEach((st, i) => {
    rows.push(el("div", {className: "stop"}, el("span", {className: "ix"}, String(i + 1)), picker(i),
      draft.stops.length > 2 && !(fromStock && !i) ? el("button", {className: "rm", ariaLabel: `Remove stop ${i + 1}`, title: "Remove this stop",
        onclick: () => { draft.stops.splice(i, 1); draft.modes.splice(Math.min(i, draft.modes.length - 1), 1); changedDraft(); }}, "×") : el("span", {})));
    if (i < draft.stops.length - 1) rows.push(el("div", {className: "legmode"}, "by",
      el("div", {className: "seg3", role: "group", ariaLabel: `Mode for leg ${i + 1}`}, Object.keys(MODE_ICONS).map(m =>
        el("button", {type: "button", ariaPressed: String(draft.modes[i] === m), innerHTML: svgIcon(m) + cap(m),
          onclick: () => { draft.modes[i] = m; changedDraft(); }})))));
  });
  const wh = fromStock ? stockWh() : null, cargo = fromStock ? stockCargo() : null;
  const kids = [
    draft.wantTruck ? el("div", {className: "using"}, el("span", {className: "mode-ic", innerHTML: svgIcon("truck")}),
      el("span", {}, el("b", {}, `Using ${draft.wantTruck.name}`), draft.wantTruck.registration ? ` (${draft.wantTruck.registration})` : "", el("small", {}, `from ${draft.wantTruck.base} · holds ${draft.wantTruck.capacity.toLocaleString()} ${UNIT_NAME[draft.wantTruck.capacity_unit]}${draft.wantTruck.payload_kg ? `, ${draft.wantTruck.payload_kg.toLocaleString()} kg` : ""} · choose where it goes, then Suggest routes`)),
      el("button", {className: "rm", title: "Plan without a particular truck", ariaLabel: "Stop using this truck", onclick: () => { draft.wantTruck = null; draft.fleet = null; renderPlanner(); }}, "×")) : "",
    el("div", {className: "legmode source"}, "What's going",
      el("div", {className: "seg3", role: "group", ariaLabel: "What is being shipped"}, [["cargo", "Any cargo"], ["stock", "Warehouse stock"]].map(([k, label]) =>
        el("button", {type: "button", ariaPressed: String(draft.source === k), onclick: () => setSource(k)}, label)))),
    el("p", {className: "note"}, fromStock
      ? [stockView?.is_sample ? el("span", {className: "badge badge-sample", style: "margin-right:6px"}, "sample stock") : "", "Send stock from a warehouse: it is the first stop. Pick what to send, plan the route, then submit it to the warehouse. Nothing is booked with a carrier."]
      : "Test a shipment before it exists. Chain legs by truck, ship and plane; nothing is booked."),
    fromStock && dsp.done ? el("div", {className: "submitted"}, el("b", {}, `${dsp.done.order_id} submitted to ${dsp.done.warehouse}`),
      `${dsp.done.lines.map(l => `${l.quantity} ${l.unit}s ${l.item.toLowerCase()}`).join(", ")} to ${dsp.done.destination} · leaves ${dt(dsp.done.depart_at)} · about ${money(dsp.done.cost, dsp.done.currency)} · kept in ${dsp.done.stored}. Nothing is booked with a carrier.`) : "",
    fromStock && !stockView ? el("p", {className: "warn"}, "Could not load warehouse stock.") : "",
    el("h3", {}, "Route", el("span", {}, fromStock ? "stop 1 is the warehouse" : "or click a place on the map")), ...rows,
    el("button", {className: "textbtn", style: "margin-top:8px", onclick: () => {
      const next = allPlaces().find(p => !draft.stops.some(s => s.name === p.name)); if (next) addStop(next); }}, "+ Add a stop"),
    el("h3", {}, "How urgent?", el("span", {}, "time, then your setting below")),
    el("div", {className: "seg3 urgency", role: "group", ariaLabel: "How urgent is this shipment"}, [["fastest", "Fastest"], ["deadline", "By a date"], ["none", "No deadline"]].map(([k, label]) =>
      el("button", {type: "button", ariaPressed: String(draft.urgency === k), onclick: () => { draft.urgency = k; if (k !== "deadline") draft.planFrom = "depart"; changedDraft(); }}, label))),
    el("p", {className: "note", style: "margin-top:6px"}, {
      fastest: "Suggests the earliest arrival within your risk limit; every route is listed by arrival time.",
      deadline: "Routes that miss the date are marked late; the pick is the best on-time route for your setting below.",
      none: "Leaves when you say; the pick follows your setting below."}[draft.urgency]),
    ...(draft.urgency === "deadline" ? [
      dateField("Arrive by", "arrive", "When the cargo must arrive", true),
      el("div", {className: "quick-dates", role: "group", ariaLabel: "Arrive within"}, [["1 day", 1], ["2 days", 2], ["3 days", 3], ["1 week", 7]].map(([label, days]) =>
        el("button", {type: "button", className: "chip", onclick: () => { const from = draft.depart ? new Date(draft.depart) : new Date(Date.now() + 2 * 36e5);
          draft.arrive = localInput(new Date(from.getTime() + days * 864e5)); changedDraft(); }}, `in ${label}`))),
      el("div", {className: "legmode source", style: "margin-top:10px"}, "Send it",
        el("div", {className: "seg3", role: "group", ariaLabel: "When to send it"}, [["depart", "As soon as possible"], ["arrive", "Just in time"]].map(([k, label]) =>
          el("button", {type: "button", ariaPressed: String(draft.planFrom === k), title: k === "arrive" ? "Work backwards: the latest time to send it and still arrive by the date" : "Leave at the time below and check the date",
            onclick: () => { draft.planFrom = k; changedDraft(); }}, label)))),
      dateField(draft.planFrom === "arrive" ? "Not before" : "Leaves", "depart", draft.planFrom === "arrive" ? "Optional: the earliest the cargo can leave" : "Leave empty for two hours from now"),
    ] : [dateField("Leaves", "depart", "Leave empty for two hours from now")]),
    ...(fromStock ? [
      el("h3", {}, `What to send from ${wh ? wh.warehouse.replace(" warehouse", "") : "the warehouse"}`, el("span", {}, wh ? `stock as of ${dt(wh.updated_at)}` : "")),
      ...(wh ? wh.lines.map(row => el("label", {className: "sline" + (row.available ? "" : " none")},
        el("span", {}, el("b", {}, row.item), el("small", {}, `${row.sku} · ${row.available} of ${row.quantity} ${row.unit}s available${row.reserved ? ` · ${row.reserved} already allocated` : ""} · ${row.kg_per_unit} kg each`)),
        el("input", {type: "number", min: 0, max: row.available, step: 1, value: dsp.qty[row.stock_id] || "", placeholder: "0", disabled: !row.available, ariaLabel: `Pallets of ${row.item} to send`,
          onchange: e => { dsp.qty[row.stock_id] = Math.max(0, Math.min(row.available, Math.floor(+e.target.value || 0))); dsp.done = null; changedDraft(); }}),
        el("span", {className: "note"}, `${row.unit}s`))) : []),
      el("p", {className: "note stotal"}, cargo?.units ? el("b", {}, `${cargo.units} pallets · ${Math.round(cargo.weight_kg).toLocaleString()} kg to send`) : "Enter how many pallets of each line to send."),
    ] : [
    el("div", {className: "when cargo"}, "Carrying",
      el("span", {}, el("input", {type: "number", min: 1, max: 5000, value: draft.cargo.units, ariaLabel: "How many units",
          onchange: e => { draft.cargo.units = Math.max(1, +e.target.value || 1); changedDraft(); }}),
        el("select", {ariaLabel: "Unit type", onchange: e => { draft.cargo.unit_type = e.target.value; changedDraft(); }},
          Object.entries(CARGO).map(([k, label]) => el("option", {value: k, selected: draft.cargo.unit_type === k}, label))))),
    el("label", {className: "when"}, "Weight", el("input", {type: "number", min: 0, placeholder: "kg, optional (used for air)", value: draft.cargo.weight_kg ?? "",
      onchange: e => { draft.cargo.weight_kg = +e.target.value || null; changedDraft(); }}))]),
    el("h3", {}, "My places", el("span", {}, "drag a type onto the map")),
    el("div", {className: "palette"}, Object.entries(KIND).map(([k, [label]]) => el("span", {className: "drag", draggable: true, title: `Drag onto the map to add your own ${label.toLowerCase()}`,
      ondragstart: e => { e.dataTransfer.setData("text/plain", k); e.dataTransfer.effectAllowed = "copy"; $("ws").classList.add("dropping"); },
      ondragend: () => $("ws").classList.remove("dropping")}, el("i", {className: "kglyph", innerHTML: glyph(k)}), label))),
    draft.pending ? el("form", {className: "pending", onsubmit: e => { e.preventDefault();
        const name = e.target.elements.pname.value.trim(); if (!name || placeBy(name)) return e.target.elements.pname.focus();
        if (draft.pending.kind === "customer") { const owner = e.target.elements.pcust?.value.trim() || "";
          addCustomer({...draft.pending, name, customer: owner}).then(p => { draft.pending = null; draft.pendingError = null; addStop(p); })
            .catch(err => { draft.pendingError = err.message; renderPlanner(); }); return; }
        const p = {...draft.pending, name}; myPlaces.unshift(p); saveMine(); draft.pending = null; addStop(p); }},
      el("b", {}, `Name this ${KIND[draft.pending.kind][0].toLowerCase()} (${draft.pending.lat.toFixed(2)}, ${draft.pending.lon.toFixed(2)})`),
      el("input", {name: "pname", placeholder: draft.pending.kind === "customer" ? "e.g. Acme DC (Wakefield)" : "e.g. Leeds depot", autocomplete: "off"}),
      draft.pending.kind === "customer" ? el("input", {name: "pcust", placeholder: "Customer, optional", autocomplete: "off"}) : "",
      draft.pendingError ? el("p", {className: "warn", style: "grid-column:1/-1"}, draft.pendingError) : "",
      el("button", {className: "btn small primary"}, "Save"),
      el("button", {type: "button", className: "btn small", onclick: () => { draft.pending = null; draft.pendingError = null; renderPlanner(); draw(); }}, "Cancel")) : "",
    ...myPlaces.map(p => el("div", {className: "mine"}, el("i", {className: "kglyph", innerHTML: glyph(p.kind)}), p.name,
      el("span", {className: "note"}, KIND[p.kind][0]),
      el("button", {className: "rm", title: "Delete this place", ariaLabel: `Delete ${p.name}`, onclick: () => {
        myPlaces = myPlaces.filter(x => x !== p); saveMine(); draft.stops = draft.stops.filter(s => s.name !== p.name);
        draft.modes = draft.modes.slice(0, Math.max(0, draft.stops.length - 1)); changedDraft(); }}, "×"))),
    el("h3", {}, "Customer sites", el("span", {}, customers.some(c => c.is_sample) ? "demo sites · drag Customer site onto the map to add yours" : "drag Customer site onto the map to add one")),
    ...customers.map(p => el("div", {className: "mine"}, el("i", {className: "kglyph", innerHTML: glyph("customer")}),
      el("button", {className: "textbtn", title: "Make this the last stop", onclick: () => deliverTo(p)}, p.name),
      el("span", {className: "note"}, p.customer || "yours"),
      p.is_sample ? el("span", {}) : el("button", {className: "rm", title: "Delete this customer site", ariaLabel: `Delete ${p.name}`, onclick: async () => {
        await removeCustomer(p.name); draft.stops = draft.stops.filter(st => st.name !== p.name);
        draft.modes = draft.modes.slice(0, Math.max(0, draft.stops.length - 1)); changedDraft(); }}, "×"))),
    el("h3", {}, "What matters most"),
    el("div", {className: "presets"}, Object.entries(PRESETS).map(([k, pr]) =>
      el("button", {className: "preset", type: "button", ariaPressed: String(preset === k), onclick: () => { setPreset(k); if (draft.result) findRoutes(); else renderPlanner(); }},
        el("b", {}, pr.label), el("span", {}, pr.desc)))),
    el("button", {className: "btn primary", style: "margin-top:12px", disabled: draft.busy || draft.stops.length < 2 || (fromStock && !cargo?.units) || (draft.urgency === "deadline" && !draft.arrive), onclick: findRoutes}, draft.busy ? "Working…" : "Suggest routes"),
    draft.error ? el("p", {className: "warn"}, `Could not get routes (${draft.error}).`) : ""];
  const r = draft.result;
  if (r) {
    const best = plannerPick(r);
    kids.push(el("h3", {}, "Suggested routes", el("span", {}, `risk up to ${limits.max_risk} ${NAMES[limits.max_risk]}`)),
      el("div", {role: "radiogroup", ariaLabel: "Suggested routes"}, (draft.urgency === "none" ? r.routes : [...r.routes].sort((a, b) => (a.problems.length - b.problems.length) || a.eta.localeCompare(b.eta))).map(x => {
        const lvl = x.risk.level || 0, on = x.id === draft.picked;
        return el("button", {className: "opt", role: "radio", ariaChecked: String(on), onclick: () => { draft.picked = x.id; renderPlanner(); draw(); fit(x.legs.flatMap(l => l.geometry), 7); }},
          el("span", {className: "radio"}),
          el("span", {className: "name"}, x.label, " ",
            x.id === best ? el("span", {className: "badge badge-rec"}, pickName()) : "",
            x.problems.length ? el("span", {className: "badge badge-out"}, "Not possible") : x.within_limits ? "" : el("span", {className: "badge badge-out"}, "Outside limits"),
            x.slack_hours == null || x.problems.length ? "" : x.slack_hours < 0 ? el("span", {className: "badge badge-out"}, `Late by ${spanText(x.slack_hours)}`)
              : el("span", {className: "badge"}, x.slack_hours < 1 ? "Just in time" : `${spanText(x.slack_hours)} to spare`)),
          el("span", {className: "cost same"}, money(x.cost, x.currency)),
          el("span", {className: "f"}, x.cost_basis !== "default" ? el("span", {className: "badge src-operator"}, "your rates") : "", el("span", {}, `${Math.round(x.km).toLocaleString()} km`), el("span", {}, durText(x.hours)), el("span", {}, r.plan_from === "arrive" ? el("b", {}, `leave by ${dt(x.depart_at)}`) : `leaves ${dt(x.depart_at)}`), el("span", {}, `arrives ${dt(x.eta)}`),
            el("span", {}, el("span", {className: "dot", style: `background:${COLORS[lvl]}`}), ` ${lvl ? `${lvl} ${NAMES[lvl]}` : "not scored"}`)),
          el("span", {className: "chain"}, x.legs.flatMap((l, i) => [i ? "›" : "", el("span", {innerHTML: svgIcon(l.mode)}), l.to_name]).filter(Boolean)));
      })));
    const x = r.routes.find(y => y.id === draft.picked);
    if (x) kids.push(el("h3", {}, "This route, stop by stop"),
      ...x.problems.map(t => el("p", {className: "warn"}, t)),
      el("div", {className: "timing"}, el("div", {}, el("span", {}, r.plan_from === "arrive" ? "Send it by" : "Leaves"), el("b", {}, dt(x.depart_at))),
        el("div", {}, el("span", {}, "Arrives"), el("b", {}, dt(x.eta))),
        x.arrive_by ? el("div", {className: x.slack_hours < 0 ? "late" : ""}, el("span", {}, `Due ${dt(x.arrive_by)}`),
          el("b", {}, x.slack_hours < 0 ? `${spanText(x.slack_hours)} late` : x.slack_hours < 1 ? "just in time" : `${spanText(x.slack_hours)} to spare`)) : ""),
      el("div", {className: "why-level", style: `margin:0 0 8px;border-left:3px solid ${COLORS[x.risk.level || 0]}`},
        el("b", {}, x.risk.level ? `Risk ${x.risk.level} · ${NAMES[x.risk.level]}` : "Risk not scored"), x.risk.reason,
        ...x.risk.event_ids.map(id => { const e = events.find(v => v.event_id === id);
          return e ? el("div", {}, el("button", {className: "textbtn", onclick: () => openEvent(id)}, `${cap(e.type)} · ${e.location} →`)) : ""; })),
      el("div", {className: "box", style: "margin-top:0"}, el("ol", {className: "journey"},
        el("li", {}, el("b", {}, x.legs[0].from_name), el("span", {className: "time"}, `Leaves ${dt(x.legs[0].planned_start)}`)),
        ...x.legs.map((l, i) => el("li", {className: [l.event_ids.length ? "disrupted" : "", i === x.legs.length - 1 ? "end" : ""].join(" ").trim()},
          el("b", {}, l.to_name), el("span", {className: "time"}, `${i === x.legs.length - 1 ? "Arrives" : "ETA"} ${dt(l.planned_end)} · by ${l.mode}, ${l.km.toLocaleString()} km, ${durText(l.hours)} · ${l.cost == null ? "no rate" : money(l.cost, x.currency)}`),
          l.event_ids.length ? el("span", {className: "flag"}, `Disruption on this leg: ${l.event_ids.map(id => events.find(v => v.event_id === id)?.location || id).join(", ")}`) : "")))),
      costTable(x.legs.map((l, i) => [`Leg ${i + 1} · ${l.from_name} to ${l.to_name} · by ${l.mode}`, l.cost_lines || []]), x.cost, x.currency, x.cost_note),
      el("p", {className: "note", style: "margin-top:10px"}, r.notes, " ",
        el("button", {className: "textbtn", onclick: () => $("tab-ins").click()}, "See reported market rates →")),
      ...(x.problems.length ? [] : fleetSection(x)),
      ...(fromStock ? [] : [savePlanBox(x)]));
    if (x && fromStock && wh) { const chosen = wh.lines.filter(l => dsp.qty[l.stock_id] > 0);
      kids.push(el("div", {className: "box alloc"}, el("div", {className: "bhead"}, `Allocation from ${wh.warehouse}`, el("span", {}, "left in stock after")),
          ...chosen.map(l => el("div", {className: "stat", style: "grid-template-columns:1fr auto auto;padding:7px 12px"}, el("span", {}, l.item), el("b", {}, `${dsp.qty[l.stock_id]} ${l.unit}s`), el("span", {className: "note"}, `${l.available - dsp.qty[l.stock_id]} left`)))),
        el("button", {className: "btn primary", disabled: dsp.busy || !!x.problems.length, onclick: () => submitDispatch(x)}, dsp.busy ? "Submitting…" : `Submit to ${wh.warehouse}`),
        dsp.error ? el("p", {className: "warn"}, `Could not submit: ${dsp.error}`) : "",
        el("p", {className: "note", style: "margin-top:8px"}, `Submitting records a dispatch order for ${wh.warehouse} to pick, and takes these pallets out of what is available. Nothing is booked with a carrier.`));
    }
  }
  if (fromStock && stockView) kids.push(el("h3", {}, "Dispatch orders", el("span", {}, `${stockView.orders.length} so far`)),
    el("p", {className: "note", style: "margin-bottom:8px"}, `Orders are kept in ${stockView.stored}.`),
    ...(stockView.orders.length ? stockView.orders.map(o => el("div", {className: "rcard"},
      el("div", {className: "rhead"}, el("b", {}, `${o.order_id} · ${o.warehouse.replace(" warehouse", "")} → ${o.destination}`),
        el("span", {}, el("span", {className: `badge ${o.status === "submitted" ? "badge-rec" : ""}`}, o.status), "")),
      el("div", {className: "note"}, o.lines.map(l => `${l.quantity} ${l.unit}s ${l.item.toLowerCase()}`).join(", ")),
      el("div", {className: "note"}, `${o.route_label} · leaves ${dt(o.depart_at)} · arrives ${dt(o.eta)} · about ${money(o.cost, o.currency)} · submitted ${dt(o.submitted_at)}`)))
      : [el("p", {className: "muted"}, "None yet.")]));
  $("new").replaceChildren(...kids);
  if (draft.pending) $("new").querySelector("input[name=pname]")?.focus();
}

function drawPlanner() { // places, the route as drawn, and the picked suggestion
  const inRoute = new Set(draft.stops.map(s => s.name));
  [...allPlaces(), ...(draft.pending ? [{...draft.pending, name: "New place"}] : [])].forEach(p => {
    if (!mapShow[p.kind] && !inRoute.has(p.name) && p.name !== "New place") return; // unticked in the map key
    const icon = L.divIcon({className: "", iconSize: [18, 18], html: glyph(p.kind, inRoute.has(p.name))});
    L.marker([p.lat, p.lon], {icon, keyboard: false, zIndexOffset: inRoute.has(p.name) ? 400 : 0})
      .bindTooltip(`<b>${esc(p.name)}</b><small>${KIND[p.kind][0]}${p.customer ? ` · ${esc(p.customer)}` : ""}${myPlaces.includes(p) ? " · yours" : ""}${draft.source === "stock" && stockWarehouses().some(w => w.warehouse === p.name) ? ` · ${stockWarehouses().find(w => w.warehouse === p.name).pallets_available} pallets in stock` : ""} · click to add to the route</small>`, {direction: "top", offset: [0, -8], className: "tip"})
      .on("click", () => { if (p.name !== "New place") addStop(p); }).addTo(shipLayer);
  });
  const route = draft.result?.routes.find(x => x.id === draft.picked);
  if (!route) {
    if (draft.stops.length > 1) L.polyline(draft.stops.map(s => [s.lat, s.lon]), {color: css("--muted"), weight: 2, dashArray: "4 7", interactive: false}).addTo(shipLayer);
  } else {
    const c = COLORS[route.risk.level || 0];
    route.legs.forEach(l => {
      L.polyline(l.geometry, {color: c, weight: 9, opacity: 0.15, interactive: false}).addTo(shipLayer);
      L.polyline(l.geometry, {color: c, weight: 3, opacity: 1, dashArray: l.mode === "ship" ? "8 7" : l.mode === "plane" ? "2 8" : null, lineCap: "round", interactive: false}).addTo(shipLayer);
    });
    const stops = [[route.legs[0].from_name, route.legs[0].from_lat, route.legs[0].from_lon], ...route.legs.map(l => [l.to_name, l.to_lat, l.to_lon])];
    stops.forEach(([n, la, lo], i) => L.circleMarker([la, lo], {radius: 5, color: css("--surface"), weight: 2, fillColor: c, fillOpacity: 1, interactive: false})
      .bindTooltip(`${i + 1}. ${esc(n)}`, {permanent: true, direction: "top", offset: [0, -7], className: "stop-label"}).addTo(shipLayer));
  }
}
$("map").addEventListener("dragover", e => { if (view === "new") { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; } });
$("map").addEventListener("drop", e => {
  if (view !== "new") return;
  e.preventDefault(); $("ws").classList.remove("dropping");
  const kind = e.dataTransfer.getData("text/plain"); if (!KIND[kind]) return;
  const ll = map.mouseEventToLatLng(e);
  draft.pending = {kind, lat: +ll.lat.toFixed(4), lon: +ll.lng.toFixed(4)}; renderPlanner(); draw();
});

// ---- my rates: the operator's own rate cards, delay terms and surcharges ----
let rateView = null, rateForm = null, rateError = null; // rateForm: {table, index (null = new), row}
const MODE_NAME = {ship: "Sea", truck: "Road", plane: "Air"};
const UNIT_PER = {container_20: "per 20 ft container", container_40: "per 40 ft container", reefer: "per reefer container", tonne: "per tonne",
  km: "per truck", pallet: "per pallet", kg: "per kg chargeable"};
const eur = v => `EUR ${(+v).toLocaleString(undefined, {maximumFractionDigits: 4})}`;
const rateText = r => [r.base_rate ? `${eur(r.base_rate)} ${UNIT_PER[r.unit]}` : "", r.per_km ? `${eur(r.per_km)} per km${r.unit === "km" ? " per truck" : ""}` : ""].filter(Boolean).join(" + ")
  + (r.min_charge ? ` · minimum ${eur(r.min_charge)}` : "");
const delayText = r => `${r.free_days} free day${r.free_days === 1 ? "" : "s"}, then ${eur(r.per_unit_per_day)} ${r.unit ? UNIT_PER[r.unit] : "per unit"} per day · rebooking ${eur(r.rebooking_fee)}`;
const laneText = r => r.origin || r.destination ? `${r.origin || "anywhere"} → ${r.destination || "anywhere"}` : "any lane";

async function saveMyRates(next) {
  try {
    const res = await fetch("/api/my-rates", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(next)});
    if (!res.ok) { const d = (await res.json().catch(() => ({}))).detail; rateError = typeof d === "string" ? d : `Could not save (HTTP ${res.status}).`; return renderRates(); }
    rateView = await res.json(); rateForm = null; rateError = null;
    [ships, events, summary] = await Promise.all(["/api/shipments", "/api/events", "/api/summary"].map(getJSON)); // every estimate may have moved
    opts = null; draft.result = null; draft.picked = null; refresh();
  } catch (err) { rateError = `Could not save (${err.message}).`; renderRates(); }
}
const mineCopy = () => JSON.parse(JSON.stringify(rateView.mine));

function rateFormEl() {
  const f = rateForm, r = f.row, isRate = f.table === "rate_cards";
  const field = (name, label, type = "text", {wide, list, ...props} = {}) => { // input.list is read-only: set it as an attribute
    const input = el("input", {name, type, value: r[name] ?? "", autocomplete: "off", ...(type === "number" ? {min: 0, step: "any"} : {}), ...props});
    if (list) input.setAttribute("list", list);
    return el("label", {className: wide ? "wide" : ""}, label, input); };
  const pick = (name, label, options, onchange) => el("label", {}, label, el("select", {name, onchange},
    options.map(([k, text]) => el("option", {value: k, selected: (r[name] ?? "") === k}, text))));
  const read = form => { for (const [k, v] of new FormData(form)) r[k] = v; };
  const units = rateView.mode_units[r.mode].map(u => [u, cap(UNIT_PER[u])]);
  return el("form", {className: "rform", onsubmit: e => { e.preventDefault(); read(e.target);
      const next = mineCopy(); if (f.index == null) next[f.table].push(r); else next[f.table][f.index] = r; saveMyRates(next); }},
    el("b", {className: "wide"}, f.index == null ? (isRate ? "New freight rate" : "New delay terms") : "Edit"),
    field("partner", isRate ? "Partner (carrier)" : "Partner (blank = any)", "text", {placeholder: "e.g. Evercore Line", required: isRate, wide: true, list: "carriers"}),
    pick("mode", "Mode", Object.entries(MODE_NAME), e => { read(e.target.form); r.unit = isRate ? rateView.mode_units[r.mode][0] : ""; renderRates(); }),
    pick("unit", "Priced", isRate ? units : [["", "Any unit"], ...units]),
    ...(isRate ? [
      field("origin", "From (blank = any)", "text", {list: "placenames"}), field("destination", "To (blank = any)", "text", {list: "placenames"}),
      field("base_rate", "Rate, EUR", "number"), field("per_km", "Plus per km, EUR", "number"),
      field("min_charge", "Minimum charge, EUR", "number"), el("span", {}),
      field("valid_from", "Valid from", "date"), field("valid_to", "Valid to", "date"),
      field("note", "Note", "text", {wide: true, placeholder: "e.g. 2026 partnership agreement"}),
    ] : [
      field("free_days", "Free days", "number", {step: 1}), field("per_unit_per_day", "Per unit per day, EUR", "number"),
      field("rebooking_fee", "Rebooking fee, EUR", "number"), el("span", {}),
    ]),
    rateError ? el("p", {className: "warn wide"}, rateError) : "",
    el("div", {className: "wide acts"}, el("button", {className: "btn small primary"}, "Save"),
      el("button", {type: "button", className: "btn small", onclick: () => { rateForm = null; rateError = null; renderRates(); }}, "Cancel")),
    el("datalist", {id: "carriers"}, rateView.carriers.map(c => el("option", {value: c}))),
    el("datalist", {id: "placenames"}, allPlaces().map(p => el("option", {value: p.name}))));
}

function renderRates() {
  if (!rateView) return;
  const v = rateView, m = v.mine;
  const open = (table, index = null) => { rateError = null;
    rateForm = {table, index, row: index == null ? (table === "rate_cards" ? {mode: "ship", unit: "container_20"} : {mode: "ship", unit: "", free_days: 0}) : {...m[table][index]}}; renderRates(); };
  const remove = (table, index) => { const next = mineCopy(); next[table].splice(index, 1); saveMyRates(next); };
  const card = (table, r, i, title, lines, status) => el("div", {className: "rcard" + (status && status !== "active" ? " off" : "")},
    el("div", {className: "rhead"}, el("b", {}, title), status ? el("span", {className: `badge ${status === "active" ? "badge-rec" : "badge-out"}`}, status === "active" ? "in use" : status) : ""),
    ...lines.map(t => el("div", {className: "note"}, t)),
    el("div", {className: "racts"}, el("button", {className: "textbtn", onclick: () => open(table, i)}, "Edit"), el("button", {className: "textbtn del", onclick: () => remove(table, i)}, "Remove")));
  const formFor = table => rateForm && rateForm.table === table ? rateFormEl() : "";
  const setSurcharge = (d, value) => { const next = mineCopy();
    next.surcharges = next.surcharges.filter(x => !(x.code === d.code && x.mode === d.mode));
    if (value !== "" && +value !== d.value) next.surcharges.push({...d, value: +value, partner: null});
    saveMyRates(next); };
  $("rat").replaceChildren(
    el("p", {className: "note"}, v.note),
    el("h3", {}, "Freight rates", el("span", {}, "for planning and detours")),
    ...m.rate_cards.map((r, i) => card("rate_cards", r, i, `${r.partner} · ${MODE_NAME[r.mode]}`,
      [`${laneText(r)} · ${rateText(r)}`, `${r.valid_from || r.valid_to ? `valid ${r.valid_from ? day(r.valid_from) : "from any date"} to ${r.valid_to ? day(r.valid_to) : "any date"}` : "no end date"}${r.note ? ` · ${r.note}` : ""}`], r.status)),
    !m.rate_cards.length && !formFor("rate_cards") ? el("p", {className: "muted"}, "None yet. Add a contract rate, for example a cheaper rate agreed with a partner carrier on one lane.") : "",
    formFor("rate_cards") || el("button", {className: "btn small add", onclick: () => open("rate_cards")}, "+ Add a freight rate"),
    el("h3", {}, "Delay terms", el("span", {}, "for rescheduling")),
    ...m.delay_charges.map((r, i) => card("delay_charges", r, i, `${r.partner || "Any partner"} · ${MODE_NAME[r.mode]}`, [delayText(r)], "active")),
    !m.delay_charges.length && !formFor("delay_charges") ? el("p", {className: "muted"}, "None yet. Add the free days, daily charge and rebooking fee a partner has agreed.") : "",
    formFor("delay_charges") || el("button", {className: "btn small add", onclick: () => open("delay_charges")}, "+ Add delay terms"),
    el("h3", {}, "Surcharges", el("span", {}, "your value replaces the default")),
    ...v.defaults.surcharges.map(d => { const own = m.surcharges.find(x => x.code === d.code && x.mode === d.mode);
      return el("label", {className: "srow"}, el("span", {}, el("b", {}, d.label), el("small", {}, `${MODE_NAME[d.mode]} · ${d.basis === "percent_of_base" ? "% of the freight" : d.basis === "per_unit" ? "EUR per unit" : "EUR flat"} · default ${d.value}`)),
        el("input", {type: "number", min: 0, step: "any", value: own ? own.value : "", placeholder: String(d.value), ariaLabel: `Your value for ${d.label}`, onchange: e => setSurcharge(d, e.target.value)}),
        own ? el("span", {className: "badge src-operator"}, "yours") : el("span", {className: "badge src-default"}, "default")); }),
    rateError && !rateForm ? el("p", {className: "warn"}, rateError) : "",
    el("h3", {}, "Defaults", el("span", {}, "illustrative · used where you have none")),
    ...v.defaults.rate_cards.map(r => el("div", {className: "stat drow"}, el("span", {}, MODE_NAME[r.mode]), el("span", {}, rateText(r)))),
    ...v.defaults.delay_charges.map(r => el("div", {className: "stat drow"}, el("span", {}, MODE_NAME[r.mode]), el("span", {}, `${r.label}: ${delayText(r)}`))),
    el("p", {className: "note", style: "margin-top:12px"}, `${v.stored} Late delivery penalties come from each shipment's own terms (demo fleet).`));
  if (rateForm) $("rat").querySelector(".rform input")?.focus();
}

// ---- warehouse stock, planned through Plan a shipment: the warehouse is stop 1, its stock is the cargo, the order goes to the warehouse ----
let stockView = null;
const dsp = {qty: {}, busy: false, error: null, done: null};
async function loadStock() { try { stockView = await getJSON("/api/stock"); } catch { stockView = null; } renderPlanner(); if (view === "new") draw(); }
const stockWarehouses = () => (stockView?.warehouses || []).filter(w => placeBy(w.warehouse));
const stockWh = () => stockView?.warehouses.find(w => w.warehouse === draft.stops[0]?.name);
const stockLines = () => Object.entries(dsp.qty).filter(([, n]) => n > 0).map(([stock_id, quantity]) => ({stock_id, quantity}));
function stockCargo() {
  const chosen = (stockWh()?.lines || []).filter(r => dsp.qty[r.stock_id] > 0);
  return {units: chosen.reduce((t, r) => t + dsp.qty[r.stock_id], 0), unit_type: "pallet", weight_kg: chosen.reduce((t, r) => t + dsp.qty[r.stock_id] * r.kg_per_unit, 0)};
}
function setSource(k) { if (draft.source === k) return; draft.source = k; dsp.qty = {}; dsp.done = null; changedDraft(); }
async function submitDispatch(route) {
  const wh = stockWh(); dsp.busy = true; dsp.error = null; renderPlanner();
  try {
    const res = await fetch("/api/dispatch", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({warehouse: wh.warehouse, lines: stockLines(), route, stops: draft.stops.map(st => st.name)})});
    const body = await res.json();
    if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`);
    dsp.done = body; dsp.qty = {}; draft.result = null; draft.picked = null;
    try { planned = await getJSON("/api/planned"); } catch {} // the dispatch is recorded as a planned shipment too
  } catch (err) { dsp.error = err.message; }
  dsp.busy = false; await loadStock(); refresh();
}

// ---- fleet: the operator's vehicles and booked capacity; status is worked out by the server from the bookings ----
let fleetView = null, fleetForm = null, fleetError = null, fleetFilter = "all"; // fleetForm: {id (null = new), row}
const UNIT_NAME = {pallet: "pallets", container_20: "20 ft containers", container_40: "40 ft containers", trailer: "trailers", kg: "kg"};
const stBadge = a => el("span", {className: "badge" + (a.status === "available" ? "" : " st-busy")}, a.status_label); // plain when free, greyed when not
async function loadFleet() { try { fleetView = await getJSON("/api/fleet"); } catch { fleetView = null; } renderFleet(); if (summary) renderChrome(summary); if (view === "flt" || view === "map") draw(); }
async function fleetSend(method, url, body) {
  const res = await fetch(url, {method, headers: {"Content-Type": "application/json"}, body: body ? JSON.stringify(body) : undefined});
  const out = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof out.detail === "string" ? out.detail : `HTTP ${res.status}`);
  return out;
}
async function fleetSave(method, url, body) {
  try { fleetView = await fleetSend(method, url, body); fleetForm = null; fleetError = null; draft.fleet = null; }
  catch (err) { fleetError = err.message; }
  if (summary) renderChrome(summary);
  renderFleet(); renderPlanner(); draw();
}
function fleetFormEl() {
  const f = fleetForm, r = f.row, vehicle = r.record === "vehicle";
  const read = form => { for (const [k, v] of new FormData(form)) r[k] = v; r.reefer = !!form.elements.reefer?.checked; r.adr = !!form.elements.adr?.checked; };
  const field = (name, label, type = "text", props = {}) => el("label", {className: props.wide ? "wide" : ""}, label,
    el("input", {name, type, value: r[name] ?? "", autocomplete: "off", ...(type === "number" ? {min: 0, step: "any"} : {}), placeholder: props.placeholder || "", required: !!props.required}));
  const pick = (name, label, options, rerender) => el("label", {}, label, el("select", {name, onchange: rerender ? e => { read(e.target.form); renderFleet(); } : null},
    options.map(([k, text]) => el("option", {value: k, selected: (r[name] ?? "") === k}, text))));
  const kind = r.mode === "ship" ? "port" : r.mode === "plane" ? "airport" : "warehouse";
  const here = places.filter(p => p.kind === kind).map(p => [p.name, p.name]);
  const units = (r.mode === "truck" ? ["pallet"] : r.mode === "plane" ? ["kg"] : ["container_40", "container_20", "trailer"]).map(u => [u, cap(UNIT_NAME[u])]);
  if (!units.some(([u]) => u === r.capacity_unit)) r.capacity_unit = units[0][0];
  return el("form", {className: "rform", onsubmit: e => { e.preventDefault(); read(e.target);
      fleetSave(f.id ? "PUT" : "POST", f.id ? `/api/fleet/${encodeURIComponent(f.id)}` : "/api/fleet", r); }},
    el("b", {className: "wide"}, f.id ? `Edit ${f.id}` : vehicle ? "New vehicle" : "New booked capacity"),
    pick("mode", vehicle ? "Type" : "Mode", vehicle ? [["truck", "Truck"], ["ship", "Ship (owned or chartered)"], ["plane", "Plane (owned or chartered)"]] : [["ship", "Sea"], ["plane", "Air"]], true),
    ...(vehicle ? [
      field("name", "Name or fleet number", "text", {placeholder: "e.g. Artic 12", required: true}),
      field("registration", r.mode === "truck" ? "Registration" : "Registration or IMO"), field("body", r.mode === "truck" ? "Body" : "Class", "text", {placeholder: r.mode === "truck" ? "curtainsider, box, refrigerated" : ""}),
      pick("base", "Based at", here),
    ] : [
      field("carrier", "Carrier", "text", {placeholder: "e.g. Evercore Line", required: true}),
      field("service", "Service", "text", {placeholder: "e.g. North Sea shuttle"}), el("span", {}),
      pick("origin", "From", here), pick("destination", "To", here),
    ]),
    field("capacity", vehicle ? "Maximum capacity" : "Space per departure", "number", {required: true}), pick("capacity_unit", "Counted in", units),
    ...(vehicle ? [
      field("payload_kg", "Payload, kg", "number"), el("span", {}),
      field("cost_per_km", "Your cost per km, EUR", "number"), field("cost_per_day", "Your cost per day, EUR", "number"),
      ...(r.mode === "truck" ? [el("label", {className: "check"}, el("input", {type: "checkbox", name: "reefer", checked: !!r.reefer}), "Refrigerated"),
        el("label", {className: "check"}, el("input", {type: "checkbox", name: "adr", checked: !!r.adr}), "Dangerous goods (ADR)")] : []),
      field("off_road_until", "Off road until (blank = in service)", "date", {wide: true}),
    ] : [
      field("rate", `Your rate, EUR per ${UNIT_NAME[r.capacity_unit].replace(/s$/, "")}`, "number"), field("cutoff_hours", "Cut-off before departure, h", "number"),
    ]),
    field("note", "Note", "text", {wide: true}),
    fleetError ? el("p", {className: "warn wide"}, fleetError) : "",
    el("div", {className: "wide acts"}, el("button", {className: "btn small primary"}, "Save"),
      el("button", {type: "button", className: "btn small", onclick: () => { fleetForm = null; fleetError = null; renderFleet(); }}, "Cancel")));
}
function renderFleet() {
  if (!$("flt")) return;
  if (!fleetView) return $("flt").replaceChildren(el("p", {className: "muted"}, "Could not load the fleet."));
  const v = fleetView, vehicles = v.assets.filter(a => a.record === "vehicle"), space = v.assets.filter(a => a.record === "capacity");
  const open = (record, a = null) => { fleetError = null;
    fleetForm = {id: a ? a.asset_id : null, record, row: a ? {...a, off_road_until: (a.off_road_until || "").slice(0, 10)}
      : record === "vehicle" ? {record, mode: "truck", capacity: 26, capacity_unit: "pallet", payload_kg: 25000, base: "Birmingham warehouse"}
      : {record, mode: "ship", capacity_unit: "container_40", origin: "Rotterdam", destination: "Felixstowe"}}; renderFleet(); };
  const formFor = record => fleetForm && fleetForm.row.record === record ? fleetFormEl() : "";
  const shown = vehicles.filter(a => fleetFilter === "all" || a.status === fleetFilter);
  const card = a => el("div", {className: "rcard fcard " + (a.status === "available" ? "free" : "busy")},
    el("div", {className: "rhead"}, el("b", {}, a.record === "vehicle" ? el("span", {className: "mode-ic", innerHTML: svgIcon(a.mode)}) : el("span", {className: "mode-ic", innerHTML: svgIcon(a.mode)}), ` ${a.name}`, a.registration ? el("span", {className: "note"}, ` · ${a.registration}`) : ""),
      el("span", {}, stBadge(a))),
    a.record === "vehicle"
      ? el("div", {className: "note"}, [`${a.capacity.toLocaleString()} ${UNIT_NAME[a.capacity_unit]}`, a.payload_kg ? `${a.payload_kg.toLocaleString()} kg payload` : "", a.body, a.reefer ? "refrigerated" : "", a.adr ? "ADR" : "", `based at ${a.base}`].filter(Boolean).join(" · "))
      : el("div", {className: "note"}, `${a.origin} → ${a.destination} · ${a.capacity.toLocaleString()} ${UNIT_NAME[a.capacity_unit]} per departure · cut-off ${a.cutoff_hours} h${a.rate != null ? ` · EUR ${a.rate} per ${UNIT_NAME[a.capacity_unit].replace(/s$/, "")}` : ""}`),
    a.record === "vehicle" && (a.cost_per_km != null || a.cost_per_day != null) ? el("div", {className: "note"}, `your cost: EUR ${a.cost_per_km ?? 0} per km + EUR ${a.cost_per_day ?? 0} per day`) : "",
    a.status === "off_road" ? el("div", {className: "note"}, `Off road until ${day(a.off_road_until)}`)
      : a.busy_with ? el("div", {className: "note"}, `${a.status === "in_transit" ? "On" : "Next:"} ${a.busy_with} · free again ${dt(a.free_from)}`) : "",
    el("div", {className: "racts"}, el("button", {className: "textbtn", onclick: () => open(a.record, a)}, "Edit"),
      a.record === "vehicle" ? el("button", {className: "textbtn", onclick: () => fleetSave("PUT", `/api/fleet/${encodeURIComponent(a.asset_id)}`,
        {off_road_until: a.status === "off_road" ? "" : new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 19) + "Z"})}, a.status === "off_road" ? "Back in service" : "Take off road") : "",
      el("button", {className: "textbtn del", onclick: () => fleetSave("DELETE", `/api/fleet/${encodeURIComponent(a.asset_id)}`)}, "Remove")));
  const refs = [...new Set(v.bookings.map(b => b.booking_ref))];
  $("flt").replaceChildren(
    el("p", {className: "note"}, v.is_sample ? el("span", {className: "badge badge-sample", style: "margin-right:6px"}, "demo fleet") : "", v.note),
    el("div", {className: "seg3 fstat", role: "group", ariaLabel: "Filter vehicles by status"},
      [["all", `All ${vehicles.length}`], ...Object.entries(v.status_names).map(([k, label]) => [k, `${label} ${v.counts[k]}`])].map(([k, label]) =>
        el("button", {type: "button", ariaPressed: String(fleetFilter === k), onclick: () => { fleetFilter = k; renderFleet(); }}, label))),
    el("h3", {}, "Vehicles", el("span", {}, "trucks, and any ship or plane you run")),
    ...shown.map(card), !shown.length ? el("p", {className: "muted"}, "None with that status.") : "",
    formFor("vehicle") || el("button", {className: "btn small add", onclick: () => open("vehicle")}, "+ Add a vehicle"),
    el("h3", {}, "Booked capacity", el("span", {}, "space agreed with sea and air carriers")),
    ...space.map(card),
    formFor("capacity") || el("button", {className: "btn small add", onclick: () => open("capacity")}, "+ Add booked capacity"),
    fleetError && !fleetForm ? el("p", {className: "warn"}, fleetError) : "",
    el("h3", {}, "Reservations", el("span", {}, "made from Plan a shipment")),
    ...(refs.length ? refs.map(ref => { const rows = v.bookings.filter(b => b.booking_ref === ref);
      return el("div", {className: "rcard"}, el("div", {className: "rhead"}, el("b", {}, `${ref} · ${rows[0].label}`),
          el("button", {className: "textbtn del", onclick: () => fleetSave("DELETE", `/api/fleet/bookings/${encodeURIComponent(ref)}`)}, "Release")),
        ...rows.map(b => el("div", {className: "note"}, `${v.assets.find(a => a.asset_id === b.asset_id)?.name || b.asset_id} · ${b.from_name} → ${b.to_name} · ${dt(b.start)} to ${dt(b.end)}`))); })
      : [el("p", {className: "muted"}, "None yet. Pick a route in Plan a shipment and choose your vehicles for it.")]),
    el("p", {className: "note", style: "margin-top:12px"}, `Kept in ${v.stored}.`));
  if (fleetForm) $("flt").querySelector(".rform input")?.focus();
}
function depotPrompt(base, d, at) { // clicking a depot asks which of its trucks to use for a shipment
  const body = el("div", {className: "depot-pop"},
    el("b", {}, base), el("p", {className: "note"}, "Use one of these for a shipment? It will start from here."),
    ...d.list.map(a => el("div", {className: "dp-row" + (a.status === "available" ? "" : " busy")},
      el("span", {}, el("b", {}, a.name), el("small", {}, `${a.capacity.toLocaleString()} ${UNIT_NAME[a.capacity_unit]}${a.reefer ? " · refrigerated" : ""}${a.adr ? " · ADR" : ""}${a.status === "available" ? "" : ` · ${a.status_label}${a.free_from ? `, free ${dt(a.free_from)}` : ""}`}`)),
      a.status === "available" ? el("button", {className: "btn small primary", onclick: () => { map.closePopup(); useTruck(a); }}, "Use this truck") : "")),
    el("div", {className: "dp-foot"}, el("button", {className: "textbtn", onclick: () => { map.closePopup(); $("tab-flt").click(); }}, "Open Fleet →"),
      el("button", {className: "textbtn", onclick: () => map.closePopup()}, "Not now")));
  L.popup({className: "depot-popup", maxWidth: 320, closeButton: false, offset: [0, 4]}).setLatLng(at).setContent(body).openOn(map);
}
function useTruck(a) { // Plan a shipment from the truck's depot, with the truck chosen for its leg
  const from = placeBy(a.base); if (!from) return;
  $("tab-new").click();
  draft.source = "cargo"; draft.wantTruck = {asset_id: a.asset_id, name: a.name, registration: a.registration, base: a.base, capacity: a.capacity, capacity_unit: a.capacity_unit, payload_kg: a.payload_kg};
  const rest = draft.stops.slice(1).filter(st => st && st.name !== a.base);
  draft.stops = [from, ...(rest.length ? rest : [allPlaces().find(p => p.kind === "warehouse" && p.name !== a.base)])];
  draft.modes = draft.stops.slice(1).map((_, i) => i === 0 ? "truck" : (draft.modes[i] || "truck"));
  if (a.capacity_unit === "pallet") { draft.cargo.unit_type = "pallet"; draft.cargo.units = Math.min(draft.cargo.units || a.capacity, a.capacity); }
  changedDraft(); fit(L.latLngBounds(draft.stops.map(st => [st.lat, st.lon])), 7);
}
function drawFleet(all) { // one mark per depot: its vehicles, and how many are free (the live map shows only depots with a free one)
  const by = {};
  (fleetView?.assets || []).forEach(a => { if (a.record === "vehicle" && a.place) (by[a.base] ||= {place: a.place, list: []}).list.push(a); });
  Object.entries(by).forEach(([base, d]) => { const free = d.list.filter(a => a.status === "available").length;
    if (!all && !free) return;
    const mode = d.list[0].mode;
    const icon = L.divIcon({className: "", iconSize: [34, 20], iconAnchor: [17, -6], html: `<div class="depot-icon${free ? "" : " none"}">${svgIcon(mode)}<b>${free}</b></div>`});
    L.marker([d.place.lat, d.place.lon], {icon, keyboard: false, zIndexOffset: -150})
      .bindTooltip(`<b>${esc(base)}</b><small>${free} of ${d.list.length} free for use</small>${d.list.map(a => `<small>${esc(a.name)} · ${esc(a.status_label)}${a.busy_with ? ` · ${esc(a.busy_with)}` : ""}</small>`).join("")}`, {direction: "top", offset: [0, -4], className: "tip"})
      .on("click", ev => depotPrompt(base, d, ev.latlng)).addTo(shipLayer); });
}

// ---- plan a shipment: choose your own vehicles and booked space for the picked route ----
const fleetCargo = () => draft.source === "stock" ? stockCargo() : draft.cargo;
const fleetKey = x => JSON.stringify([x.id, x.depart_at, x.legs.map(l => l.planned_start), fleetCargo(), draft.needs]);
async function loadCandidates(x) {
  const key = fleetKey(x);
  draft.fleet = {key, offer: null, picks: {}, error: null, done: null, busy: false};
  try { const offer = await fleetSend("POST", "/api/fleet/candidates", {legs: x.legs, cargo: fleetCargo(), needs: draft.needs});
    if (draft.fleet?.key === key) { draft.fleet.offer = offer;
      const want = draft.wantTruck?.asset_id; // came here from "Use this truck": choose it for the first leg it can take
      const leg = want && offer.find(l => l.candidates.some(c => c.asset_id === want && c.ok));
      if (leg) draft.fleet.picks[leg.seq] = want;
      else if (want) draft.fleet.wantWhy = offer.flatMap(l => l.candidates).find(c => c.asset_id === want)?.why_not || "no road leg on this route"; }
  } catch (err) { if (draft.fleet?.key === key) draft.fleet.error = err.message; }
  renderPlanner();
}
function fleetSection(x) {
  if (!draft.fleet || draft.fleet.key !== fleetKey(x)) { loadCandidates(x); return [el("h3", {}, "Your fleet for this route"), el("p", {className: "muted"}, "Checking which of your vehicles are free…")]; }
  const f = draft.fleet;
  if (f.error) return [el("h3", {}, "Your fleet for this route"), el("p", {className: "warn"}, `Could not check your fleet (${f.error}).`)];
  if (!f.offer) return [el("h3", {}, "Your fleet for this route"), el("p", {className: "muted"}, "Checking which of your vehicles are free…")];
  const chosen = leg => leg.candidates.find(c => c.asset_id === f.picks[leg.seq]);
  const cannot = draft.wantTruck && f.wantWhy ? el("p", {className: "warn"}, `${draft.wantTruck.name} cannot take this route: ${f.wantWhy}. Choose another below, or change the route or cargo.`) : "";
  const total = f.offer.reduce((t, leg) => t + (chosen(leg)?.cost ?? leg.market_cost ?? 0), 0), any = f.offer.some(chosen);
  const label = c => `${c.name}${c.registration ? ` (${c.registration})` : ""}${c.record === "vehicle" ? ` · ${c.empty_km ? `${c.empty_km} km from ${c.base}` : `at ${c.base}`}` : ` · ${c.free.toLocaleString()} ${UNIT_NAME[c.capacity_unit]} free`}${c.cost != null ? ` · ${money(c.cost)}` : ""}`;
  return [
    el("h3", {}, "Your fleet for this route", el("span", {}, "optional · unassigned legs use a carrier at the market rate")),
    cannot,
    el("div", {className: "needs"},
      el("label", {className: "check"}, el("input", {type: "checkbox", checked: !!draft.needs.reefer, onchange: e => { draft.needs.reefer = e.target.checked; renderPlanner(); }}), "Needs refrigeration"),
      el("label", {className: "check"}, el("input", {type: "checkbox", checked: !!draft.needs.adr, onchange: e => { draft.needs.adr = e.target.checked; renderPlanner(); }}), "Dangerous goods (ADR)"),
      el("button", {className: "btn small", style: "margin-left:auto", disabled: !f.offer.some(l => l.suggested_id), title: "For each leg: the nearest of your vehicles that fits and is free, or your booked space on that lane",
        onclick: () => { f.picks = Object.fromEntries(f.offer.filter(l => l.suggested_id).map(l => [l.seq, l.suggested_id])); f.done = null; renderPlanner(); }}, "Auto-assign")),
    ...f.offer.map(leg => { const pick = chosen(leg), ok = leg.candidates.filter(c => c.ok), no = leg.candidates.filter(c => !c.ok);
      return el("div", {className: "assign"},
        el("div", {className: "ahead"}, el("span", {className: "mode-ic", innerHTML: svgIcon(leg.mode)}), el("b", {}, `Leg ${leg.seq}`), ` ${leg.from_name} → ${leg.to_name}`),
        el("select", {ariaLabel: `Vehicle or booked space for leg ${leg.seq}`, onchange: e => { f.picks[leg.seq] = e.target.value || null; f.done = null; renderPlanner(); }},
          el("option", {value: "", selected: !pick}, `Carrier at the market rate${leg.market_cost != null ? ` · ${money(leg.market_cost)}` : ""}`),
          ok.length ? el("optgroup", {label: leg.mode === "truck" ? "Your vehicles, free for this leg" : "Yours, with space"}, ok.map(c => el("option", {value: c.asset_id, selected: pick?.asset_id === c.asset_id}, label(c)))) : "",
          no.length ? el("optgroup", {label: "Cannot take it"}, no.map(c => el("option", {value: c.asset_id, disabled: true}, `${c.name} · ${c.why_not}`))) : ""),
        pick?.cost_formula ? el("div", {className: "note"}, `${pick.cost_formula} = ${money(pick.cost)} · estimate`) : "",
        !leg.candidates.length ? el("div", {className: "note"}, leg.mode === "truck" ? "You have no trucks." : `You have no ${leg.mode === "ship" ? "sea" : "air"} space booked from ${leg.from_name} to ${leg.to_name}, and no ${leg.mode} of your own.`) : ""); }),
    any ? el("div", {className: "timing"}, el("div", {}, el("span", {}, "All by carrier"), el("b", {}, money(x.cost, x.currency))),
      el("div", {}, el("span", {}, "With your fleet"), el("b", {}, money(Math.round(total), x.currency))),
      el("div", {className: total > x.cost ? "late" : ""}, el("span", {}, "Difference"), el("b", {}, `${total > x.cost ? "+" : "−"}${money(Math.abs(Math.round(total - x.cost)), x.currency)}`))) : "",
    f.done ? el("div", {className: "submitted"}, el("b", {}, `${f.done.booking_ref} reserved`), `${f.done.bookings.map(b => `${fleetView?.assets.find(a => a.asset_id === b.asset_id)?.name || b.asset_id} for leg ${b.seq}`).join(", ")}. ${f.done.note}`)
      : el("button", {className: "btn", disabled: !any || f.busy, onclick: async () => { f.busy = true; f.error2 = null; renderPlanner();
          try { f.done = await fleetSend("POST", "/api/fleet/reserve", {legs: x.legs, cargo: fleetCargo(), needs: draft.needs, picks: f.picks, label: `${x.legs[0].from_name} → ${x.legs[x.legs.length - 1].to_name}`}); await loadFleet(); }
          catch (err) { f.error2 = err.message; }
          f.busy = false; renderPlanner(); }}, f.busy ? "Reserving…" : "Reserve these for this plan"),
    f.error2 ? el("p", {className: "warn"}, `Could not reserve: ${f.error2}`) : "",
    el("p", {className: "note", style: "margin-top:6px"}, "Greedy suggestion, not an optimiser. Your own cost per km and per day, including the empty run from the depot. Reserving holds the vehicle in PortShift only.")];
}

// ---- planned shipments: approved plans (tentative, nothing booked) ----
function renderPlanned() {
  const host = $("pln"); if (!host) return;
  $("n-pln").textContent = planned.length ? String(planned.length) : "";
  if (!planned.length) {
    host.replaceChildren(el("div", {className: "empty-cta pln-empty"},
      el("h3", {}, "No current planned shipments"),
      el("p", {className: "muted"}, "Plan one yourself, or ask PortShifter to plan it for you from a sentence, for example “Glasgow warehouse to Southampton port, 10 pallets”."),
      el("div", {className: "acts"},
        el("button", {className: "btn small primary", onclick: () => $("tab-new").click()}, "Plan a shipment"),
        el("button", {className: "btn small", onclick: () => openBot()}, "Ask PortShifter"))));
    return;
  }
  const cargoText = c => !c ? "Cargo not given" : `${c.units ?? ""} ${c.unit_type ? c.unit_type + (c.units === 1 ? "" : "s") : ""}${c.weight_kg ? ` · ${Math.round(c.weight_kg).toLocaleString()} kg` : ""}`.trim();
  const showOnMap = x => { const pts = x.legs.flatMap(l => (l.geometry && l.geometry.length ? l.geometry : [[l.from_lat, l.from_lon], [l.to_lat, l.to_lon]])).filter(p => p && p[0] != null);
    if (pts.length) { tab("map"); refresh(); map.fitBounds(pts, {padding: [60, 60]}); } };
  host.replaceChildren(
    el("p", {className: "note"}, "Approved plans. Tentative: nothing is booked. Costs are estimates."),
    ...planned.slice().reverse().map(x => {
      const lv = x.risk?.level || 0, first = x.legs[0], last = x.legs[x.legs.length - 1];
      return el("article", {className: "pln-card box"},
        el("div", {className: "pln-head"},
          el("b", {}, x.plan_id), el("span", {className: "pln-status"}, cap(x.status || "tentative")),
          x.source ? (src => el("span", {className: "pln-src", title: src}, src))(x.source === "planner" ? "Plan a shipment" : x.source === "dispatch" ? `Warehouse dispatch${x.order_id ? ` ${x.order_id}` : ""}` : "Ask PortShifter") : "",
          el("span", {className: "v"}, x.cost == null ? "no rate" : money(x.cost, x.currency))),
        el("div", {className: "pln-title"}, x.label || `${first.from_name} to ${last.to_name}`),
        el("div", {className: "muted"}, `${x.route_label || "Route"} · ${cargoText(x.cargo)}${x.km ? ` · ${Math.round(x.km).toLocaleString()} km` : ""}${x.hours ? ` · ${durText(x.hours)}` : ""}`),
        (x.depart_at || x.arrive_by || x.when?.text) ? el("div", {className: "pln-when"},
          x.depart_at ? el("span", {}, `Leaves ${dt(x.depart_at)}`) : "",
          x.arrive_by ? el("span", {className: x.slack_hours < 0 ? "late" : ""}, `Arrive by ${dt(x.arrive_by)}${x.slack_hours == null ? "" : x.slack_hours < 0 ? ` · ${spanText(x.slack_hours)} late` : ` · ${spanText(x.slack_hours)} to spare`}`) : "",
          !x.depart_at && !x.arrive_by && x.when?.text ? el("span", {}, x.when.text) : "") : "",
        lv ? el("div", {className: "why-level", style: `margin:8px 0 0;border-left:3px solid ${COLORS[lv]}`}, el("b", {}, `Risk ${lv} · ${NAMES[lv]}`), x.risk.reason ? ` ${x.risk.reason}` : "") : "",
        el("ol", {className: "journey"},
          el("li", {}, el("b", {}, first.from_name), el("span", {className: "time"}, `Leaves ${dt(first.planned_start)}`)),
          ...x.legs.map((l, i) => el("li", {className: i === x.legs.length - 1 ? "end" : ""}, el("b", {}, l.to_name),
            el("span", {className: "time"}, `${i === x.legs.length - 1 ? "Arrives" : "ETA"} ${dt(l.planned_end)} · by ${l.mode}`)))),
        el("div", {className: "acts"},
          el("button", {className: "btn small", onclick: () => showOnMap(x)}, "Show on map"),
          el("span", {className: "muted"}, x.approved_at ? `Approved ${span(x.approved_at)} ago` : "")));
    }));
}

// ---- what if: a hypothetical disruption run against the fleet. Nothing is saved; the map shows the fleet as it would be ----
let whatIf = null, realShips = null; // whatIf: {question, state: working | done | error, data, error}
const lvlChip = n => el("span", {className: "lv", style: `--lv:${COLORS[n] || COLORS[0]}`}, n ? `${n} ${NAMES[n]}` : NAMES[0]);
function closePanels(except) {
  if (except !== "proposal" && proposal) { proposal = null; renderProposal(); }
  if (except !== "brief" && brief) { clearInterval(brief.timer); brief = null; renderBriefing(); }
}
async function askWhatIf(question) {
  if (selected) deselect();
  if (view !== "map") $("tab-map").click();
  closePanels("whatif");
  if (realShips) { ships = realShips; realShips = null; }
  whatIf = {question, state: "working", data: null, error: null}; renderWhatIf();
  try {
    const res = await fetch("/api/whatif", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({message: question, preferences: limits})});
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`);
    if (!whatIf || whatIf.question !== question) return;
    whatIf.data = body; whatIf.state = "done";
    realShips = ships; ships = body.ships; // the map and the list now show the fleet as it would be
    refresh(); renderWhatIf();
    const e = body.event; map.invalidateSize(); // keep the event clear of the left panel and of this panel on the right
    map.fitBounds(L.latLng(e.lat, e.lon).toBounds(Math.max(e.radius_km, 150) * 5000), {paddingTopLeft: [430, 90], paddingBottomRight: [Math.min(640, $("whatif").offsetWidth + 60), 90], maxZoom: 7});
    if (botOpen) botSay(`${e.summary} ${body.totals.worse ? `${body.totals.worse} shipment${body.totals.worse === 1 ? " gets" : "s get"} worse` : "No shipment gets worse"}${body.totals.newly_critical ? `, ${body.totals.newly_critical} to Critical` : ""}. The map shows the fleet as it would be. This is hypothetical: nothing was saved.`);
  } catch (err) { if (whatIf) { whatIf.state = "error"; whatIf.error = err.message; renderWhatIf(); } if (botOpen) botSay(err.message); }
}
async function exitWhatIf() {
  whatIf = null; hoverId = null;
  if (realShips) { ships = realShips; realShips = null; try { ships = await getJSON("/api/shipments"); } catch { /* keep what we had */ } }
  renderWhatIf(); refresh();
}
function drawWhatIf() {
  const e = whatIf?.data?.event; if (!e) return;
  L.circle([e.lat, e.lon], {radius: e.radius_km * 1000, color: css("--whatif"), weight: 2.5, dashArray: "3 7", fillColor: css("--whatif"), fillOpacity: 0.16, interactive: false}).addTo(eventLayer);
  L.marker([e.lat, e.lon], {icon: L.divIcon({className: "", iconSize: [26, 26], html: `<div class="whatif-icon">?</div>`}), keyboard: false, zIndexOffset: 900})
    .bindTooltip(`What if: ${esc(e.type)} at ${esc(e.location)}`, {permanent: true, direction: "top", offset: [0, -14], className: "stop-label whatif-label"}).addTo(eventLayer);
}
function renderWhatIf() {
  const host = $("whatif"), w = whatIf;
  $("ws").classList.toggle("whatif-on", !!w && w.state === "done");
  host.hidden = !w; if (!w) return;
  const head = el("div", {className: "phead"},
    el("div", {}, el("div", {className: "eyebrow whatif-tag"}, "What if · hypothetical · nothing is saved"),
      el("h2", {}, w.data ? `${cap(w.data.event.type)} at ${w.data.event.location}` : "Working it out"), el("p", {className: "note"}, `You asked: "${w.question}"`)),
    el("button", {className: "iconbtn", ariaLabel: "Leave the what-if", title: "Leave the what-if (Esc)", onclick: exitWhatIf}, "×"));
  if (w.state === "working") return host.replaceChildren(head, el("ol", {className: "work"},
    el("li", {}, "Read the question", el("span", {className: "note"}, "place, kind of disruption, when and for how long")),
    el("li", {className: "doing"}, "Scoring the whole fleet again with it", el("span", {className: "note"}, "the same risk job, costing and planner as for real events"))));
  if (w.state === "error") return host.replaceChildren(head, el("p", {className: "warn", style: "margin:12px 16px"}, w.error),
    el("div", {className: "pfoot"}, el("button", {className: "btn small", onclick: exitWhatIf}, "Close")));
  const d = w.data, e = d.event, t = d.totals;
  host.replaceChildren(head,
    el("div", {className: "pnote"},
      el("p", {}, e.summary, " ", el("span", {className: "note"}, `${dt(e.window_start)} to ${dt(e.window_end)} · treated as confirmed · read by ${e.read_by}`)),
      el("div", {className: "timing", style: "margin-top:10px"},
        el("div", {className: t.worse ? "late" : ""}, el("span", {}, "Shipments that get worse"), el("b", {}, String(t.worse))),
        el("div", {className: t.newly_critical ? "late" : ""}, el("span", {}, "Newly Critical"), el("b", {}, String(t.newly_critical))),
        el("div", {}, el("span", {}, "Suggested changes"), el("b", {}, `${t.plan_changes} · ${money(t.plan_cost)}`))),
      el("div", {className: "lvrow"}, el("span", {className: "note"}, "Fleet now"), ...[5, 4, 3, 2, 1].map(n => el("span", {className: "lvn"}, el("i", {style: `background:${COLORS[n]}`}), String(d.levels_before[n]))),
        el("span", {className: "note", style: "margin-left:10px"}, "With it"), ...[5, 4, 3, 2, 1].map(n => el("span", {className: "lvn" + (d.levels_after[n] !== d.levels_before[n] ? " moved" : "")}, el("i", {style: `background:${COLORS[n]}`}), String(d.levels_after[n]))))),
    ...(d.changed.length ? d.changed.map(c => el("div", {className: "prow wrow", onmouseenter: () => { hoverId = c.shipment_id; draw(); }, onmouseleave: () => { hoverId = null; draw(); }},
      el("span", {className: "mode-ic", innerHTML: svgIcon(c.mode)}),
      el("div", {},
        el("div", {className: "pt"}, el("b", {}, c.shipment_id), el("span", {className: "note"}, `${c.origin} → ${c.destination} · ${c.cargo}`)),
        el("div", {className: "pact"}, lvlChip(c.from), " → ", lvlChip(c.to), c.to === c.from ? el("span", {className: "note"}, " same level, now also on this event") : ""),
        el("div", {className: "note"}, c.reason),
        c.choice ? el("div", {className: "note"}, el("b", {}, c.plan_status === "change" ? "I would: " : c.plan_status === "needs_your_call" ? "Needs your call: " : "No better option: "), c.choice.label,
          c.choice.resulting_risk ? ` · risk after ${c.choice.resulting_risk} ${NAMES[c.choice.resulting_risk]}` : "") : ""),
      el("span", {className: "pcost"}, c.choice && c.plan_status === "change" ? `+${money(c.choice.extra_cost)}` : c.wait_out ? `wait ${money(c.wait_out.cost)}` : "")))
      : [el("p", {className: "muted", style: "padding:12px 16px"}, "No shipment in the demo fleet passes through it in that window.")]),
    el("div", {className: "pnote"}, el("p", {className: "note"}, d.note)),
    el("div", {className: "pfoot"},
      el("button", {className: "btn small primary", onclick: () => { openBot(); $("bot-msg").value = "What if "; $("bot-msg").focus(); }}, "Try another"),
      el("button", {className: "btn small", onclick: exitWhatIf}, "Back to the real fleet")));
}

// ---- briefing: what the agent found and proposes, step by step, counted from the tables as they are now ----
let brief = null; // {state: working | done | error, data, shown, timer}
async function openBriefing() {
  if (selected) deselect();
  if (whatIf) await exitWhatIf();
  if (view !== "map") $("tab-map").click();
  closePanels("brief");
  if (brief) clearInterval(brief.timer);
  brief = {state: "working", data: null, shown: 0, timer: null}; renderBriefing();
  try {
    const d = await postJSON("/api/briefing", {preferences: limits});
    if (!brief) return;
    brief.data = d; brief.state = "done";
    if (calm()) brief.shown = d.steps.length;
    else brief.timer = setInterval(() => { if (!brief || ++brief.shown >= brief.data.steps.length) clearInterval(brief?.timer); renderBriefing(); }, 520);
  } catch (err) { if (brief) { brief.state = "error"; brief.error = err.message; } }
  renderBriefing();
}
function briefOpen(id, options) { // a shipment from the briefing opens beside it: the briefing stays where it is
  if (options) ptab = "plan";
  select(id); renderBriefing();
}
function closeBriefing() { if (brief) clearInterval(brief.timer); brief = null; renderBriefing(); }
function renderBriefing() {
  const host = $("briefing"), b = brief;
  host.hidden = !b; if (!b) return;
  const head = el("div", {className: "phead"},
    el("div", {}, el("div", {className: "eyebrow"}, "PortShifter · briefing"), el("h2", {}, "Here is where things stand"),
      el("p", {className: "note"}, b.data ? `From the tables as of ${dt(b.data.as_of)} · ${b.data.source === "databricks" ? "Databricks" : "this server"}` : "Reading the tables…")),
    el("button", {className: "iconbtn", ariaLabel: "Close the briefing", onclick: closeBriefing}, "×"));
  if (b.state === "working") return host.replaceChildren(head, el("ol", {className: "work"}, el("li", {className: "doing"}, "Putting it together")));
  if (b.state === "error") return host.replaceChildren(head, el("p", {className: "warn", style: "margin:12px 16px"}, `Could not build the briefing (${b.error}).`));
  const d = b.data, all = b.shown >= d.steps.length, dec = d.decision;
  const planItems = d.steps.find(x => x.key === "plan")?.items || [];
  const item = (s, it) => s.key === "sources"
    ? el("button", {className: "bitem", onclick: () => { closeBriefing(); $("tab-evt").click(); openEvent(it.event_id); }}, el("span", {className: `badge badge-${it.status}`}, it.status), el("span", {}, it.text),
        el("span", {className: "note"}, `${it.basis} · ${it.shipments} shipment${it.shipments === 1 ? "" : "s"}${it.is_fixture ? " · sample" : ""}`))
    : s.key === "score"
    ? el("button", {className: "bitem" + (selected === it.shipment_id ? " on" : ""), onclick: () => briefOpen(it.shipment_id, s.key === "plan")}, lvlChip(it.level), el("span", {}, el("b", {}, it.shipment_id), ` ${it.text}`), el("span", {className: "note"}, it.reason))
    : el("button", {className: "bitem" + (selected === it.shipment_id ? " on" : ""), onclick: () => briefOpen(it.shipment_id, s.key === "plan")}, lvlChip(it.level), el("span", {}, el("b", {}, it.shipment_id), ` ${it.text}`),
        it.status === "needs_your_call" ? el("span", {className: "note"}, "needs your call") : it.cost ? el("span", {className: "note loss"}, `cost ${lossText(it.cost)}`) : el("span", {className: "note"}, "no cost"));
  host.replaceChildren(head,
    el("ol", {className: "work brief"}, d.steps.slice(0, b.shown + (all ? 0 : 1)).map((s, i) => el("li", {className: i >= b.shown ? "doing" : ""},
      s.title, s.at ? el("span", {className: "when"}, `${span(s.at)} ago`) : "",
      i >= b.shown ? "" : el("span", {className: "note"}, s.detail),
      i >= b.shown ? "" : s.action === "check" ? el("button", {className: "textbtn", onclick: () => { closeBriefing(); openBot("Check for new disruptions"); }}, "Run a live check now →") : "",
      i >= b.shown || !s.items.length ? "" : el("div", {className: "bitems"}, s.items.map(it => item(s, it)))))),
    all ? el("div", {className: "pnote"},
      el("b", {className: "choose"}, "Your call: choose one"),
      el("div", {className: "choices", role: "radiogroup", ariaLabel: "What to do about the disruptions"},
        el("button", {type: "button", className: "choice", role: "radio", ariaChecked: String(b.choice === "wait"), onclick: () => { b.choice = "wait"; renderBriefing(); }},
          el("span", {className: "radio"}), el("b", {}, "Do nothing: wait it out"),
          el("span", {className: "loss"}, `Estimated loss: ${lossText(dec.wait_out)}`),
          el("small", {}, `${d.wait_out.rows.length} shipment${d.wait_out.rows.length === 1 ? "" : "s"} held, delays up to ${d.wait_out.longest_days} day${d.wait_out.longest_days === 1 ? "" : "s"}`)),
        el("button", {type: "button", className: "choice", role: "radio", ariaChecked: String(b.choice === "plan"), onclick: () => { b.choice = "plan"; renderBriefing(); }},
          el("span", {className: "radio"}), el("b", {}, `My plan: ${dec.changes} change${dec.changes === 1 ? "" : "s"}`),
          el("span", {className: "loss"}, `Estimated cost: ${lossText(dec.cost)}`),
          el("small", {className: dec.wait_out > dec.cost ? "gain" : ""}, dec.wait_out > dec.cost ? `${money(dec.wait_out - dec.cost)} less than waiting` : `${money(dec.cost - dec.wait_out)} more than waiting`,
            dec.needs_your_call ? ` · ${dec.needs_your_call} need${dec.needs_your_call === 1 ? "s" : ""} your call` : ""))),
      !b.choice ? el("p", {className: "note"}, "Pick one to see what it means, shipment by shipment. Both figures are costs to you, and estimates.") : "",
      b.choice === "wait" ? el("div", {className: "waits"},
        el("div", {className: "whead"}, el("b", {}, "If you wait it out"), el("span", {className: "note"}, `${d.wait_out.rows.length} shipment${d.wait_out.rows.length === 1 ? "" : "s"} held${d.wait_out.tentative ? ` · ${d.wait_out.tentative} tentative` : ""}`)),
        ...d.wait_out.rows.map(r => el("button", {className: "bitem wait" + (selected === r.shipment_id ? " on" : ""), onclick: () => briefOpen(r.shipment_id, false)},
          lvlChip(r.level), el("span", {}, el("b", {}, r.shipment_id), ` ${r.text}`),
          el("span", {className: "delay"}, `+${r.delay_days} day${r.delay_days === 1 ? "" : "s"}`, r.tentative ? el("span", {className: "badge badge-out", title: r.why_tentative}, "tentative") : ""),
          el("span", {className: "note"}, `arrives ${dt(r.eta_if_waiting)} instead of ${dt(r.eta)} · ${r.events.join(", ")}${r.until ? ` until ${dt(r.until)}` : ""} · `,
            el("span", {className: "loss"}, `estimated loss ${lossText(r.cost)}`), r.tentative ? el("em", {}, ` · tentative: ${r.why_tentative}`) : ""))),
        el("div", {className: "sum"}, el("span", {}, "Total if you wait"), el("span", {className: "loss"}, `Estimated loss: ${lossText(d.wait_out.total_cost)}`)),
        el("p", {className: "note"}, d.wait_out.note),
        el("div", {className: "cacts"}, el("button", {className: "btn small", onclick: closeBriefing}, "Keep everything as planned"),
          el("span", {className: "note"}, "Nothing to approve: the shipments stay as they are."))) : "",
      b.choice === "plan" ? el("div", {className: "waits"},
        el("div", {className: "whead"}, el("b", {}, "If you take my plan"), el("span", {className: "note"}, `${planItems.length} shipment${planItems.length === 1 ? "" : "s"} touched`)),
        ...planItems.map(it => el("button", {className: "bitem wait" + (selected === it.shipment_id ? " on" : ""), onclick: () => briefOpen(it.shipment_id, true)},
          lvlChip(it.level), el("span", {}, el("b", {}, it.shipment_id), ` ${it.text}`),
          it.status === "needs_your_call" ? el("span", {className: "badge badge-out"}, "needs your call") : it.cost ? el("span", {className: "loss"}, `cost ${lossText(it.cost)}`) : el("span", {className: "note"}, "no cost"))),
        el("div", {className: "sum"}, el("span", {}, "Total for the plan"), el("span", {className: "loss"}, `Estimated cost: ${lossText(dec.cost)}`)),
        el("div", {className: "cacts"}, el("button", {className: "btn small primary", onclick: () => { closeBriefing(); fleetPlan(""); }}, "Review and approve this plan"),
          el("span", {className: "note"}, "Opens every change for you to tick or untick. Nothing changes until you approve."))) : "",
      el("p", {className: "note"}, d.note)) : "",
    all ? el("div", {className: "pfoot"},
      el("button", {className: "btn small", onclick: () => { closeBriefing(); openBot(); $("bot-msg").value = "What if "; $("bot-msg").focus(); }}, "Ask a what-if"),
      el("button", {className: "btn small", onclick: closeBriefing}, "Close")) : "");
}
$("brief-open").onclick = openBriefing;
addEventListener("keydown", e => { if (e.key === "Escape" && whatIf && !selected) exitWhatIf(); });

// ---- views (left navigation) ----
const TABS = ["map", "evt", "new", "flt", "pln", "ins", "rat"];
function tab(which) {
  view = which;
  $("ws").classList.toggle("wide-left", which === "ins"); // Insights gets a wider panel over the map
  for (const t of TABS) {
    $("tab-" + t).setAttribute("aria-selected", String(t === which));
    $("side-" + t).hidden = t !== which;
  }
}
for (const t of TABS) $("tab-" + t).onclick = () => { focusEvent = null; hoverId = null; if (t === "ins" || t === "new" || t === "pln" || t === "rat" || t === "flt") { selected = null; detail = null; } tab(t); refresh(); map.invalidateSize(); };
for (const [id, table, key] of [["sort-map", SORT_SHIP, "map"], ["sort-evt", SORT_EVT, "evt"]]) {
  $(id).replaceChildren(...Object.entries(table).map(([k, [label]]) => el("option", {value: k, selected: sort[key] === k}, label)));
  $(id).onchange = e => { sort[key] = e.target.value; refresh(); };
}

// ---- ask agent: one thread per shipment; options can be submitted from the chat ----
const QUICK = [["Why is this disrupted?", "Summarise why this shipment is at risk and what the disruption is"],
  ["Lower risk, keep cost low", "I want to lower the risk of disruption but keep the cost low at the same time"],
  ["Reroute it", "Suggest a way to reroute this shipment"],
  ["Cost to move the date", "What does it cost to move this to another date?"]];
let logFor = null, chatOptions = null, limitsOpen = false; // which shipment's thread is shown; the options last offered in it

function placeChat() {
  const log = $("log");
  if (logFor !== selected) { // swap threads when the shipment changes
    if (logFor) logs[logFor] = [...log.childNodes];
    log.replaceChildren(...(selected && logs[selected] || [])); logFor = selected; chatOptions = null;
  }
  if (!selected) return;
  $("msg").placeholder = `Ask about ${selected}, or say what you want…`;
  $("pref-chip").replaceChildren(el("span", {className: "edit"}, limitsOpen ? "Done" : "Change"), "Planning for: ", el("b", {}, presetName()), ` · ${limitsText()}`);
  $("pref-chip").setAttribute("aria-expanded", String(limitsOpen));
  const wasMeaning = !!$("pref-edit").querySelector(".meaning details[open]");
  $("pref-edit").hidden = !limitsOpen;
  $("pref-edit").replaceChildren(...(limitsOpen ? [...limitsEditor("chat-"), el("p", {className: "note"}, "PortShifter plans inside these limits. Change them and it offers the options again.")] : []));
  if (wasMeaning && limitsOpen) $("pref-edit").querySelector(".meaning details").open = true;
  $("quick").replaceChildren(...QUICK.map(([label, message]) => el("button", {type: "button", onclick: () => ask(message)}, label)));
  if (!log.children.length) log.append(el("div", {className: "intro"}, el("b", {}, "Ask about this shipment"),
    "Ask why it is disrupted, say what you want (\"lower the risk but keep the cost low\"), or ask for a reroute. Pick an option and submit it here. Or hand over the whole fleet: \"optimise everything for the least cost\". Every answer cites its sources."));
}
$("pref-chip").onclick = () => { limitsOpen = !limitsOpen; placeChat(); };
let reofferSeq = 0;
async function reoffer() { // limits changed while options were on offer in the chat: offer them again under the new limits
  if (ptab !== "chat" || !selected || !chatOptions) return;
  const id = selected, seq = ++reofferSeq;
  try {
    const o = await postJSON("/api/options", {shipment_id: id, preferences: limits});
    if (selected !== id || seq !== reofferSeq) return;
    chatOptions = o; opts = null;
    $("log").querySelector(".msg.reoffer")?.remove(); // one refreshed offer, not a pile of them
    const m = say(el("span", {className: "cites", style: "margin:0 0 6px"}, `Planning for ${presetName()}: ${limitsText()}.`),
      o.options.length > 1 ? "Here are the options again under your new limits." : "There is nothing to move on this route.", o.options.length > 1 ? optionLines(o) : "");
    m.classList.add("reoffer"); $("log").append(m); $("log").scrollTop = 1e9;
  } catch { /* the chip already shows the new limits; the next question uses them */ }
}

const say = (...kids) => el("div", {className: "msg"}, el("span", {className: "by"}, "PORTSHIFTER"), ...kids);
function optionLines(o) { // options offered in the chat, each with its own submit button
  const rec = recommend(o);
  return el("span", {className: "opts"}, o.options.map(x => el("span", {className: "optline"},
    el("b", {}, x.label, " ", x.id === rec ? el("span", {className: "badge badge-rec"}, `Best for ${presetName()}`) : "", x.within_limits ? "" : el("span", {className: "badge badge-out"}, "Outside limits")),
    el("small", {}, optFacts(x, o.currency), detail && x.delay_hours ? ` · arrives ${dt(new Date(+new Date(detail.eta) + x.delay_hours * 36e5).toISOString())}` : ""),
    x.cost_lines?.length ? el("details", {className: "working"}, el("summary", {}, `How ${money(x.extra_cost, o.currency)} was worked out`),
      ...x.cost_lines.map(l => costLine(l, o.currency)), el("small", {className: "src"}, x.cost_note)) : "",
    el("button", {className: "btn small", onclick: async e => { const b = e.currentTarget; b.disabled = true;
      try { await submit(x); b.textContent = "Submitted"; $("log").append(say(`Submitted "${x.label}" for ${selected}. It is recorded as tentative: nothing is booked or sent to a carrier.`)); $("log").scrollTop = 1e9; }
      catch { b.disabled = false; b.textContent = "Try again"; } }}, "Submit"))));
}

// "optimise everything", "reschedule the whole fleet for the least cost", "sort out all shipments under EUR 10,000"
const FLEET_RE = /\b(optimi[sz]e|reschedul\w*|rerout\w*|re-rout\w*|plan|fix|sort out|handle|resolve|deal with)\b[^.?!]*\b(everything|every shipment|all( of)?( the| my)? shipments|all of (it|them)|the (whole |entire )?fleet|whole fleet|them all|it all)\b/i;
function fleetGoal(text) {
  const risk = /(low|least|less|minim|reduc|avoid|safe)\w*\W+(\w+\W+){0,3}(risk|disruption)|safest|safer/i.test(text);
  const cost = /(low|least|cheap|minim|less|reduc)\w*\W+(\w+\W+){0,3}cost|cheap|budget|save money/i.test(text);
  const m = text.match(/(?:under|below|within|budget(?: of)?|max(?:imum)?(?: of)?|no more than|up to)\s*(?:eur|€|euros?)?\s*([\d][\d,.]*)\s*(k)?/i);
  const total = m ? parseFloat(m[1].replace(/,/g, "")) * (m[2] ? 1000 : 1) : null;
  return {goal: risk && !cost ? "low_risk" : cost && !risk ? "low_cost" : risk && cost ? "balanced" : PRESETS[preset] ? preset : "balanced", total: total > 0 ? total : null};
}
let proposal = null; // {request, data, picked: Set, shown, state: working | review | approving | done, error}
async function fleetPlan(text = "", read = null) { // read: the request as the request reader understood it
  const mine = fleetGoal(text);
  const goal = read ? ({least_cost: "low_cost", least_risk: "low_risk", balanced: "balanced"}[read.goal] || (PRESETS[preset] ? preset : "balanced")) : mine.goal;
  const total = read ? read.budget_eur : mine.total;
  const prefs = limits; // the goal says what to aim for; the operator's own limits still say what is acceptable
  if (selected) deselect();
  proposal = {kind: "fleet", request: text || `Plan the fleet for ${PRESETS[goal]?.label.toLowerCase() || "balanced"}`, data: null, picked: new Set(), shown: 0, state: "working", error: null};
  renderProposal();
  try {
    const d = await postJSON("/api/plan-all", {preferences: prefs, goal, max_total_cost: total});
    proposal.data = d; proposal.picked = new Set(d.rows.filter(r => r.status === "change").map(r => r.shipment_id));
    return stepThrough(d);
  } catch (err) { proposal.error = err.message; proposal.state = "review"; }
  renderProposal();
}
async function approveProposal() { // approved: PortShifter records each item and says what it is doing
  const p = proposal, isNew = p.kind === "new";
  const rows = isNew ? p.data.shipments.filter(x => p.picked.has(x.ref)) : p.data.rows.filter(r => p.picked.has(r.shipment_id));
  p.state = "approving"; p.log = [];
  let ok = 0;
  for (const [i, r] of rows.entries()) {
    const name = isNew ? `${r.ref} · ${r.label}` : `${r.shipment_id} · ${r.choice.label}`;
    p.log.push({text: `Recording ${name} (${i + 1} of ${rows.length})`, state: "doing"}); renderProposal();
    try {
      if (isNew) planned.push(...await postJSON("/api/planned", {plans: [{ref: r.ref, label: r.label, cargo: r.cargo, when: r.when, route: r.routes.find(y => y.id === p.route[r.ref])}]}));
      else decisions.push(await postJSON("/api/decisions", {shipment_id: r.shipment_id, option: r.choice, preset: p.data.goal}));
      ok++; p.log[i] = {text: `Recorded ${name} as tentative`, state: "ok"};
    } catch (err) { p.log[i] = {text: `Could not record ${name} (${err.message})`, state: "bad"}; }
    await pause(320); renderProposal();
  }
  p.log.push({text: isNew ? "Added them to Planned shipments and drew their routes on the map" : "Updated each shipment and Insights with the approved change", state: "ok"});
  p.state = "done"; p.approved = ok; p.failed = rows.length - ok;
  renderProposal(); draw(); if (summary) renderInsights(summary);
  if (botOpen) botSay(`Done. I recorded ${ok} ${isNew ? `planned shipment${ok === 1 ? "" : "s"}` : `change${ok === 1 ? "" : "s"}`} as tentative${p.failed ? `; ${p.failed} could not be recorded` : ""}. Nothing is booked and no carrier has been contacted.`,
    isNew && ok ? chipRow([["Open Planned shipments", "The plans you approved, with cargo, timing and route", () => $("tab-pln").click()]]) : "");
}
const stepList = (steps, upto, working) => el("ol", {className: "work"}, steps.slice(0, upto).map((st, i) =>
  el("li", {className: working && i === upto - 1 ? "doing" : st.state || "ok"}, st.text, st.detail ? el("span", {className: "note"}, st.detail) : "")));
const closeBtn = close => el("button", {className: "iconbtn", ariaLabel: "Close", title: "Close without approving", onclick: close, innerHTML: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/></svg>'});
function renderNewProposal(host, p, close) {
  const d = p.data, cur = d.currency, working = p.state === "working";
  const head = el("div", {className: "phead"},
    el("div", {}, el("div", {className: "eyebrow"}, working ? "PortShifter · working" : p.state === "approving" ? "PortShifter · recording" : p.state === "done" ? "PortShifter · done" : "PortShifter · needs your approval"),
      el("h2", {}, "Plans for your new shipments"), el("p", {className: "note"}, `You asked: "${p.request}"`)), closeBtn(close));
  if (working) return host.replaceChildren(head, stepList(d.steps, p.shown + 1, true));
  const chosen = d.shipments.filter(x => p.picked.has(x.ref)), routeOf = x => x.routes.find(y => y.id === p.route[x.ref]);
  const total = chosen.reduce((t, x) => t + routeOf(x).cost, 0), locked = p.state !== "review";
  const plans = d.shipments.filter(x => !x.problem), isLate = x => !!routeOf(x)?.late;
  const dated = plans.filter(x => routeOf(x)?.slack_hours != null), onTime = dated.filter(x => !isLate(x)).length;
  const view = x => { p.focus = p.focus === x.ref ? null : x.ref; renderProposal(); draw(); const r = routeOf(x);  // open a plan: its route on the map, its stops and times
    if (p.focus && r) fit(r.legs.flatMap(l => l.geometry), 8); };
  const row = x => { const r = routeOf(x);
    if (x.problem) return el("div", {className: "prow needs_your_call"}, el("span", {}), el("div", {className: "pmain"}, el("div", {className: "pt"}, el("b", {}, x.ref), el("span", {className: "note"}, x.text)), el("div", {className: "out"}, x.problem)), el("span", {}));
    const open = p.focus === x.ref, lvl0 = r.risk.level || 0;
    return el("div", {className: "prow" + (open ? " viewing" : "") + (isLate(x) ? " needs_your_call" : "")},
      el("input", {type: "checkbox", checked: p.picked.has(x.ref), disabled: locked, ariaLabel: `Include ${x.ref}`, onchange: e => { e.target.checked ? p.picked.add(x.ref) : p.picked.delete(x.ref); renderProposal(); draw(); }}),
      el("div", {className: "pmain"},
        el("div", {className: "pt"}, el("button", {className: "textbtn planref", ariaExpanded: String(open), title: "See this plan on the map, with its stops and times", onclick: () => view(x)}, `${x.ref} · ${x.label}`),
          isLate(x) ? el("span", {className: "badge badge-out"}, "Cannot meet the deadline") : "",
          p.state === "done" && p.picked.has(x.ref) ? el("span", {className: "badge badge-rec"}, "Recorded") : ""),
        el("div", {className: "psum"}, el("span", {}, r.label), el("span", {}, `leaves ${dt(r.depart_at)}`), el("span", {}, `arrives ${dt(r.eta)}`),
          el("span", {}, el("span", {className: "dot", style: `background:${COLORS[lvl0]}`}), ` ${lvl0} ${NAMES[lvl0]}`),
          el("button", {className: "textbtn", onclick: () => view(x)}, open ? "Hide" : "View on map →")),
        isLate(x) ? el("div", {className: "out"}, `${r.late} Left unticked: tick it to save it anyway, or pick a later date.`) : "",
        open ? el("ol", {className: "journey pjourney"},
          el("li", {}, el("b", {}, r.legs[0].from_name), el("span", {className: "time"}, `Leaves ${dt(r.legs[0].planned_start)}`)),
          ...r.legs.map((l, i) => el("li", {className: [l.event_ids?.length ? "disrupted" : "", i === r.legs.length - 1 ? "end" : ""].join(" ").trim()}, el("b", {}, l.to_name),
            el("span", {className: "time"}, `${i === r.legs.length - 1 ? "Arrives" : "ETA"} ${dt(l.planned_end)} · by ${l.mode}, ${Math.round(l.km).toLocaleString()} km, ${durText(l.hours)} · ${money(l.cost, cur)}`),
            l.event_ids?.length ? el("span", {className: "flag"}, `Disruption on this leg: ${l.event_ids.map(id => events.find(v => v.event_id === id)?.location || id).join(", ")}`) : ""))) : "",
        el("div", {className: "note"}, `${cargoText(x.cargo)} · ${whenText(x.when)} · this route leaves ${dt(r.depart_at)}`
          + (r.slack_hours != null ? (r.slack_hours >= 0 ? ` and arrives ${durText(r.slack_hours)} before the deadline` : ` and arrives ${durText(-r.slack_hours)} after the deadline`) : "")),
        el("div", {className: "proutes", role: "radiogroup", ariaLabel: `Route for ${x.ref}`}, x.routes.map(y => { const lvl = y.risk.level || 0;
          return el("button", {className: "proute", role: "radio", ariaChecked: String(y.id === r.id), disabled: locked, onclick: () => { p.route[x.ref] = y.id; renderProposal(); draw(); }},
            el("span", {className: "radio"}), el("b", {}, y.label, y.id === x.recommended_id ? el("span", {className: "badge badge-rec"}, "Suggested") : ""),
            el("span", {className: "pcost"}, money(y.cost, cur)),
            el("small", {}, `${Math.round(y.km).toLocaleString()} km · ${durText(y.hours)} · arrives ${dt(y.eta)} · `, el("span", {className: "dot", style: `background:${COLORS[lvl]}`}), ` ${lvl} ${NAMES[lvl]}`,
              y.within_limits ? "" : el("span", {className: "out"}, ` · ${cap(y.violations[0] || "outside your limits")}`))); })),
        r.risk.level > 1 ? el("div", {className: "note"}, `Risk on the chosen route: ${r.risk.reason}.`) : "",
        ...x.same_lane.map(sl => el("div", {className: "note"}, el("b", {}, `${sl.shipment_id} already runs this lane`), ` (${sl.cargo}, leaves ${dt(sl.departs)}). PortShift has no capacity data, so check for room before adding a vehicle.`)),
        el("details", {className: "working"}, el("summary", {}, `How ${money(r.cost, cur)} was worked out`),
          ...r.legs.flatMap((l, i) => [el("div", {className: "cgroup"}, `Leg ${i + 1} · ${l.from_name} to ${l.to_name} · by ${l.mode}`), ...l.cost_lines.map(c => costLine(c, cur))]), el("small", {className: "src"}, r.cost_note))),
      el("b", {className: "pcost"}, money(r.cost, cur))); };
  host.replaceChildren(head,
    el("details", {className: "pwork"}, el("summary", {}, `What PortShifter did: ${d.steps.length} steps, ${d.shipments.reduce((t, x) => t + x.routes.length, 0)} routes priced and scored`), stepList(d.steps, d.steps.length)),
    el("div", {className: "pall"}, el("b", {}, `${plans.length} shipment${plans.length === 1 ? "" : "s"} planned`), ` · ${money(plans.reduce((t, x) => t + routeOf(x).cost, 0), cur)} in all (estimate)`,
      dated.length ? ` · ${onTime} of ${dated.length} meet their arrive-by date` : "", el("span", {className: "note"}, " · open a plan to see it on the map")),
    el("div", {className: "prows"}, d.shipments.map(row)),
    p.log?.length ? el("div", {className: "plog"}, el("div", {className: "eyebrow"}, p.state === "done" ? "What PortShifter did after you approved" : "PortShifter is working"), stepList(p.log, p.log.length)) : "",
    el("div", {className: "pfoot"},
      p.state === "done" ? el("div", {className: "submitted", style: "margin:0;flex:1"}, el("b", {}, `Recorded ${p.approved} planned shipment${p.approved === 1 ? "" : "s"}`), "Tentative: nothing is booked and no carrier has been contacted. ",
          el("button", {className: "textbtn", onclick: () => { close(); $("tab-pln").click(); }}, "Open Planned shipments →"))
        : el("div", {style: "flex:1"}, el("b", {}, `${chosen.length} of ${plans.length} selected · ${money(total, cur)}`),
            el("div", {className: "note"}, plans.some(isLate) ? "A plan that cannot meet its date is left unticked: tick it to include it anyway." : "Untick any you do not want. One click saves the rest.")),
      p.state === "done" ? el("button", {className: "btn small", onclick: close}, "Close")
        : [el("button", {className: "btn small", disabled: locked, onclick: close}, "Dismiss"),
           el("button", {className: "btn small primary", disabled: locked || !chosen.length, onclick: approveProposal}, p.state === "approving" ? "Recording…" : chosen.length === plans.length ? `Approve all ${chosen.length}` : `Approve ${chosen.length} of ${plans.length}`)]),
    el("p", {className: "note pnote"}, d.note));
}
function renderProposal() {
  const host = $("proposal"), p = proposal;
  host.hidden = !p; if (!p) return;
  const d = p.data, close = () => { proposal = null; renderProposal(); draw(); };
  if (p.kind === "new") return renderNewProposal(host, p, close);
  const head = el("div", {className: "phead"},
    el("div", {}, el("div", {className: "eyebrow"}, p.state === "working" ? "PortShifter · working" : p.state === "approving" ? "PortShifter · recording" : p.state === "done" ? "PortShifter · done" : "PortShifter · needs your approval"),
      el("h2", {}, "Suggested plan for the fleet"), el("p", {className: "note"}, `You asked: "${p.request}" · inside your limits: ${limitsText()}`)),
    el("button", {className: "iconbtn", ariaLabel: "Close", title: "Close without approving", onclick: close, innerHTML: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/></svg>'}));
  if (p.error) return host.replaceChildren(head, el("p", {className: "warn"}, `PortShifter could not build a plan (${p.error}). Nothing was changed.`));
  if (!d) return host.replaceChildren(head, el("ol", {className: "work"}, el("li", {className: "doing"}, "Reading the fleet…")));
  const work = el("ol", {className: "work"}, d.steps.slice(0, p.state === "working" ? p.shown + 1 : d.steps.length).map((st, i) =>
    el("li", {className: p.state === "working" && i === p.shown ? "doing" : "ok"}, st.text, el("span", {className: "note"}, st.detail))));
  if (p.state === "working") return host.replaceChildren(head, work);
  const cur = d.currency, chosen = d.rows.filter(r => p.picked.has(r.shipment_id)), total = chosen.reduce((t, r) => t + r.choice.extra_cost, 0);
  const row = r => { const c = r.choice, lvl = r.current_risk || 0, change = c.kind !== "keep", done = p.state === "done";
    return el("div", {className: `prow ${r.status}`},
      change ? el("input", {type: "checkbox", checked: p.picked.has(r.shipment_id), disabled: p.state !== "review", ariaLabel: `Include ${r.shipment_id}`,
        onchange: e => { e.target.checked ? p.picked.add(r.shipment_id) : p.picked.delete(r.shipment_id); renderProposal(); }}) : el("span", {}),
      el("div", {className: "pmain"},
        el("div", {className: "pt"}, el("button", {className: "textbtn", title: "Open this shipment", onclick: () => { close(); ptab = "plan"; select(r.shipment_id); }}, r.shipment_id),
          el("span", {className: "note"}, `${r.origin} → ${r.destination}`),
          r.status === "needs_your_call" ? el("span", {className: "badge badge-out"}, "Needs your call") : r.status === "no_change" ? el("span", {className: "badge"}, "No change") : "",
          done && p.picked.has(r.shipment_id) ? el("span", {className: "badge badge-rec"}, "Approved") : ""),
        el("div", {className: "pact"}, el("b", {}, c.label), " · ", el("span", {className: "dot", style: `background:${COLORS[lvl]}`}), ` ${lvl} ${NAMES[lvl]} → `,
          el("span", {className: "dot", style: `background:${COLORS[c.resulting_risk || 0]}`}), ` ${c.resulting_risk} ${NAMES[c.resulting_risk] || ""}`,
          c.delay_hours ? ` · +${hours(c.delay_hours)}` : ""),
        el("div", {className: "note"}, r.events.length ? `${r.events.map(e => `${cap(e.type)} at ${e.location} (${e.status}${e.is_fixture ? ", sample" : ""})`).join("; ")}. ` : "", r.why,
          ...(c.violations || []).map(v => el("span", {className: "out"}, ` ${cap(v)}.`))),
        c.cost_lines?.length ? el("details", {className: "working"}, el("summary", {}, `How ${money(c.extra_cost, cur)} was worked out`),
          ...c.cost_lines.map(l => costLine(l, cur)), el("small", {className: "src"}, c.cost_note)) : ""),
      el("b", {className: "pcost"}, change ? `+${money(c.extra_cost, cur)}` : "No cost")); };
  host.replaceChildren(head,
    el("details", {className: "pwork"}, el("summary", {}, `What PortShifter did: ${d.steps.length} steps, ${d.rows.reduce((t, r) => t + r.options_considered, 0)} options priced for ${d.totals.affected} shipments`), work),
    el("div", {className: "prows"}, d.rows.map(row)),
    p.log?.length ? el("div", {className: "plog"}, el("div", {className: "eyebrow"}, p.state === "done" ? "What PortShifter did after you approved" : "PortShifter is working"), stepList(p.log, p.log.length)) : "",
    el("div", {className: "pfoot"},
      p.state === "done"
        ? el("div", {className: "submitted", style: "margin:0;flex:1"}, el("b", {}, `Approved ${p.approved} change${p.approved === 1 ? "" : "s"}`),
            `${p.failed ? `${p.failed} could not be recorded. ` : ""}Recorded as tentative; nothing is booked or sent to a carrier.`)
        : el("div", {style: "flex:1"}, el("b", {}, `${chosen.length} change${chosen.length === 1 ? "" : "s"} selected · ${money(total, cur)}`),
            el("div", {className: "note"}, `${d.goal_label} · ${d.totals.no_change} left as planned · ${d.totals.needs_your_call} needing your call (tick to include)`)),
      p.state === "done" ? el("button", {className: "btn small", onclick: close}, "Close")
        : [el("button", {className: "btn small", disabled: p.state !== "review", onclick: close}, "Dismiss"),
           el("button", {className: "btn small primary", disabled: p.state !== "review" || !chosen.length, onclick: approveProposal}, p.state === "approving" ? "Recording…" : `Approve ${chosen.length} change${chosen.length === 1 ? "" : "s"}`)]),
    el("p", {className: "note pnote"}, d.note));
}

async function ask(message) {
  if (!selected) return;
  if (FLEET_RE.test(message)) { // a request about the whole fleet, typed in a shipment's chat
    const log = $("log"); log.querySelector(".intro")?.remove();
    log.append(el("div", {className: "msg you"}, message),
      say("That is a job for the whole fleet. I am working through every affected shipment now and will bring you one plan to approve. Nothing changes until you approve it."));
    logs[selected] = [...log.childNodes];
    return fleetPlan(message);
  }
  if (/\bnew (shipments?|loads?|deliveries)\b/i.test(message)) { // new shipments are not about this one: PortShifter takes it
    const log = $("log"); log.querySelector(".intro")?.remove();
    log.append(el("div", {className: "msg you"}, message), say("That is about new shipments, not this one, so I have taken it to the main Ask PortShifter chat."));
    return openBot(message);
  }
  if (ptab !== "chat") { ptab = "chat"; placeChat(); renderDetail(); }
  const log = $("log"), id = selected; log.querySelector(".intro")?.remove();
  log.append(el("div", {className: "msg you"}, message));
  const wait = el("div", {className: "msg muted"}, "Working…"); log.append(wait); log.scrollTop = 1e9;
  try {
    // "submit the reroute", "go with the recommended one": act on the options already offered
    const act = /^\s*(please\s+)?(submit|apply|confirm|go with|choose|pick|book)\b/i.test(message);
    if (act && (chatOptions || opts)) {
      const o = chatOptions || opts, kind = /reroute|re-route|detour/i.test(message) ? "reroute" : /resched|delay|later|date/i.test(message) ? "reschedule" : /keep|current|nothing/i.test(message) ? "keep" : null;
      const choice = kind ? o.options.find(x => x.kind === kind) : o.options.find(x => x.id === recommend(o));
      if (choice) { await submit(choice);
        wait.replaceWith(say(`Submitted "${choice.label}" for ${id}: ${optFacts(choice, o.currency)}. It is recorded as tentative: nothing is booked or sent to a carrier.`)); log.scrollTop = 1e9; return; }
    }
    // "lower the risk but keep the cost low": turn what they want into a setting, and say which one
    const wantsRisk = /(low|less|reduc|minimi[sz]|avoid|safe)\w*\W+(\w+\W+){0,4}(risk|disruption)|safest|safer/i.test(message);
    const wantsCost = /(low|keep|cheap|minimi[sz]|less|reduc)\w*\W+(\w+\W+){0,4}cost|cheap|budget/i.test(message);
    const inferred = wantsRisk && wantsCost ? "balanced" : wantsRisk ? "low_risk" : wantsCost && !/what does it cost|how much/i.test(message) ? "low_cost" : null;
    if (inferred) { preset = inferred; limits = {...PRESETS[inferred].prefs}; savePrefs(); opts = null; placeChat(); }
    const r = await postJSON("/api/chat", {message, selected_ids: [id], preferences: limits});
    if (selected !== id) return;
    if (!inferred && r.preferences && typeof r.preferences.max_risk === "number" && r.intent === "set_limits") { // limits said in the sentence
      preset = "custom"; limits = {...limits, ...r.preferences}; savePrefs(); opts = null; placeChat();
    }
    // A cost question is answered with the priced options, so the chat and Options show one price for one option.
    const wantsOptions = inferred || r.intent === "suggest_plan" || /rerout|re-rout|resched|option|plan|suggest|alternativ|cost|how much|price/i.test(message);
    let offered = null;
    if (wantsOptions) { offered = await postJSON("/api/options", {shipment_id: id, preferences: limits}); chatOptions = offered; }
    // If the agent answered a different question than "give me options", lead with a plain line instead.
    const text = !offered ? r.text : r.intent === "suggest_plan" ? r.text.split("\n\n")[0]
      : offered.options.length > 1 ? `Here are the options for ${id}. The one marked best is what ${presetName()} points to: ${preset === "low_risk" ? "the lowest risk, then the least delay" : "the cheapest that stays inside these limits"}.`
      : `There is no disruption on ${id}'s route, so there is nothing to move.`;
    const cites = (r.citations || []).map(c => el("div", {}, link(c.url, c.title), el("span", {className: "muted"}, ` · ${ago(c.retrieved_at)}`)));
    wait.replaceWith(say(
      inferred ? el("span", {className: "cites", style: "margin:0 0 6px"}, `Planning for ${presetName()}: ${limitsText()}.`) : "",
      text,
      offered && offered.options.length > 1 ? optionLines(offered) : "",
      offered && offered.options.length > 1 ? el("span", {className: "cites"}, "Submit one here. Tighten or loosen the limits with Change below and I will offer them again. ", el("button", {className: "textbtn", onclick: () => setPtab("plan")}, "Stop-by-stop schedule in Options →")) : "",
      cites.length > 2 ? el("details", {}, el("summary", {}, `${cites.length} sources`), cites)
        : cites.length ? el("span", {className: "cites"}, cites) : ""));
  } catch (err) {
    wait.replaceWith(el("div", {className: "msg warn"}, `The request failed (${err.message}). Nothing was changed.`));
  }
  log.scrollTop = 1e9;
}
$("chat-form").onsubmit = e => {
  e.preventDefault();
  const message = $("msg").value.trim(); if (!message) return;
  $("msg").value = ""; ask(message);
};

$("q").oninput = e => { filter.q = e.target.value.trim(); refresh(); };
$("theme").onclick = () => {
  const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("portshift.theme", t); } catch { /* not stored */ }
  $("theme").setAttribute("aria-checked", String(t === "dark"));
  if (land) land.setStyle(landStyle()); draw();
};
$("theme").setAttribute("aria-checked", String(document.documentElement.dataset.theme === "dark"));
addEventListener("keydown", e => {
  if (e.key !== "Escape" || e.target.matches("input, select")) return;
  if (proposal && proposal.state !== "approving") { proposal = null; renderProposal(); }
  else if (selected) deselect();
  else if (focusEvent) { focusEvent = null; refresh(); }
  else if (filter.levels.size || filter.modes.size || filter.q) clearFilters();
});

function refresh() {
  if (summary) { renderChrome(summary); renderInsights(summary); }
  placeChat(); renderDetail(); renderList(); renderEvents(); renderPlanner(); renderPlanned(); renderRates(); renderFleet(); renderBot(); draw();
}

(async () => {
  [ships, events, summary, decisions, places, rateView] = await Promise.all(
    ["/api/shipments", "/api/events", "/api/summary", "/api/decisions", "/api/places", "/api/my-rates"].map(getJSON));
  await loadCustomers(); renderLegend(); setLegend(legendOpen); loadFleet();
  const p = new URLSearchParams(location.search); // deep links: ?select=S-1005, ?event=E-1, ?tab=evt|ins, ?ptab=chat|plan, ?ask=..., ?theme=dark
  if (p.get("tab") === "stk") { tab("new"); draft.source = "stock"; } // old Stock and dispatch links open the planner with stock
  else if (TABS.includes(p.get("tab"))) tab(p.get("tab"));
  refresh();
  loadStock();
  Promise.all([getJSON("/api/runs"), getJSON("/api/check"), getJSON("/api/planned")]).then(([a, b, c]) => { runs = a; check = b; planned = c; renderBot(); renderPlanned(); renderChrome(summary); draw(); }).catch(() => {});
  loadRates();
  if (["chat", "plan"].includes(p.get("ptab"))) ptab = p.get("ptab");
  if (p.get("limits") === "open") limitsOpen = true; // ?ptab=chat&limits=open shows the limits editor in Ask agent
  if (events.some(e => e.event_id === p.get("event"))) { tab("evt"); openEvent(p.get("event")); }
  else if (ships.some(s => s.shipment_id === p.get("select"))) await select(p.get("select"));
  if (selected) { placeChat(); renderDetail(); if (ptab === "plan") loadOptions(); }
  if (p.get("ask") && selected) ask(p.get("ask"));
  if (p.get("whatif")) askWhatIf(p.get("whatif")); // ?whatif=What if Dover closes tomorrow for 3 days?
  if (p.get("briefing") != null) openBriefing();
  if (p.get("fleet") != null) fleetPlan(p.get("fleet")); // ?fleet=optimise everything for the least cost
  if (draft.source === "stock" && p.get("send")) { // ?tab=stk&from=Glasgow warehouse&send=ST-001:20,ST-002:6&to=London warehouse (Hayes)>...
    await loadStock();
    const from = placeBy(p.get("from") || ""), to = (p.get("to") || "").split(">").map(placeBy).filter(Boolean);
    if (from) draft.stops[0] = from;
    if (to.length) { draft.stops = [draft.stops[0], ...to]; draft.modes = to.map(() => "truck"); }
    dsp.qty = Object.fromEntries(p.get("send").split(",").map(x => x.split(":")).map(([id, n]) => [id, +n || 0]));
    renderPlanner(); await findRoutes();
  }
  if (p.get("bot") != null) { // ?bot=<message> opens Ask PortShifter and sends it; &confirm=1 answers "yes" to its question
    check = await getJSON("/api/check").catch(() => null);
    openBot(); if (p.get("bot")) { await botAsk(p.get("bot")); for (const more of p.getAll("then")) await botAsk(more); // &then=<reply> sends follow-ups in order
      if (p.get("confirm") && pendingNew) { botYou("Yes, plan them"); startNewPlan(pendingNew); } }
  }
  if (view === "new" && p.get("route")) { // ?tab=new&route=Grangemouth>Felixstowe>Birmingham warehouse&modes=ship,truck
    const stops = p.get("route").split(">").map(placeBy).filter(Boolean);
    if (stops.length > 1) { draft.stops = stops; draft.modes = (p.get("modes") || "").split(",").filter(m => MODE_ICONS[m]);
      while (draft.modes.length < stops.length - 1) draft.modes.push("truck"); await findRoutes(); }
  }
})();
