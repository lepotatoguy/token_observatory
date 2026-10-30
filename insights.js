'use strict';
// Dashboard insights: quota gauge, daily budget, model/project breakdown, trends, cache and context alerts.
// Uses helpers and state from app.js, which loads first.
const CONTEXT_ALERTS = [80, 95];
const BUDGET_ALERTS = [80, 100];
const ACTIVE_SECONDS = 3600;
const BREAKDOWN_ROWS = 8;
const LOW_CACHE_MIN_INPUT = 100000;
const TREND_DAYS = 7;
const BUSIEST_DAYS = 30;
const HEATMAP_DAYS = 28;
const MAX_BUDGET = 1e13;
const WEEKDAYS = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

// Settings live in this browser. If storage is blocked, they last for this page only.
const memory = {};
const saved = {
  get(key, fallback) {
    try { const value = localStorage.getItem('to.'+key); return value === null ? fallback : JSON.parse(value); }
    catch { return key in memory ? memory[key] : fallback; }
  },
  set(key, value) {
    memory[key] = value;
    try { localStorage.setItem('to.'+key, JSON.stringify(value)); } catch { /* kept in memory above */ }
  },
};
const percent = (part, whole) => whole ? 100*part/whole : 0;
const contextPercent = s => s.capacity && s.context !== null && s.context !== undefined ? 100*s.context/s.capacity : null;

function renderInsights(sessions) {
  renderLimits();
  renderBudget();
  renderBreakdown(sessions);
  renderTrends();
  renderPressure();
  renderAlertsButton();
  checkLimitEvents();
  renderLimitEventHistory();
}

// Usage limits. The collector asks Claude Code (/usage) and the Codex app server on Refresh and every few
// minutes; between checks, Codex log snapshots, Claude's status line or the desktop app's samples fill in.
const windowLabel = minutes => minutes === 300 ? '5-hour' : minutes === 10080 ? 'Weekly' : `${minutes}-minute`;
const WEEK = 7*86400;
function countdown(seconds) {
  const hours = Math.floor(seconds/3600), minutes = Math.floor(seconds%3600/60);
  return hours >= 24 ? `${Math.floor(hours/24)}d ${hours%24}h` : `${hours}h ${minutes}m`;
}
function resetText(limit) {
  if (!limit.resets_at) return 'reset time unknown';
  const left = limit.resets_at - nowSeconds();
  if (left <= 0) return 'reset since this snapshot';
  return limit.resets_estimated ? `resets in ~${countdown(left)} (estimated)` : `resets in ${countdown(left)}`;
}
function limitRow(limit, provider) {
  const known = limit.used_percent !== null && limit.used_percent !== undefined;
  const used = Math.min(100, Math.max(0, Number(limit.used_percent) || 0));
  const level = used >= 90 ? ' critical' : used >= 70 ? ' high' : '';
  return `<div class="limit"><div class="limit-head"><span>${windowLabel(limit.window_minutes)}</span><strong>${known ? `${+Number(limit.used_percent).toFixed(1)}% used · ${+Math.max(0, 100 - limit.used_percent).toFixed(1)}% left` : 'Unreported'}</strong></div><div class="gauge${level}"><span style="width:${used}%"></span></div><small title="${escapeHTML(limit.resets_at ? date(limit.resets_at) : 'Not recorded locally')}">${resetText(limit)}</small>${forecastLine(provider, limit)}</div>`;
}
// Forecast: logged tokens per quota percent in this window, projected at the recent pace. Claude's quota also
// counts claude.ai and desktop chats that aren't in these logs, so the forecast says it is an estimate.
const FORECAST_PACE = {300:3600, 10080:86400};  // Pace window in seconds for the 5-hour and weekly limits.
function clock(at) {
  const sameDay = dayKey(at) === dayKey(nowSeconds());
  return new Date(at*1000).toLocaleString(undefined, sameDay ? {hour:'numeric', minute:'2-digit'} : {weekday:'short', hour:'numeric', minute:'2-digit'});
}
function forecast(provider, limit) {
  const used = Number(limit.used_percent), now = nowSeconds(), pace = FORECAST_PACE[limit.window_minutes];
  if (!pace || !limit.resets_at || !(used >= 1) || used >= 100 || limit.resets_at <= now) return null;
  const observed = Math.min(now, state.data.limits?.[provider]?.observed_at || now);
  const sofar = providerTokens(provider, limit.resets_at - limit.window_minutes*60, observed);
  if (!sofar) return null;
  const perPercent = sofar/used;
  const current = Math.min(100, used + providerTokens(provider, observed, now)/perPercent);
  const rate = providerTokens(provider, now - pace, now)/pace;
  if (!rate) return {idle:true, current};
  const hitAt = now + (100 - current)*perPercent/rate;
  return hitAt < limit.resets_at ? {hitAt, current} : {atReset:Math.min(100, current + rate*(limit.resets_at - now)/perPercent), current};
}
function forecastLine(provider, limit) {
  const f = forecast(provider, limit);
  if (!f) return '';
  const paceLabel = limit.window_minutes === 300 ? 'the last hour' : 'the last day';
  const text = f.idle ? `No logged use in ${paceLabel}; it stays near ${f.current.toFixed(0)}% for now.`
    : f.hitAt ? `At the pace of ${paceLabel}, you'll reach it around ${clock(f.hitAt)} (in ${countdown(f.hitAt - nowSeconds())}), before it resets.`
    : `At the pace of ${paceLabel}, you'll be at about ${f.atReset.toFixed(0)}% when it resets.`;
  return `<small class="forecast${f.hitAt ? ' warn' : ''}" title="Estimated from tokens in these logs. Usage elsewhere (for example claude.ai chats) also counts toward the limit.">${text}</small>`;
}

