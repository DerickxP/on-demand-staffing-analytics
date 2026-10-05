/* Dashboard de mão de obra sob demanda: filtros cruzados, cinco visões e gráficos em SVG puro.
 * Entradas: window.BOOKINGS_DATA, window.REVENUE_DATA, window.HEADCOUNT e window.LABOR.
 * As regras de negócio espelham staffing_analytics/analytics/metrics.py. */
(function () {
  "use strict";

  const MONTHS = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];
  const MONTH_ORDER = Object.fromEntries(MONTHS.map((m, i) => [m, i + 1]));
  const WEEKDAYS = ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"];
  const WEEKDAY_ORDER = { Segunda: 1, "Terça": 2, Quarta: 3, Quinta: 4, Sexta: 5, "Sábado": 6, Domingo: 7 };
  const SHIFTS = ["Manhã", "Tarde", "Noite", "Madrugada"];
  const SHIFT_ORDER = Object.fromEntries(SHIFTS.map((s, i) => [s, i + 1]));
  const FIELDS = ["year", "month", "day", "shift", "store", "role", "weekday"];
  const REVENUE_FIELDS = ["year", "month", "day", "shift", "store", "weekday"];
  const LABELS = { year: "Ano", month: "Mês", day: "Dia do mês", shift: "Turno", store: "Loja", role: "Função", weekday: "Dia da semana" };
  const THEME_KEY = "staffing-theme";

  const LABOR = window.LABOR || {};
  const HEADCOUNT = window.HEADCOUNT || {};
  const BOOKINGS = Array.isArray(window.BOOKINGS_DATA) ? window.BOOKINGS_DATA : [];
  const REVENUE = Array.isArray(window.REVENUE_DATA) ? window.REVENUE_DATA : [];
  const PERMANENT_ROLE = normalize(LABOR.permanent_role || "");

  // ---- utilidades -----------------------------------------------------------
  const money = (v) => (v || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  const integer = (v) => Math.round(v || 0).toLocaleString("pt-BR");
  const hours = (v) => (v || 0).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + " h";
  const pct = (v, digits = 2) => (v === null || v === undefined ? "n/d" : v.toFixed(digits).replace(".", ",") + "%");
  const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const byId = (id) => document.getElementById(id);
  const attrs = (field, value) => `data-field="${esc(field)}" data-value="${esc(value)}"`;
  function normalize(text) {
    return String(text || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]/g, "");
  }
  function parseLocal(text) {
    if (!text) return null;
    const p = String(text).split(/[- :T]/).map(Number);
    const d = new Date(p[0], (p[1] || 1) - 1, p[2] || 1, p[3] || 0, p[4] || 0, p[5] || 0);
    return isNaN(d.getTime()) ? null : d;
  }
  function isoWeek(d) {
    const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    t.setUTCDate(t.getUTCDate() + 4 - (t.getUTCDay() || 7));
    const yearStart = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
    const week = Math.ceil((((t - yearStart) / 86400000) + 1) / 7);
    return `${t.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
  }
  const shiftFor = (h) => (h >= 6 && h < 12 ? "Manhã" : h >= 12 && h < 18 ? "Tarde" : h >= 18 && h < 24 ? "Noite" : "Madrugada");

  // ---- pré-processamento ----------------------------------------------------
  BOOKINGS.forEach((r) => {
    const d = parseLocal(r.start);
    r.cost = Number(r.cost || 0);
    r.hours = Number(r.hours || 0);
    r.cancelled = Boolean(r.cancelled);
    if (d) {
      r.hour = d.getHours();
      r.year = String(d.getFullYear());
      r.month = MONTHS[d.getMonth()];
      r.day = String(d.getDate());
      r.weekday = WEEKDAYS[d.getDay()];
      r.shift = shiftFor(r.hour);
      r.week = isoWeek(d);
      r.dayKey = `${r.year}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    }
    ["year", "month", "day", "weekday", "shift"].forEach((f) => { if (!r[f]) r[f] = "Desconhecido"; });
    if (!r.store) r.store = "Não informado";
    if (!r.role) r.role = "Não informado";
    r.costPerHour = r.hours > 0 ? r.cost / r.hours : 0;
  });
  REVENUE.forEach((r) => {
    const d = parseLocal(r.date);
    r.net = Number(r.net || 0);
    r.hour = r.hour === null || r.hour === undefined ? null : Number(r.hour);
    if (d) {
      r.year = String(d.getFullYear());
      r.month = MONTHS[d.getMonth()];
      r.day = String(d.getDate());
      r.weekday = WEEKDAYS[d.getDay()];
    } else {
      r.year = r.month = r.day = r.weekday = "Desconhecido";
    }
    r.shift = shiftFor(r.hour === null ? -1 : r.hour);
  });

  // ---- estado dos filtros ---------------------------------------------------
  const SEL = {};
  FIELDS.forEach((f) => { SEL[f] = new Set(); });
  let currentView = "overview";

  const valueOf = (row, field) => String(row[field] ?? "");
  function matches(row, fields, ignore) {
    for (const f of fields) {
      if (f === ignore) continue;
      if (SEL[f].size && !SEL[f].has(valueOf(row, f))) return false;
    }
    return true;
  }
  const filteredBookings = (ignore = null) => BOOKINGS.filter((r) => matches(r, FIELDS, ignore));
  const filteredRevenue = () => REVENUE.filter((r) => matches(r, REVENUE_FIELDS, null));

  function sortValues(field, values) {
    if (field === "month") return values.sort((a, b) => (MONTH_ORDER[a] || 99) - (MONTH_ORDER[b] || 99));
    if (field === "day") return values.sort((a, b) => Number(a) - Number(b));
    if (field === "shift") return values.sort((a, b) => (SHIFT_ORDER[a] || 99) - (SHIFT_ORDER[b] || 99));
    if (field === "weekday") return values.sort((a, b) => (WEEKDAY_ORDER[a] || 99) - (WEEKDAY_ORDER[b] || 99));
    return values.sort((a, b) => a.localeCompare(b, "pt-BR"));
  }
  function groupBy(rows, field, valueField) {
    const map = new Map();
    rows.forEach((r) => {
      const key = valueOf(r, field) || "Não informado";
      map.set(key, (map.get(key) || 0) + (valueField ? Number(r[valueField] || 0) : 1));
    });
    return [...map.entries()].map(([label, value]) => ({ label, value }));
  }
  function distributeCostByHour(rows) {
    const out = new Map();
    rows.forEach((r) => {
      if (r.cancelled || !(r.hours > 0) || r.hour === undefined) return;
      let remaining = r.hours;
      let hour = r.hour;
      while (remaining > 1e-9) {
        const share = Math.min(1, remaining);
        out.set(hour, (out.get(hour) || 0) + share * r.costPerHour);
        remaining -= share;
        hour = (hour + 1) % 24;
      }
    });
    return out;
  }

  function toggleSel(field, value) {
    if (!SEL[field]) return;
    if (SEL[field].has(value)) SEL[field].delete(value); else SEL[field].add(value);
    refreshAll();
  }
  function clearGroup(field) { SEL[field].clear(); refreshAll(); }
  function clearAll() { FIELDS.forEach((f) => SEL[f].clear()); refreshAll(); }
  function refreshAll() { rebuildSidebar(); renderActiveStrip(); render(); }

  // ---- barra lateral --------------------------------------------------------
  function buildSidebarGroups() {
    byId("sidebar-groups").innerHTML = FIELDS.map((f) => `
      <div class="fg">
        <div class="fg-lbl">${esc(LABELS[f])} <span class="fg-cnt" id="cnt-${f}"></span>
          <button class="fg-x" id="fgx-${f}" type="button" title="Limpar este filtro" data-clear="${f}">×</button></div>
        <div class="fl" id="fl-${f}"></div>
      </div>`).join("");
  }
  function rebuildSidebar() {
    FIELDS.forEach((field) => {
      const rows = filteredBookings(field);
      const available = new Set(rows.map((r) => valueOf(r, field)));
      const counts = new Map();
      rows.forEach((r) => { const k = valueOf(r, field); counts.set(k, (counts.get(k) || 0) + 1); });
      const values = sortValues(field, [...new Set(BOOKINGS.map((r) => valueOf(r, field)))].filter(Boolean));
      byId("fl-" + field).innerHTML = values.map((v) => {
        const on = SEL[field].has(v);
        const off = !available.has(v) && !on;
        return `<div class="fi${on ? " on" : ""}${off ? " off" : ""}" ${attrs(field, v)}>
          <div class="fi-box"><svg class="fi-check" viewBox="0 0 10 10" fill="none"><path d="M1.5 5l2.5 2.5 4.5-4" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
          <span class="fi-name" title="${esc(v)}">${esc(v)}</span><span class="fi-n">${counts.get(v) || 0}</span></div>`;
      }).join("");
      const n = SEL[field].size;
      byId("cnt-" + field).textContent = n;
      byId("cnt-" + field).className = "fg-cnt" + (n ? " show" : "");
      byId("fgx-" + field).className = "fg-x" + (n ? " show" : "");
    });
  }
  function renderActiveStrip() {
    const strip = byId("af");
    strip.querySelectorAll(".af-tag").forEach((t) => t.remove());
    let count = 0;
    FIELDS.forEach((field) => SEL[field].forEach((value) => {
      count += 1;
      const tag = document.createElement("span");
      tag.className = "af-tag";
      tag.innerHTML = `<span class="af-field">${esc(LABELS[field])}</span> ${esc(value)} <button class="af-x" type="button" ${attrs(field, value)}>×</button>`;
      strip.appendChild(tag);
    }));
    byId("af-none").style.display = count ? "none" : "";
  }

  // ---- componentes gráficos -------------------------------------------------
  function renderBars(elId, items, format, field, accent) {
    const el = byId(elId);
    if (!items.length) { el.innerHTML = "<div class='empty'>Sem dados</div>"; return; }
    const max = Math.max(...items.map((i) => i.value), 1);
    const hasSel = SEL[field] && SEL[field].size > 0;
    el.innerHTML = `<div class="blist">` + items.map((item) => {
      const on = SEL[field] && SEL[field].has(item.label);
      const dim = hasSel && !on;
      const extra = item.extra ? `<span class="bextra" title="Participação no faturamento da loja">${esc(item.extra)}</span>` : "";
      return `<div class="brow${on ? " hi" : ""}${dim ? " dim" : ""}" ${attrs(field, item.label)}>
        <div class="brow-top"><div class="blbl" title="${esc(item.label)}">${esc(item.label)}</div><div class="bval">${format(item.value)}${extra}</div></div>
        <div class="btrack"><div class="bfill${accent ? " accent" : ""}" style="width:${(item.value / max * 100).toFixed(1)}%"></div></div></div>`;
    }).join("") + `</div>`;
  }

  function renderLine(elId, items, format, field) {
    const el = byId(elId);
    if (!items.length) { el.innerHTML = "<div class='empty'>Sem dados</div>"; return; }
    if (items.length === 1) { renderBars(elId, items, format, field, true); return; }
    const W = 700, H = 220, pl = 30, pr = 30, pt = 40, pb = 30, iW = W - pl - pr, iH = H - pt - pb;
    const values = items.map((i) => i.value);
    const minV = Math.min(...values), maxV = Math.max(...values, 1);
    const pts = items.map((item, i) => ({
      x: pl + (i / (items.length - 1)) * iW,
      y: pt + iH - ((item.value - minV) / (maxV - minV || 1)) * iH,
      item,
    }));
    let line = `M${pts[0].x.toFixed(1)},${pts[0].y.toFixed(1)} `;
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1], b = pts[i], mid = (a.x + b.x) / 2;
      line += `C${mid.toFixed(1)},${a.y.toFixed(1)} ${mid.toFixed(1)},${b.y.toFixed(1)} ${b.x.toFixed(1)},${b.y.toFixed(1)} `;
    }
    const area = line + `L${pts[pts.length - 1].x.toFixed(1)},${(pt + iH).toFixed(1)} L${pl},${(pt + iH).toFixed(1)} Z`;
    const grid = [0, 0.5, 1].map((p) => { const y = pt + iH - p * iH; return `<line x1="${pl}" y1="${y}" x2="${W - pr}" y2="${y}" stroke="var(--border)" stroke-dasharray="4 4"/>`; }).join("");
    const short = (v) => (v >= 1e6 ? (v / 1e6).toFixed(1) + "M" : v >= 1e3 ? (v / 1e3).toFixed(1) + "k" : String(Math.round(v)));
    const markers = pts.map((p, i) => {
      const on = SEL[field] && SEL[field].has(p.item.label);
      const prev = i > 0 ? pts[i - 1].item.value : null;
      const arrow = prev === null ? "" : p.item.value > prev ? "▲ " : p.item.value < prev ? "▼ " : "";
      const color = prev !== null && p.item.value < prev ? "var(--text3)" : "var(--blue)";
      return `<g class="pt" ${attrs(field, p.item.label)}>
        <line class="guide" x1="${p.x.toFixed(1)}" y1="${pt}" x2="${p.x.toFixed(1)}" y2="${pt + iH}" stroke="var(--border2)" stroke-dasharray="3 3" opacity="${on ? 1 : 0}"/>
        <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${on ? 6 : 4}" fill="${on ? "var(--text)" : "var(--bg2)"}" stroke="${on ? "var(--accent)" : "var(--blue)"}" stroke-width="${on ? 3 : 2}"/>
        <text x="${p.x.toFixed(1)}" y="${(p.y - 14).toFixed(1)}" text-anchor="middle" font-size="12" font-weight="700" fill="${color}" font-family="'DM Mono',monospace">${arrow}${format === money ? "R$ " : ""}${short(p.item.value)}</text>
        <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="18" fill="transparent"/></g>`;
    }).join("");
    const labels = pts.map((p) => `<text x="${p.x.toFixed(1)}" y="${H - 5}" text-anchor="middle" font-size="12" fill="var(--text3)" font-weight="600" font-family="'DM Mono',monospace">${esc(String(p.item.label).slice(0, 3))}</text>`).join("");
    el.innerHTML = `<svg class="spark" viewBox="0 0 ${W} ${H}"><defs><linearGradient id="g_${elId}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="var(--blue)" stop-opacity="0.2"/><stop offset="100%" stop-color="var(--bg2)" stop-opacity="0"/></linearGradient></defs>
      ${grid}<path d="${area}" fill="url(#g_${elId})"/><path d="${line}" fill="none" stroke="var(--blue)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>${markers}${labels}</svg>`;
  }

  function renderDonut(elId, items, format, field, colors) {
    const el = byId(elId);
    if (!items.length) { el.innerHTML = "<div class='empty'>Sem dados</div>"; return; }
    const total = items.reduce((a, i) => a + i.value, 0) || 1;
    const R = 80, cx = 110, cy = 100, ri = 56;
    const hasSel = SEL[field] && SEL[field].size > 0;
    let paths = "", offset = -90;
    items.forEach((item, index) => {
      const angle = item.value / total * 360;
      const s = offset, e = offset + angle;
      const x1 = cx + R * Math.cos(s * Math.PI / 180), y1 = cy + R * Math.sin(s * Math.PI / 180);
      const x2 = cx + R * Math.cos(e * Math.PI / 180), y2 = cy + R * Math.sin(e * Math.PI / 180);
      const on = SEL[field] && SEL[field].has(item.label);
      const color = colors[index % colors.length];
      const d = angle >= 359.9 ? `M${cx},${cy - R} A${R},${R} 0 1,1 ${cx},${cy - R + 0.01} Z`
        : `M${cx},${cy} L${x1.toFixed(2)},${y1.toFixed(2)} A${R},${R} 0 ${angle > 180 ? 1 : 0},1 ${x2.toFixed(2)},${y2.toFixed(2)} Z`;
      paths += `<path d="${d}" fill="${color}" stroke="var(--bg2)" stroke-width="${on ? 3 : 1.5}" opacity="${hasSel && !on ? 0.2 : 1}" ${attrs(field, item.label)}><title>${esc(item.label)}: ${format(item.value)}</title></path>`;
      offset += angle;
    });
    const legend = items.map((item, index) => {
      const on = SEL[field] && SEL[field].has(item.label);
      return `<div class="dr${on ? " hi" : ""}${hasSel && !on ? " dim" : ""}" ${attrs(field, item.label)}><div class="dd" style="background:${colors[index % colors.length]}"></div><span class="dn-lbl">${esc(item.label)}</span><span class="dp">${format(item.value)} · ${(item.value / total * 100).toFixed(0)}%</span></div>`;
    }).join("");
    el.innerHTML = `<div class="dw"><svg class="donut" width="220" height="200" viewBox="0 0 220 200">${paths}<circle cx="${cx}" cy="${cy}" r="${ri}" fill="var(--bg2)"/><text x="${cx}" y="${cy}" text-anchor="middle" dominant-baseline="central" font-size="16" font-weight="700" fill="var(--text)" font-family="'DM Mono',monospace">${format(total)}</text></svg><div class="dl">${legend}</div></div>`;
  }

  function renderShiftCards(elId, distribution, field) {
    const el = byId(elId);
    const total = SHIFTS.reduce((a, s) => a + (distribution.get(s) || 0), 0);
    if (!total) { el.innerHTML = "<div class='empty'>Sem dados</div>"; return; }
    const hasSel = SEL[field].size > 0;
    el.innerHTML = `<div class="sgrid">` + SHIFTS.map((shift) => {
      const value = distribution.get(shift) || 0;
      const share = value / total * 100;
      const on = SEL[field].has(shift);
      return `<div class="scard${on ? " hi" : ""}${hasSel && !on ? " dim" : ""}" ${attrs(field, shift)}>
        <div class="sctit">${esc(shift)}</div><div class="scpct">${share.toFixed(1).replace(".", ",")}%</div>
        <div class="scval">${money(value)}</div><div class="scbar"><div class="scbar-fill" style="width:${share.toFixed(1)}%"></div></div></div>`;
    }).join("") + `</div>`;
  }

  function renderTable(elId, headers, rows, options = {}) {
    const el = byId(elId);
    if (!rows.length) { el.innerHTML = "<div class='empty'>Sem dados</div>"; return; }
    const head = headers.map((h) => `<th${h.right ? ' class="right"' : ""}>${esc(h.label || h)}</th>`).join("");
    const body = rows.map((cells, index) => {
      const rowAttrs = options.rowAttrs ? options.rowAttrs(index) : "";
      return `<tr${rowAttrs}>${cells.map((c, i) => `<td class="${headers[i] && headers[i].right ? "right mono" : ""}">${c}</td>`).join("")}</tr>`;
    }).join("");
    el.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  }

  // ---- visões ---------------------------------------------------------------
  function renderOverview(rows, revenueRows) {
    const active = rows.filter((r) => !r.cancelled);
    const totalCost = active.reduce((a, r) => a + r.cost, 0);
    const totalHours = active.reduce((a, r) => a + r.hours, 0);
    const totalRevenue = revenueRows.reduce((a, r) => a + r.net, 0);
    byId("k_cost").textContent = money(totalCost);
    byId("k_hours").textContent = hours(totalHours);
    byId("k_count").textContent = integer(active.length);
    byId("k_ticket").textContent = money(active.length ? totalCost / active.length : 0);
    byId("k_share").textContent = totalRevenue > 0 ? pct(totalCost / totalRevenue * 100) : "n/d";

    const revenueByStore = new Map();
    revenueRows.forEach((r) => revenueByStore.set(r.store, (revenueByStore.get(r.store) || 0) + r.net));
    const storeCost = groupBy(active, "store", "cost").sort((a, b) => b.value - a.value);
    storeCost.forEach((d) => { const rev = revenueByStore.get(d.label) || 0; d.extra = rev > 0 ? pct(d.value / rev * 100) : "sem receita"; });

    renderBars("c_store_cost", storeCost, money, "store", true);
    renderBars("c_store_hours", groupBy(active, "store", "hours").sort((a, b) => b.value - a.value), hours, "store", false);
    renderDonut("c_weekday", groupBy(active, "weekday").sort((a, b) => (WEEKDAY_ORDER[a.label] || 99) - (WEEKDAY_ORDER[b.label] || 99)), integer, "weekday",
      ["#0c4a6e", "#075985", "#0369a1", "#0284c7", "#0ea5e9", "#38bdf8", "#7dd3fc"]);
    const byHour = distributeCostByHour(active);
    const byShift = new Map();
    byHour.forEach((value, hour) => { const s = shiftFor(hour); byShift.set(s, (byShift.get(s) || 0) + value); });
    renderShiftCards("c_shift", byShift, "shift");
    renderBars("c_role_cost", groupBy(active, "role", "cost").sort((a, b) => b.value - a.value), money, "role", true);
    renderBars("c_role_hours", groupBy(active, "role", "hours").sort((a, b) => b.value - a.value), hours, "role", false);
    renderLine("c_month", groupBy(active, "month", "cost").sort((a, b) => (MONTH_ORDER[a.label] || 99) - (MONTH_ORDER[b.label] || 99)), money, "month");

    const recent = [...rows].sort((a, b) => String(b.start).localeCompare(String(a.start))).slice(0, 50);
    renderTable("t_recent", ["Início", "Status", "Prestador", "Loja", "Função", { label: "Valor", right: true }],
      recent.map((r) => [
        `<span class="muted mono nowrap">${esc(r.start)}</span>`,
        `<span class="badge ${r.cancelled ? "danger" : "ok"}">${esc(r.status || "-")}</span>`,
        esc(r.worker), esc(r.store), esc(r.role), money(r.cost),
      ]));
  }

  function renderHourly(rows, revenueRows) {
    const el = byId("c_hourly");
    const costMap = distributeCostByHour(rows.filter((r) => !r.cancelled));
    const revMap = new Map();
    revenueRows.forEach((r) => { if (r.hour !== null) revMap.set(r.hour, (revMap.get(r.hour) || 0) + r.net); });
    const data = Array.from({ length: 24 }, (_, h) => ({ h, cost: costMap.get(h) || 0, rev: revMap.get(h) || 0 })).filter((d) => d.cost > 0 || d.rev > 0);
    if (!data.length) { el.innerHTML = "<div class='empty'>Nenhum dado nas faixas selecionadas.</div>"; return; }
    const maxCost = Math.max(...data.map((d) => d.cost), 1), maxRev = Math.max(...data.map((d) => d.rev), 1);
    const totalCost = data.reduce((a, d) => a + d.cost, 0), totalRev = data.reduce((a, d) => a + d.rev, 0);
    const summary = `<div class="summary3">
      <div class="sbox"><div class="sbox-lbl">Faturamento filtrado</div><div class="sbox-val blue">${money(totalRev)}</div></div>
      <div class="sbox"><div class="sbox-lbl">Custo sob demanda filtrado</div><div class="sbox-val accent">${money(totalCost)}</div></div>
      <div class="sbox"><div class="sbox-lbl">Custo / faturamento</div><div class="sbox-val warn">${totalRev > 0 ? pct(totalCost / totalRev * 100) : "n/d"}</div></div></div>`;
    el.innerHTML = summary + `<div class="comp-list">` + data.map((d) => `
      <div class="comp-row"><div class="comp-hour">${String(d.h).padStart(2, "0")}:00 – ${String(d.h + 1).padStart(2, "0")}:00</div><div>
        <div class="comp-lbl"><span>Faturamento</span><span class="mono">${money(d.rev)}</span></div><div class="comp-track"><div class="comp-fill rev" style="width:${(d.rev / maxRev * 100).toFixed(1)}%"></div></div>
        <div class="comp-lbl"><span>Custo sob demanda</span><span class="mono">${d.rev > 0 ? pct(d.cost / d.rev * 100) + " · " : ""}${money(d.cost)}</span></div><div class="comp-track"><div class="comp-fill cost" style="width:${(d.cost / maxCost * 100).toFixed(1)}%"></div></div>
      </div></div>`).join("") + `</div>`;
  }

  function recommendation(hoursTotal, cost, isPermanentRole) {
    const fte = LABOR.monthly_hours ? hoursTotal / LABOR.monthly_hours : 0;
    const suggested = hoursTotal > 0 ? Math.max(Math.ceil(fte), 1) : 0;
    const equivalent = suggested * (LABOR.permanent_monthly_cost || 0);
    if (isPermanentRole) {
      if (hoursTotal < (LABOR.on_demand_max_hours || 0)) return { kind: "ok", label: "Sob demanda (ideal)", fte, equivalent };
      if (cost >= equivalent * (LABOR.hire_cost_ratio || 1)) return { kind: "danger", label: `Contratar ${suggested} efetivo(s)`, fte, equivalent };
      if (hoursTotal >= (LABOR.evaluate_threshold_hours || Infinity)) return { kind: "warn", label: `Avaliar ${suggested} efetivo(s)`, fte, equivalent };
      return { kind: "neutral", label: "Sob demanda", fte, equivalent };
    }
    if (hoursTotal >= (LABOR.evaluate_threshold_hours || Infinity)) return { kind: "warn", label: `Considerar ${suggested} efetivo(s)`, fte, equivalent };
    return { kind: "neutral", label: "Sob demanda", fte, equivalent };
  }

  function renderWorkforce(rows, revenueRows) {
    const el = byId("c_workforce");
    byId("workforce-hint").textContent = `Custo mensal de um efetivo (${LABOR.permanent_role || "função de referência"}): ${money(LABOR.permanent_monthly_cost || 0)}`;
    const active = rows.filter((r) => !r.cancelled);
    const costMap = new Map(), revMap = new Map();
    active.forEach((r) => costMap.set(r.store, (costMap.get(r.store) || 0) + r.cost));
    revenueRows.forEach((r) => revMap.set(r.store, (revMap.get(r.store) || 0) + r.net));
    const stores = [...new Set([...costMap.keys(), ...revMap.keys()])].filter((s) => s && s !== "Não informado");
    const data = stores.map((store) => {
      const permanent = Number(HEADCOUNT[store] || 0);
      return { store, cost: costMap.get(store) || 0, rev: revMap.get(store) || 0, permanent, permanentCost: permanent * (LABOR.permanent_monthly_cost || 0) };
    }).filter((d) => d.cost > 0 || d.rev > 0).sort((a, b) => b.rev - a.rev);
    if (!data.length) { el.innerHTML = "<div class='empty'>Sem dados para a análise de pessoal.</div>"; return; }

    const totalRev = data.reduce((a, d) => a + d.rev, 0);
    const totalPerm = data.reduce((a, d) => a + d.permanentCost, 0);
    const totalCost = data.reduce((a, d) => a + d.cost, 0);
    const totalHeads = data.reduce((a, d) => a + d.permanent, 0);
    const share = (v) => (totalRev > 0 ? v / totalRev * 100 : 0);
    const kpis = `<div class="wf-kpis">
      <div class="wf-kpi"><div class="lbl">Efetivos / faturamento</div><div class="val">${pct(share(totalPerm), 3)}</div><div class="sub">${totalHeads} efetivo(s) · ${money(totalPerm)} por mês</div></div>
      <div class="wf-kpi accent"><div class="lbl">Sob demanda / faturamento</div><div class="val">${pct(share(totalCost), 3)}</div><div class="sub">${money(totalCost)} no período filtrado</div></div>
      <div class="wf-kpi warn"><div class="lbl">Pessoal total / faturamento</div><div class="val">${pct(share(totalPerm + totalCost), 3)}</div><div class="sub">${money(totalPerm + totalCost)}</div></div></div>`;

    const roleMap = new Map();
    active.forEach((r) => {
      const key = r.store + "|" + r.role;
      if (!roleMap.has(key)) roleMap.set(key, { store: r.store, role: r.role, hours: 0, cost: 0 });
      const item = roleMap.get(key); item.hours += r.hours; item.cost += r.cost;
    });
    const maxRev = Math.max(...data.map((d) => d.rev), 1);
    const cards = data.map((d) => {
      const roles = [...roleMap.values()].filter((x) => x.store === d.store && x.hours > 0).sort((a, b) => b.hours - a.hours);
      const roleRows = roles.map((x) => {
        const rec = recommendation(x.hours, x.cost, normalize(x.role) === PERMANENT_ROLE);
        return `<div class="wf-role"><div>${esc(x.role)}</div><div class="right mono">${hours(x.hours)}</div><div class="right mono">${money(x.cost)}</div>
          <div class="right"><span class="badge ${rec.kind}" title="${rec.fte.toFixed(2)} equivalente(s) de jornada completa">${esc(rec.label)}</span></div></div>`;
      }).join("");
      const p = (v) => (d.rev > 0 ? v / d.rev * 100 : 0);
      return `<div class="wf-store">
        <div class="wf-head"><div><div class="wf-name">${esc(d.store)}</div><div class="wf-meta">Faturamento ${money(d.rev)} · ${d.permanent} efetivo(s) · custo fixo ${money(d.permanentCost)}</div></div>
          <div class="wf-pcts"><div class="wf-pct"><div class="lbl">Efetivos</div><div class="val">${pct(p(d.permanentCost), 3)}</div></div><div class="wf-pct accent"><div class="lbl">Sob demanda</div><div class="val">${pct(p(d.cost), 3)}</div></div><div class="wf-pct warn"><div class="lbl">Total</div><div class="val">${pct(p(d.permanentCost + d.cost), 3)}</div></div></div></div>
        <div class="wf-bar"><div class="lbl">Faturamento</div><div class="track"><div class="fill rev" style="width:${(d.rev / maxRev * 100).toFixed(1)}%"></div></div><div class="val">${money(d.rev)}</div></div>
        <div class="wf-bar"><div class="lbl">Efetivos (${d.permanent})</div><div class="track"><div class="fill perm" style="width:${(d.permanentCost / maxRev * 100).toFixed(1)}%"></div></div><div class="val">${money(d.permanentCost)}</div></div>
        <div class="wf-bar"><div class="lbl">Sob demanda</div><div class="track"><div class="fill cost" style="width:${(d.cost / maxRev * 100).toFixed(1)}%"></div></div><div class="val">${money(d.cost)}</div></div>
        ${roles.length ? `<div class="wf-roles"><div class="wf-role head"><div>Função</div><div class="right">Horas</div><div class="right">Custo</div><div class="right">Sugestão</div></div>${roleRows}</div>` : ""}
      </div>`;
    }).join("");
    el.innerHTML = kpis + cards;
  }

  function recurrenceTable(rows) {
    const groups = new Map();
    rows.forEach((r) => {
      if (r.cancelled || !r.worker || !r.week) return;
      if (!groups.has(r.worker)) groups.set(r.worker, { worker: r.worker, weeks: new Map(), stores: new Set(), roles: new Set() });
      const g = groups.get(r.worker);
      g.stores.add(r.store); g.roles.add(r.role);
      if (!g.weeks.has(r.week)) g.weeks.set(r.week, new Set());
      g.weeks.get(r.week).add(r.dayKey);
    });
    return [...groups.values()].map((g) => {
      const counts = [...g.weeks.values()].map((s) => s.size);
      g.peak = Math.max(...counts, 0);
      g.activeWeeks = counts.length;
      g.risk = g.peak >= (LABOR.recurrence_critical_days || 4) ? "danger" : g.peak >= (LABOR.recurrence_warning_days || 3) ? "warn" : "ok";
      return g;
    }).sort((a, b) => b.peak - a.peak || a.worker.localeCompare(b.worker));
  }

  function renderRecurrence(rows) {
    const el = byId("c_recurrence");
    const critical = LABOR.recurrence_critical_days || 4, warning = LABOR.recurrence_warning_days || 3;
    byId("recurrence-hint").textContent = `Recomendação adotada: no máximo ${warning - 1} dia(s) por semana por prestador, para não caracterizar rotina de vínculo empregatício`;
    const data = recurrenceTable(rows);
    if (!data.length) { el.innerHTML = "<div class='empty'>Nenhum prestador nos filtros atuais.</div>"; return; }
    const nCritical = data.filter((d) => d.risk === "danger").length, nWarn = data.filter((d) => d.risk === "warn").length;
    const summary = `<div class="kpis" style="grid-template-columns:repeat(3,1fr);margin-bottom:14px">
      <div class="kpi danger"><div class="kpi-val">${nCritical}</div><div class="kpi-lbl">Casos críticos (≥ ${critical} dias/semana)</div></div>
      <div class="kpi warn"><div class="kpi-val">${nWarn}</div><div class="kpi-lbl">Em atenção (≥ ${warning} dias/semana)</div></div>
      <div class="kpi accent"><div class="kpi-val">${data.length}</div><div class="kpi-lbl">Prestadores ativos</div></div></div>`;
    const labels = { danger: "Risco crítico", warn: "Atenção", ok: "Baixo risco" };
    el.innerHTML = summary + `<div class="tw tall" id="t_recurrence"></div>`;
    renderTable("t_recurrence", ["Prestador", { label: "Semanas ativas", right: true }, { label: "Pico (dias/semana)", right: true }, "Lojas", "Funções", "Risco"],
      data.map((d) => [`<strong>${esc(d.worker)}</strong>`, integer(d.activeWeeks), `<strong>${d.peak}x</strong>`, [...d.stores].map((s) => `<span class="badge neutral">${esc(s)}</span>`).join(" "), esc([...d.roles].join(", ")), `<span class="badge ${d.risk}">${labels[d.risk]}</span>`]),
      { rowAttrs: (i) => ` class="clickable" data-worker="${esc(data[i].worker)}"` });
  }

  function showWorkerSchedule(worker) {
    const items = filteredBookings().filter((r) => r.worker === worker && !r.cancelled).sort((a, b) => b.week.localeCompare(a.week) || String(a.start).localeCompare(String(b.start)));
    byId("modal-title").innerHTML = `<div><div style="font-size:15px;font-weight:700">${esc(worker)}</div><div class="muted" style="font-size:11px">Escala completa dentro dos filtros</div></div>`;
    let html = "", currentWeek = "";
    const daysPerWeek = new Map();
    items.forEach((m) => { if (!daysPerWeek.has(m.week)) daysPerWeek.set(m.week, new Set()); daysPerWeek.get(m.week).add(m.dayKey); });
    items.forEach((m) => {
      if (m.week !== currentWeek) { currentWeek = m.week; const n = daysPerWeek.get(m.week).size; html += `<div class="week-divider">Semana ${esc(m.week)} · ${n} dia${n > 1 ? "s" : ""} de serviço</div>`; }
      html += `<div class="detail-item"><div><strong>${esc(m.start)}</strong><div class="muted">${esc(m.role)}</div></div><div class="right"><span class="badge neutral">${esc(m.store)}</span><div class="muted mono">${hours(m.hours)} · ${money(m.cost)}</div></div></div>`;
    });
    byId("modal-body").innerHTML = html || "<div class='empty'>Sem agendamentos ativos.</div>";
    byId("modal").classList.remove("hidden");
  }

  function renderCompare(rows, revenueRows) {
    const el = byId("c_compare");
    const field = FIELDS.find((f) => SEL[f].size >= 2);
    if (!field) {
      el.innerHTML = `<div class="cmp-help"><div style="font-size:16px;font-weight:700;color:var(--text);margin-bottom:8px">Escolha o que comparar</div>
        Marque duas ou mais opções de um mesmo filtro na barra lateral (por exemplo, dois meses ou duas lojas). Os demais filtros continuam valendo como contexto.</div>`;
      return;
    }
    const values = sortValues(field, [...SEL[field]]);
    const stats = values.map((v) => {
      const b = rows.filter((r) => valueOf(r, field) === v && !r.cancelled);
      const rev = REVENUE_FIELDS.includes(field) ? revenueRows.filter((r) => valueOf(r, field) === v).reduce((a, r) => a + r.net, 0) : 0;
      const cost = b.reduce((a, r) => a + r.cost, 0), hrs = b.reduce((a, r) => a + r.hours, 0);
      return { v, rev, cost, hrs, count: b.length, ticket: b.length ? cost / b.length : 0, perHour: hrs ? cost / hrs : 0, share: rev ? cost / rev * 100 : 0 };
    });
    const cols = `2fr repeat(${values.length}, 1fr) 1fr`;
    const row = (label, key, format, lowerIsBetter) => {
      const a = stats[stats.length - 2][key], b = stats[stats.length - 1][key];
      const diff = a ? (b - a) / a * 100 : b ? 100 : 0;
      const cls = diff === 0 ? "flat" : (diff > 0) === !lowerIsBetter ? "up" : "down";
      return `<div class="cmp-grid" style="grid-template-columns:${cols}"><div>${label}</div>${stats.map((s) => `<div class="num">${format(s[key])}</div>`).join("")}<div class="right"><span class="delta ${cls}">${diff > 0 ? "+" : ""}${diff.toFixed(1)}%</span></div></div>`;
    };
    const context = FIELDS.filter((f) => f !== field && SEL[f].size).map((f) => `${LABELS[f]}: ${[...SEL[f]].join(", ")}`).join(" · ") || "sem filtros extras";
    el.innerHTML = `<div class="cmp-head">${stats.map((s, i) => `<div class="cmp-pill${i === stats.length - 1 ? " last" : ""}">${esc(s.v)}</div>`).join('<span class="muted">vs</span>')}</div>
      <div class="muted" style="text-align:center;margin-bottom:12px;font-size:11px">Comparando por <strong>${esc(LABELS[field])}</strong> · contexto: ${esc(context)}</div>
      <div class="cmp-grid head" style="grid-template-columns:${cols}"><div>Indicador</div>${stats.map((s) => `<div class="right">${esc(s.v)}</div>`).join("")}<div class="right">Variação (últ.)</div></div>
      ${row("Faturamento líquido", "rev", money, false)}${row("Custo sob demanda", "cost", money, true)}${row("Custo / faturamento", "share", (v) => pct(v), true)}
      ${row("Horas computadas", "hrs", hours, true)}${row("Agendamentos", "count", integer, true)}${row("Custo médio por agendamento", "ticket", money, true)}
      ${row("Custo médio da hora sob demanda", "perHour", money, true)}
      <div class="cmp-grid" style="grid-template-columns:${cols}"><div>Custo da hora de um efetivo (referência)</div>${stats.map(() => `<div class="num">${money((LABOR.permanent_monthly_cost || 0) / (LABOR.monthly_hours || 1))}</div>`).join("")}<div></div></div>`;
  }

  // ---- render principal -----------------------------------------------------
  function render() {
    const rows = filteredBookings();
    const revenueRows = filteredRevenue();
    byId("no-data").style.display = rows.length ? "none" : "block";
    document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== "view-" + currentView));
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === currentView));
    if (currentView === "overview") renderOverview(rows, revenueRows);
    else if (currentView === "hourly") renderHourly(rows, revenueRows);
    else if (currentView === "workforce") renderWorkforce(rows, revenueRows);
    else if (currentView === "recurrence") renderRecurrence(rows);
    else renderCompare(rows, revenueRows);
  }

  // ---- eventos --------------------------------------------------------------
  function toggleTheme(save) {
    const isLight = document.body.classList.toggle("light-mode");
    if (save) { try { localStorage.setItem(THEME_KEY, isLight ? "light" : "dark"); } catch (_) { /* sem storage */ } }
  }
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!target || !target.closest) return;
    const tab = target.closest("[data-view]");
    if (tab) { currentView = tab.dataset.view; render(); return; }
    const clear = target.closest("[data-clear]");
    if (clear) { clearGroup(clear.dataset.clear); return; }
    const worker = target.closest("[data-worker]");
    if (worker) { showWorkerSchedule(worker.dataset.worker); return; }
    const filter = target.closest("[data-field]");
    if (filter) toggleSel(filter.dataset.field, filter.dataset.value);
  });
  byId("btn-clear").addEventListener("click", clearAll);
  byId("theme-toggle").addEventListener("click", () => toggleTheme(true));
  byId("modal-close").addEventListener("click", () => byId("modal").classList.add("hidden"));
  byId("modal").addEventListener("click", (e) => { if (e.target === byId("modal")) byId("modal").classList.add("hidden"); });
  try { if (localStorage.getItem(THEME_KEY) === "light") toggleTheme(false); } catch (_) { /* ignora */ }

  buildSidebarGroups();
  refreshAll();
})();