// Reset alerts: remember each window's reset time; once it passes after real use, say so on the page and,
// with Alerts on, as a desktop notification.
const RESET_ALERT_MIN = 50;  // Only windows at least this full when last seen.
const RESET_NOTE_SECONDS = 1800;
function checkResets() {
  if (state.history) return;
  const now = nowSeconds(), watched = saved.get('limitWindows', {}), next = {}, recent = saved.get('recentResets', []);
  for (const [key, seen] of Object.entries(watched)) {
    if (seen.resets_at > now) { next[key] = seen; continue; }
    if (seen.used >= RESET_ALERT_MIN) {
      const [provider, minutes] = key.split(':'), label = `${providerName(provider)} ${windowLabel(Number(minutes)).toLowerCase()} limit`;
      recent.push({key:`${key}:${seen.resets_at}`, label, at:seen.resets_at});
      // Persistent collector events deliver reset notifications, including across reloads.
    }
  }
  for (const [provider, quota] of Object.entries(state.data.limits || {})) {
    for (const limit of [quota.primary, quota.secondary]) {
      if (!limit?.resets_at || limit.resets_at <= now || limit.used_percent === null || limit.used_percent === undefined) continue;
      const key = `${provider}:${limit.window_minutes}`;
      next[key] = {resets_at:limit.resets_at, used:Math.max(Number(limit.used_percent), next[key]?.resets_at === limit.resets_at ? next[key].used : 0)};
    }
  }
  saved.set('limitWindows', next);
  saved.set('recentResets', [...new Map(recent.filter(r => now - r.at < RESET_NOTE_SECONDS).map(r => [r.key, r])).values()]);
}
function resetNotes() {
  checkResets();
  const recent = saved.get('recentResets', []);
  return recent.map(r => `<p class="reset-note" role="status">✓ ${escapeHTML(r.label)} reset at ${clock(r.at)}.</p>`).join('');
}

const LIMIT_NOTES = {
  claude: q => q.source === 'live' ? `Checked with Claude Code's /usage, ${relative(q.observed_at).toLowerCase()}.`
    : q.source === 'statusline' ? `From Claude Code's status line, ${relative(q.observed_at).toLowerCase()}.`
    : `From the Claude desktop app's last sample${q.observed_at ? `, ${relative(q.observed_at).toLowerCase()}` : ''}; it may be out of date. Click Refresh to ask Claude Code for current numbers.`,
  codex: q => `Codex${q.plan_type ? ` ${escapeHTML(q.plan_type)}` : ''} quota${q.source === 'live' ? ' from the Codex app server' : ' from the newest Codex log'}, ${relative(q.observed_at).toLowerCase()}.`,
};
function liveError(provider) {
  const error = (state.data.live_limits?.errors || {})[provider];
  return error ? ` <span class="limit-error">Live check failed: ${escapeHTML(error)}.</span>` : '';
}
function renderLimits() {
  const limits = state.data.limits || {};
  const groups = ['claude', 'codex'].filter(p => limits[p]).map(p => `<div class="limit-group"><div class="limit-provider">${providerName(p)}</div>${['primary','secondary'].filter(k => limits[p][k]).map(k => limitRow(limits[p][k], p)).join('')}<p class="insight-note">${LIMIT_NOTES[p](limits[p])}${liveError(p)}</p></div>`).join('');
  $('limits').innerHTML = `<div class="insight-title">Usage limits</div>${resetNotes()}${groups || '<p class="insight-note">No quota data yet. Codex records it with each reply; the Claude desktop app records it as you use Claude.</p>'}`;
}

// Daily budget: all recorded tokens today, every provider, subagents and cache reads included.
const budgetProviders = () => enabledProviders();
function todayByProvider() {
  const start = dayStart(dayKey(nowSeconds())), used = Object.fromEntries(budgetProviders().map(p => [p, 0]));
  for (const s of state.data.sessions) for (const e of s.events) if (e.at !== null && e.at >= start) used[s.provider] = (used[s.provider] || 0) + eventTotal(e);
  return used;
}
const todayTokens = () => Object.values(todayByProvider()).reduce((a, b) => a + b, 0);
// Suggested daily budget, per provider: tokens used in the current weekly window per quota percent,
// times the percent left, spread over the days until the weekly reset. An estimate, labeled as one.
function providerTokens(provider, from, to) {
  return state.data.sessions.filter(s => s.provider === provider)
    .reduce((n, s) => n + s.events.reduce((m, e) => m + (e.at !== null && e.at >= from && e.at <= to ? eventTotal(e) : 0), 0), 0);
}
function suggestedBudget() {
  const limits = state.data.limits || {}, parts = [], missing = [];
  for (const provider of ['claude', 'codex'].filter(p => enabledProviders().includes(p))) {
    const week = limits[provider]?.secondary, observed = limits[provider]?.observed_at;
    const used = week && observed && week.resets_at && week.used_percent >= 1 ? providerTokens(provider, week.resets_at - WEEK, observed) : 0;
    if (!used) { missing.push(provider); continue; }
    const remaining = used*Math.max(0, 100 - week.used_percent)/week.used_percent;
    const days = Math.max(1, (week.resets_at - nowSeconds())/86400);
    parts.push({provider, daily:Math.round(remaining/days), estimated:!!week.resets_estimated});
  }
  return {total:parts.reduce((n, p) => n + p.daily, 0), parts, missing};
}
// The meter is split into one zone per provider, sized by its suggested daily share (scaled to a custom
// budget). Without a suggestion, each provider's tokens stack on one track.
function budgetShares(budget, suggested) {
  const scale = budget && suggested.total ? budget/suggested.total : 1;
  return Object.fromEntries(suggested.parts.map(p => [p.provider, p.daily*scale]));
}
const budgetLevel = share => share >= 100 ? ' critical' : share >= BUDGET_ALERTS[0] ? ' high' : '';
function budgetMeter(usedBy, budget, suggested) {
  const used = budgetProviders().reduce((n, p) => n + (usedBy[p] || 0), 0), scale = budget || suggested.total, share = percent(used, scale);
  const shares = suggested.total ? budgetShares(budget, suggested) : {};
  const zoned = budgetProviders().filter(p => shares[p]);
  const track = zoned.length
    ? `<div class="split-meter">${zoned.map(p => { const part = percent(usedBy[p] || 0, shares[p]); return `<div class="split-zone ${p}${budgetLevel(part)}" style="flex-grow:${shares[p]}"><span style="width:${Math.min(100, part)}%"></span></div>`; }).join('')}</div>`
    : `<div class="split-meter stacked">${budgetProviders().map(p => `<span class="${p}" style="width:${Math.min(100, percent(usedBy[p] || 0, scale))}%"></span>`).join('')}</div>`;
  const marker = budget && suggested.total ? `<span class="marker" style="left:${Math.min(100, percent(suggested.total, budget))}%" title="Suggested ${exact(suggested.total)}"></span>` : '';
  const legend = budgetProviders().filter(p => shares[p] || usedBy[p]).map(p => {
    const detail = shares[p] ? `${compact(usedBy[p] || 0)} of ${compact(shares[p])} · ${percent(usedBy[p] || 0, shares[p]).toFixed(0)}%` : `${compact(usedBy[p])} today · no share`;
    return `<li title="${exact(usedBy[p] || 0)}${shares[p] ? ` of ${exact(Math.round(shares[p]))}` : ''} tokens"><i class="swatch ${p}"></i>${providerName(p)}<strong class="${budgetLevel(shares[p] ? percent(usedBy[p] || 0, shares[p]) : 0).trim()}">${detail}</strong></li>`;
  }).join('');
  const label = `Today's tokens by provider: ${budgetProviders().map(p => `${providerName(p)} ${compact(usedBy[p] || 0)}${shares[p] ? ` of ${compact(shares[p])}` : ''}`).join(', ')}`;
  return `<div class="limit-head"><span title="${exact(used)} of ${exact(scale)}">${compact(used)} of ${compact(scale)} ${budget ? 'budget' : 'suggested'}</span><strong class="${budgetLevel(share).trim()}">${share.toFixed(0)}%</strong></div><div class="meter" role="img" aria-label="${escapeHTML(label)}">${track}${marker}</div><ul class="budget-split">${legend}</ul>`;
}
function suggestionNote(suggested) {
  if (!suggested.total) return '<p class="insight-note">No suggestion yet: it needs a weekly quota with a known reset and some usage in the current week.</p>';
  const parts = suggested.parts.map(p => `${providerName(p.provider)} ${compact(p.daily)}${p.estimated ? ' (estimated reset)' : ''}`).join(' + ');
  const missing = suggested.missing.length ? ` ${suggested.missing.map(providerName).join(' and ')} not included: no weekly quota with a reset yet.` : '';
  return `<p class="insight-note">Suggested: <strong>${compact(suggested.total)}</strong> a day (${parts}) to stay within weekly limits until they reset. Estimated from your quota snapshots and this week's usage.${missing}</p>`;
}
function renderBudget() {
  if (state.editingBudget && $('budget').querySelector('form')) return; // Don't wipe the field while typing.
  const budget = saved.get('dailyBudget', null), usedBy = todayByProvider(), suggested = suggestedBudget();
  const used = budgetProviders().reduce((n, p) => n + usedBy[p], 0);
  let body;
  if (state.editingBudget) {
    body = `<form class="budget-form"><label class="sr-only" for="budgetInput">Daily token budget</label><input id="budgetInput" type="number" min="1" step="1" inputmode="numeric" value="${budget || suggested.total || ''}" placeholder="Tokens per day" required><button type="submit" class="button">Save</button>${budget ? '<button type="button" class="quiet" data-budget="clear">Remove</button>' : ''}<button type="button" class="quiet" data-budget="cancel">Cancel</button></form>${suggestionNote(suggested)}`;
  } else {
    const meter = budget || suggested.total ? budgetMeter(usedBy, budget, suggested) : `<p class="insight-note">${compact(used)} tokens so far today.</p>`;
    const actions = `<div class="budget-actions"><button type="button" class="button" data-budget="edit">${budget ? 'Change budget' : 'Set budget'}</button>${suggested.total && suggested.total !== budget ? '<button type="button" class="quiet" data-budget="suggested">Use suggested</button>' : ''}</div>`;
    body = `${meter}${suggestionNote(suggested)}${actions}`;
    if (budget && !state.history) checkBudget(percent(used, budget));
  }
  $('budget').innerHTML = `<div class="insight-title">Today's budget</div>${body}`;
}
function checkBudget(share) {
  for (const level of BUDGET_ALERTS)
    if (share >= level) alertOnce(`budget:${dayKey(nowSeconds())}:${level}`, level >= 100 ? 'Daily token budget reached' : `Daily token budget ${level}% used`, `${share.toFixed(0)}% of today's budget is used.`);
}
function budgetAction(event) {
  const action = event.target.closest('[data-budget]')?.dataset.budget;
  if (!action) return;
  if (action === 'clear') saved.set('dailyBudget', null);
  if (action === 'suggested') saved.set('dailyBudget', suggestedBudget().total || null);
  state.editingBudget = action === 'edit';
  $('budget').innerHTML = '';
  renderBudget();
  if (state.editingBudget) $('budgetInput')?.focus();
}
function saveBudget(event) {
  event.preventDefault();
  const value = Number($('budgetInput').value);
  if (!Number.isInteger(value) || value < 1 || value > MAX_BUDGET) {
    $('budgetInput').setCustomValidity('Enter a whole number of tokens.');
    $('budgetInput').reportValidity();
    return;
  }
  saved.set('dailyBudget', value);
  state.editingBudget = false;
  $('budget').innerHTML = '';
  renderBudget();
}

// Prices come from /api/pricing: config overrides, then the daily download of Anthropic's published prices,
// then the bundled prices.json. Each is [match, [input, 5m write, 1h write, cache read, output], long-prompt rates, estimated].
const LONG_PROMPT = 100000;
let livePrices = [];
function setLivePrices(models) {
  livePrices = (models || []).flatMap(m => { try { return [[new RegExp(m.match), m.rates, m.long_rates, !!m.estimated]]; } catch { return []; } });
}
function priceFor(model) {
  const id = String(model || '').toLowerCase();
  return livePrices.find(p => p[0].test(id));
}
// Cost of one event; Haiku 5.5 switches to its higher rates for prompts over 100k tokens.
function eventCost(e, model) {
  const entry = priceFor(e.model || model);
  if (!entry) return null;
  const prompt = (e.input || 0) + (e.cached || 0) + (e.write || 0);
  const rate = entry[2] && prompt > LONG_PROMPT ? entry[2] : entry[1];
  const write1h = Math.min(e.write_1h || 0, e.write || 0);
  return ((e.input || 0) * rate[0] + ((e.write || 0) - write1h) * rate[1] + write1h * rate[2] + (e.cached || 0) * rate[3] + (e.output || 0) * rate[4]) / 1e6;
}
function costOf(sessions) {
  let cost = 0, unpriced = new Set(), estimated = false;
  for (const s of sessions) for (const e of s.events) {
    const c = eventCost(e, s.model);
    if (c === null) { if (eventTotal(e)) unpriced.add(e.model || s.model || 'Unreported'); continue; }
    cost += c;
    if (priceFor(e.model || s.model)[3]) estimated = true;
  }
  return {cost, unpriced:[...unpriced], estimated};
}
const money = n => n >= 100 ? `$${Math.round(n).toLocaleString()}` : `$${n.toFixed(2)}`;

// Breakdown by model or project, with each group's input, output, cache reuse and cost.
function breakdownRows(sessions, by) {
  const groups = new Map();
  for (const s of sessions) for (const e of s.events) {
    const name = by === 'model' ? (e.model || s.model || 'Unreported') : (s.project || 'Unknown project');
    const group = groups.get(name) || {name, total:0, cached:0, input:0, fresh:0, write:0, output:0, cost:0, priced:false, chats:new Set()};
    group.total += eventTotal(e);
    group.cached += e.cached || 0;
    group.input += (e.input || 0) + (e.cached || 0) + (e.write || 0);
    group.fresh += e.input || 0;
    group.write += e.write || 0;
    group.output += e.output || 0;
    const cost = eventCost(e, s.model);
    if (cost !== null) { group.cost += cost; group.priced = true; }
    group.chats.add(s.id);
    groups.set(name, group);
  }
  return [...groups.values()].sort((a, b) => b.total - a.total);
}
function lowestCacheChat(sessions) {
  return sessions.map(s => ({s, input:s.scope.input + s.scope.cached + s.scope.write}))
    .filter(x => x.input >= LOW_CACHE_MIN_INPUT)
    .map(x => ({...x, hit:percent(x.s.scope.cached, x.input)}))
    .sort((a, b) => a.hit - b.hit)[0];
}
function mergeRows(name, rows, extra = {}) {
  const sum = k => rows.reduce((n, r) => n + r[k], 0);
  return {name, total:sum('total'), cached:sum('cached'), input:sum('input'), fresh:sum('fresh'), write:sum('write'), output:sum('output'), cost:sum('cost'),
    priced:rows.some(r => r.priced), chats:new Set(rows.flatMap(r => [...r.chats])), ...extra};
}
function breakdownDetail(r) {
  const cells = [['Fresh input', r.fresh], ['Cache read', r.cached], ['Cache write', r.write], ['Output', r.output]]
    .map(([label, n]) => `<div><span>${label}</span><strong title="${exact(n)}">${compact(n)}</strong></div>`).join('');
  const cost = `<div><span>Est. cost</span><strong>${r.priced ? money(r.cost) : 'No price'}</strong></div>`;
  const filter = r.other ? '' : `<button type="button" class="link" data-filter="${escapeHTML(r.name)}">Filter conversations to ${escapeHTML(r.name)}</button>`;
  return `<div class="breakdown-detail">${cells}${cost}${filter}</div>`;
}
function breakdownItem(r, grand, top, key) {
  const open = state.expanded.has(key);
  return `<div class="breakdown-group${open ? ' open' : ''}"><div class="breakdown-item"><button type="button" class="breakdown-name" data-expand="${escapeHTML(key)}" aria-expanded="${open}" title="${open ? 'Hide' : 'Show'} input and output"><i class="chevron">▸</i>${escapeHTML(r.name)}</button>
    <span class="breakdown-meter" title="Input incl. cache ${exact(r.input)} / output ${exact(r.output)}"><span class="fill" style="width:${percent(r.total, top.total)}%"><i class="in" style="flex:${r.input}"></i><i class="out" style="flex:${Math.max(r.output, r.total * 0.01)}"></i></span></span>
    <strong title="${exact(r.total)}">${compact(r.total)}</strong><span>${percent(r.total, grand).toFixed(1)}%</span><span title="Share of input served from cache">${percent(r.cached, r.input).toFixed(0)}% cached</span></div>${open ? breakdownDetail(r) : ''}</div>`;
}
function renderBreakdown(sessions) {
  const by = saved.get('breakdownBy', 'model'), rows = breakdownRows(sessions, by);
  const grand = rows.reduce((n, r) => n + r.total, 0);
  const top = {total:Math.max(1, ...rows.map(r => r.total))};
  const shown = rows.slice(0, BREAKDOWN_ROWS), rest = rows.slice(BREAKDOWN_ROWS);
  const items = shown.map(r => breakdownItem(r, grand, top, `${by}:${r.name}`));
  if (rest.length) {
    const other = mergeRows(`Other (${rest.length})`, rest, {other:true});
    items.push(breakdownItem(other, grand, top, `${by}:other`));
    if (state.expanded.has(`${by}:other`)) items.push(...rest.map(r => `<div class="breakdown-nested">${breakdownItem(r, grand, top, `${by}:${r.name}`)}</div>`));
  }
  const table = items.length ? items.join('') : '<div class="empty-state">No usage in this range.</div>';
  const low = lowestCacheChat(sessions);
  const lowNote = low ? `<p class="insight-note">Lowest cache reuse: <button type="button" class="link" data-select="${escapeHTML(low.s.id)}">${escapeHTML(low.s.title)}</button> at ${low.hit.toFixed(0)}% of input from cache.</p>` : '';
  $('breakdown').innerHTML = `<div class="panel-heading"><div><h2>Breakdown</h2><p>Tokens in the selected range. Click a name to see input and output.</p></div><div class="segmented small">${['model','project'].map(k => `<button type="button" data-breakdown="${k}" class="${k === by ? 'selected' : ''}">By ${k}</button>`).join('')}</div></div><div class="breakdown-legend"><span><i class="swatch input"></i>Input incl. cache</span><span><i class="swatch output"></i>Output</span></div><div class="breakdown-table">${table}</div>${lowNote}`;
}
function breakdownAction(event) {
  const toggle = event.target.closest('[data-breakdown]'), filter = event.target.closest('[data-filter]'), expand = event.target.closest('[data-expand]');
  if (toggle) saved.set('breakdownBy', toggle.dataset.breakdown);
  if (filter) $('search').value = filter.dataset.filter;
  if (expand) { const key = expand.dataset.expand; if (!state.expanded.delete(key)) state.expanded.add(key); }
  if (toggle || filter || expand) render();
}

// Trends from every retained log, ignoring the time range so comparisons stay stable.
function dailyTotals(sessions) {
  const totals = new Map();
  for (const s of sessions) for (const e of s.events) if (e.at !== null) totals.set(dayKey(e.at), (totals.get(dayKey(e.at)) || 0) + eventTotal(e));
  return totals;
}
function trendSummary(sessions) {
  const totals = dailyTotals(sessions), today = dayKey(nowSeconds());
  const on = offset => totals.get(shiftDay(today, offset)) || 0;
  const span = (from, days) => Array.from({length:days}, (_, i) => on(from - i)).reduce((a, b) => a + b, 0);
  const recent = Array.from({length:BUSIEST_DAYS}, (_, i) => ({day:shiftDay(today, -i), total:on(-i)}));
  const busiest = recent.reduce((top, d) => d.total > top.total ? d : top, {day:null, total:0});
  return {today:on(0), average:span(-1, TREND_DAYS)/TREND_DAYS, week:span(0, TREND_DAYS), lastWeek:span(-TREND_DAYS, TREND_DAYS), busiest:busiest.day ? busiest : null};
}
function change(current, previous) {
  if (!previous) return current ? 'no usage before' : 'no change';
  const delta = percent(current - previous, previous);
  return `${delta >= 0 ? '+' : ''}${delta.toFixed(0)}%`;
}
function heatmap(sessions) {
  const grid = Array.from({length:7}, () => Array(24).fill(0)), since = dayStart(shiftDay(dayKey(nowSeconds()), 1 - HEATMAP_DAYS));
  for (const s of sessions) for (const e of s.events) {
    if (e.at === null || e.at < since) continue;
    const when = new Date(e.at*1000);
    grid[(when.getDay() + 6) % 7][when.getHours()] += eventTotal(e);
  }
  const max = Math.max(1, ...grid.flat());
  const cells = grid.map((row, d) => `<span class="heat-label">${WEEKDAYS[d]}</span>${row.map((v, h) => `<span class="heat-cell" style="opacity:${v ? 0.15 + 0.85*v/max : 0.06}" title="${WEEKDAYS[d]} ${pad(h)}:00 · ${exact(v)} tokens"></span>`).join('')}`).join('');
  return `<div class="heatmap">${cells}<span></span>${[0, 6, 12, 18].map(h => `<span class="heat-hour" style="grid-column:${h + 2}">${pad(h)}</span>`).join('')}</div>`;
}
function renderTrends() {
  const sessions = state.data.sessions.filter(s => (state.provider === 'all' || s.provider === state.provider) && ($('agents').checked || !s.subagent));
  const t = trendSummary(sessions);
  const busiest = t.busiest ? `<button type="button" class="link" data-day="${t.busiest.day}">${escapeHTML(dayLabel(t.busiest.day))}</button>, ${compact(t.busiest.total)}` : 'none yet';
  $('trends').innerHTML = `<div class="panel-heading"><div><h2>Trends</h2><p>From all retained logs for the selected provider.</p></div></div><div class="trend-stats"><div><span>Today</span><strong>${compact(t.today)}</strong><small>${change(t.today, t.average)} vs 7-day average (${compact(t.average)})</small></div><div><span>Last 7 days</span><strong>${compact(t.week)}</strong><small>${change(t.week, t.lastWeek)} vs the 7 days before</small></div></div><p class="insight-note">Busiest day in the last ${BUSIEST_DAYS} days: ${busiest}</p><div class="breakdown-heading">When you use tokens <span>last ${HEATMAP_DAYS} days</span></div>${heatmap(sessions)}`;
}

// Context pressure: chats active in the last hour whose latest request fills most of the window.
function renderPressure() {
  const now = nowSeconds();
  const hot = state.history ? [] : groupConversations(state.data.sessions)
    .filter(s => s.last && now - s.last < ACTIVE_SECONDS && contextPercent(s) >= CONTEXT_ALERTS[0])
    .sort((a, b) => contextPercent(b) - contextPercent(a));
  $('pressure').hidden = !hot.length;
  $('pressure').innerHTML = hot.length ? `Context filling up: ${hot.map(s => `<button type="button" class="link" data-select="${escapeHTML(s.id)}">${escapeHTML(s.title)} (${contextPercent(s).toFixed(0)}%)</button>`).join(', ')}` : '';
  for (const s of hot) for (const level of CONTEXT_ALERTS)
    if (contextPercent(s) >= level) alertOnce(`context:${s.id}:${level}`, `Context ${level}% full`, `${s.title} is using ${contextPercent(s).toFixed(0)}% of its ${compact(s.capacity)}-token window.`);
}

// Desktop notifications are opt-in. Each alert fires once.
function alertsEnabled() { return saved.get('alerts', false) && typeof Notification !== 'undefined' && Notification.permission === 'granted'; }
function alertOnce(key, title, body) {
  if (!alertsEnabled()) return;
  const done = saved.get('alerted', []);
  if (done.includes(key)) return;
  saved.set('alerted', [...done, key].slice(-200));
  try { new Notification(title, {body, icon:'/logo.svg', tag:key}); }
  catch (error) { $('warning').hidden = false; $('warning').textContent = `Notification failed: ${error.message}`; }
}
function renderAlertsButton() {
  const supported = typeof Notification !== 'undefined';
  $('alertsButton').textContent = alertsEnabled() ? 'Alerts on' : 'Alerts off';
  $('alertsButton').title = supported ? 'Desktop alerts for usage resets, context pressure and your daily budget' : 'This browser does not support desktop notifications';
  $('alertsButton').disabled = !supported;
  $('limitAlerts').disabled = !supported;
  $('limitAlerts').textContent = supported ? (alertsEnabled() ? 'Desktop alerts on' : 'Enable desktop alerts') : 'Desktop alerts unavailable';
}
async function toggleAlerts() {
  if (alertsEnabled()) { saved.set('alerts', false); render(); return; }
  const permission = await Notification.requestPermission();
  saved.set('alerts', permission === 'granted');
  if (permission !== 'granted') { $('warning').hidden = false; $('warning').textContent = 'Notifications are blocked for this page. Allow them in your browser settings to get alerts.'; }
  render();
}

// Cache details for the inspector: reuse rate, and the 5-minute versus 1-hour split when Claude records it.
function renderCacheSummary(events) {
  if(events.some(e=>e.cache_unreported))return '<div class="breakdown-heading">Cache</div><div class="detail-facts"><div><span>Cache breakdown</span><strong>Unreported for some requests</strong></div></div>';
  const usage = sum(events), input = usage.input + usage.cached + usage.write;
  if (!input) return '';
  const hour = events.reduce((n, e) => n + (e.write_1h || 0), 0);
  const split = events.some(e => 'write_1h' in e) ? `<div><span>Cache writes, 5-minute / 1-hour</span><strong>${exact(usage.write - hour)} / ${exact(hour)}</strong></div>` : '';
  return `<div class="breakdown-heading">Cache</div><div class="detail-facts"><div><span>Input served from cache</span><strong>${percent(usage.cached, input).toFixed(1)}%</strong></div><div><span>Fresh input + cache writes</span><strong>${exact(usage.input + usage.write)}</strong></div>${split}</div>`;
}

function selectConversation(event) {
  const target = event.target.closest('[data-select]');
  if (target) { state.selected = target.dataset.select; render(); }
}
$('budget').addEventListener('click', budgetAction);
$('budget').addEventListener('submit', saveBudget);
$('budget').addEventListener('input', event => event.target.setCustomValidity?.(''));
$('breakdown').addEventListener('click', event => { breakdownAction(event); selectConversation(event); });
$('trends').addEventListener('click', dayFromEvent);
$('pressure').addEventListener('click', selectConversation);
$('alertsButton').addEventListener('click', toggleAlerts);


// Limit preferences are shared with conversation hooks, rather than stored only in this browser.
let limitControls = null;
function currentLimitControls() { return state.data?.limit_control || limitControls; }
function checkLimitEvents() {
  if (state.history) return;
  const control = currentLimitControls();
  if (!control?.settings.reset_notifications) return;
  for (const e of control.events) {
    if (e.type !== 'reset' || nowSeconds()-e.at > RESET_NOTE_SECONDS) continue;
    alertOnce(`limit-reset:${e.provider}:${e.limit}:${e.reset}`, `${providerName(e.provider)} usage window reset`,
      `${windowLabel(e.minutes)} window reset. Any pause for this window has cleared; other limits still apply.`);
  }
}
function eventDescription(e) {
  const kinds = {threshold:'Threshold reached', exhausted:'Limit exhausted', pause:'Pause requested', reset:'Window reset', settings:'Limit settings changed'};
  return `${kinds[e.type] || e.type}${e.used === undefined ? '' : ` · ${e.used}%`}${e.mode ? ` · ${e.mode === 'warn' ? 'Warn' : 'Hard limit'}` : ''}`;
}
function renderLimitEventHistory() {
  const control = currentLimitControls();
  if (!control) return;
  $('limitEventHistory').innerHTML = control.events.length ? `<table><thead><tr><th>Time</th><th>Limit</th><th>Event</th></tr></thead><tbody>${control.events.map(e => `<tr><td>${escapeHTML(date(e.at))}</td><td>${e.provider ? escapeHTML(`${providerName(e.provider)} · ${e.limit}`) : 'All providers'}</td><td>${escapeHTML(eventDescription(e))}</td></tr>`).join('')}</tbody></table>` : '<p class="insight-note">No limit events recorded yet.</p>';
}
async function openLimitControls() {
  $('limitControlsStatus').textContent = 'Loading…';
  $('limitControlsDialog').showModal();
  $('saveLimitControls').disabled = true;
  try {
    const response = await fetch('/api/limit-control', {cache:'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    limitControls = await response.json();
    $('limitControlFields').innerHTML = ['claude','codex'].map(p => {
      const pref = limitControls.settings[p];
      return `<fieldset class="limit-preferences"><legend>${providerName(p)}</legend><label>Mode<select id="limitMode-${p}"><option value="warn"${pref.mode === 'warn' ? ' selected' : ''}>Warn only</option><option value="hard"${pref.mode === 'hard' ? ' selected' : ''}>Hard limit (pause)</option></select></label><label>Threshold (%)<input id="limitThreshold-${p}" type="number" min="1" max="100" step="any" value="${pref.threshold}" required></label></fieldset>`;
    }).join('');
    $('resetNotifications').checked = limitControls.settings.reset_notifications;
    $('limitControlsStatus').textContent = '';
    $('saveLimitControls').disabled = false;
    if (state.data) state.data.limit_control = limitControls;
    renderLimitEventHistory();
  } catch (error) { $('limitControlsStatus').textContent = `Could not load settings: ${error.message}`; }
}
async function saveLimitControls(event) {
  event.preventDefault();
  const payload = {reset_notifications:$('resetNotifications').checked};
  for (const p of ['claude','codex']) {
    const threshold = Number($(`limitThreshold-${p}`).value);
    if (!Number.isFinite(threshold) || threshold < 1 || threshold > 100) {
      $('limitControlsStatus').textContent = 'Threshold must be from 1 to 100%.';
      return;
    }
    payload[p] = {mode:$(`limitMode-${p}`).value, threshold};
  }
  $('saveLimitControls').disabled = true;
  try {
    const response = await fetch('/api/limit-control', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    limitControls = await response.json();
    if (state.data) state.data.limit_control = limitControls;
    $('limitControlsStatus').textContent = 'Saved. Applies to new hook events in this chat and other chats.';
    renderLimitEventHistory();
  } catch (error) { $('limitControlsStatus').textContent = `Could not save settings: ${error.message}`; }
  finally { $('saveLimitControls').disabled = false; }
}
$('limitControlsButton').addEventListener('click', openLimitControls);
$('closeLimitControls').addEventListener('click', () => $('limitControlsDialog').close());
$('limitControlsForm').addEventListener('submit', saveLimitControls);
$('limitAlerts').addEventListener('click', toggleAlerts);

$('limitControlsMobileButton').addEventListener('click', openLimitControls);
