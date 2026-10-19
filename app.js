'use strict';
const $ = id => document.getElementById(id);
const state = {data:null, provider:'all', selected:null, paused:false, sort:'recent', sortDirection:'desc', day:null, fetching:false, history:'', archive:null};
const nowSeconds = () => state.history && state.data ? state.data.at : Date.now()/1000;
const fields = ['input','cached','write','output'];
const colors = ['#8caa77','#aaa0c5','#88a6b5','#d9916b'];
const labels = ['Fresh input','Cache read','Cache write','Output'];
const exact = n => Number(n || 0).toLocaleString();
const compact = n => n >= 1e9 ? `${(n/1e9).toFixed(2)}B` : n >= 1e6 ? `${(n/1e6).toFixed(2)}M` : n >= 1e3 ? `${(n/1e3).toFixed(1)}k` : exact(n);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date = at => at ? new Date(at*1000).toLocaleString() : 'Timestamp unavailable';
const eventTotal = e => fields.reduce((sum,k) => sum+(e[k] || 0),0);
const providerName = p => p === 'codex' ? 'Codex' : 'Claude Code';
const sum = events => Object.fromEntries([...fields,'reasoning','total'].map(k => [k,events.reduce((a,e) => a+(k === 'total' ? eventTotal(e) : e[k] || 0),0)]));

const pad = n => String(n).padStart(2,'0');
const dayKey = at => {const d=new Date(at*1000);return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;};
const dayStart = key => {const [y,m,d]=key.split('-').map(Number);return new Date(y,m-1,d).getTime()/1000;};
const shiftDay = (key, days) => {const [y,m,d]=key.split('-').map(Number);return dayKey(new Date(y,m-1,d+days).getTime()/1000);};
const dayLabel = key => new Date(dayStart(key)*1000).toLocaleDateString(undefined,{weekday:'short',month:'short',day:'numeric',year:'numeric'});
function rangeEnd() { return state.day ? dayStart(shiftDay(state.day,1)) : null; }
function cutoff() {
  if (state.day) return dayStart(state.day);
  const range = $('range').value;
  if (range === 'all') return 0;
  const now = new Date(nowSeconds()*1000);
  if (range === 'today') { now.setHours(0,0,0,0); return now.getTime()/1000; }
  return nowSeconds()-(range==='48h' ? 48*3600 : Number(range)*86400);
}
// One row per chat: subagent and thread logs join the conversation that spawned them.
function groupConversations(sessions) {
  const result=[], groups=new Map();
  for(const s of sessions) {
    const key=`${s.provider}:${s.conversation_id || s.session_id}`;
    if(!groups.has(key))groups.set(key,[]);
    groups.get(key).push(s);
  }
  for(const members of groups.values()) {
    const key=members[0].conversation_id || members[0].session_id;
    const root=members.find(s=>s.session_id===key && !s.subagent) || members.find(s=>!s.subagent) || members[0];
    const events=members.flatMap(s=>s.events).sort((a,b)=>(a.at || 0)-(b.at || 0));
    const totals=Object.fromEntries([...fields,'reasoning','total'].map(k=>[k,members.reduce((n,s)=>n+(s.totals[k] || 0),0)]));
    result.push({...root,id:`${root.provider}-conversation:${key}`,session_id:key,events,totals,
      last:Math.max(...members.map(s=>s.last || 0)) || null,
      modified:Math.max(...members.map(s=>s.modified || 0)),
      models:[...new Set(members.flatMap(s=>s.models))],
      source_files:[...new Set(members.flatMap(s=>s.source_files || [s.source]))],
      thread_ids:members.map(s=>s.session_id),agent_count:members.filter(s=>s.subagent).length,
      compactions:members.reduce((n,s)=>n+s.compactions,0),
      usage_source:members.some(s=>s.usage_source!=='unavailable') ? root.usage_source==='unavailable'?'subagent response usage':root.usage_source : 'unavailable'});
  }
  return result;
}
function scoped() {
  if (!state.data) return [];
  const since = cutoff(), until = rangeEnd();
  const inRange = e => !since || (e.at !== null && e.at >= since && (!until || e.at < until));
  return groupConversations(state.data.sessions.filter(s => (state.provider === 'all' || s.provider === state.provider) && ($('agents').checked || !s.subagent)))
    .map(s => {const events=s.events.filter(inRange); return {...s,events,scope:sum(events)};})
    .filter(s => !since || s.events.length || (!until && s.last && s.last >= since));
}
function relative(at) {
  if (!at) return 'Undated';
  const seconds=Math.max(0,Math.floor(nowSeconds()-at));
  if (seconds<60) return 'Just now';
  if (seconds<3600) return `${Math.floor(seconds/60)}m ago`;
  if (seconds<86400) return `${Math.floor(seconds/3600)}h ago`;
  return new Date(at*1000).toLocaleDateString(undefined,{month:'short',day:'numeric'});
}
function stat(label,value,note,icon) {
  return `<div class="metric"><span>${label}</span><span class="metric-icon">${icon}</span><strong title="${exact(value)}">${compact(value)}</strong><small>${note}</small></div>`;
}
function render() {
  if (!state.data) return;
  const sessions=scoped(), events=sessions.flatMap(s => s.events), totals=sum(events);
  const cacheInput=totals.input+totals.cached+totals.write;
  const hit=cacheInput ? (100*totals.cached/cacheInput).toFixed(1) : '0.0';
  const missing=sessions.filter(s=>s.usage_source==='unavailable').length;
  $('metrics').innerHTML=stat('Recorded tokens',totals.total,`${exact(sessions.length)} chats · ${missing} unreported`,'◈')+
    stat('Input tokens',cacheInput,'Fresh input + cache reads + writes','↗')+
    stat('Output tokens',totals.output,`${exact(totals.reasoning)} recorded reasoning tokens included`,'↙')+
    `<div class="metric"><span>Cache read share</span><span class="metric-icon">◴</span><strong>${hit}<span style="font-size:17px">%</span></strong><small title="${exact(totals.cached)} cached tokens">${compact(totals.cached)} input tokens served from cache</small></div>`;
  renderChart(events);
  renderInsights(sessions);
  $('dayFilter').hidden=!state.day;
  $('dayFilter').textContent=state.day?`${dayLabel(state.day)} ✕`:'';
  const query=$('search').value.toLowerCase();
  const visible=sessions.filter(s => `${s.title} ${s.model} ${s.project} ${s.session_id}`.toLowerCase().includes(query));
  visible.sort((a,b) => (state.sortDirection==='desc'?1:-1)*(state.sort==='tokens' ? b.scope.total-a.scope.total : (b.last || 0)-(a.last || 0)));
  for(const [key,button,header,label] of [['tokens','sortButton','tokensHeader','Tokens'],['recent','activitySortButton','activityHeader','Last activity']]) {
    const active=state.sort===key;
    $(button).textContent=label+(active?(state.sortDirection==='desc'?' ↓':' ↑'):'');
    $(header).setAttribute('aria-sort',active?(state.sortDirection==='desc'?'descending':'ascending'):'none');
  }
  $('sessionCount').textContent=exact(visible.length);
  if (!visible.some(s => s.id===state.selected)) state.selected=null;
  $('sessions').innerHTML=visible.length ? visible.map(s => `<tr tabindex="0" data-id="${escapeHTML(s.id)}" class="${s.id===state.selected?'active':''}" aria-selected="${s.id===state.selected}"><td><div class="conversation"><span class="provider-icon ${s.provider}">${s.provider==='claude'?'✳':'◈'}</span><div><div class="conversation-title" title="${escapeHTML(s.title)}">${escapeHTML(s.title)}</div><div class="conversation-sub">${escapeHTML(s.model)}${s.agent_count?` · ${s.agent_count} ${s.agent_count===1?'subagent':'subagents'}`:s.subagent?' · subagent':''}${s.last && Date.now()/1000-s.last<300?' · recent':''}${contextPercent(s)>=CONTEXT_ALERTS[0]?` · <span class="pressure-badge">context ${contextPercent(s).toFixed(0)}%</span>`:''}</div></div></div></td><td class="token-number" title="${exact(s.scope.total)}">${s.usage_source==='unavailable'?'Unreported':compact(s.scope.total)}</td><td class="relative" title="${escapeHTML(date(s.last))}">${relative(s.last)}</td></tr>`).join('') : '<tr><td colspan="3"><div class="empty-state">No chats match these filters.</div></td></tr>';
  $('tableFooter').textContent=`${exact(visible.length)} ${visible.length===1?'chat':'chats'} · ${exact(visible.reduce((n,s)=>n+s.events.length,0))} usage updates · select a row for details`;
  renderInspector(visible.find(s => s.id===state.selected),visible);
  $('updated').textContent=`${state.history?'Snapshot captured':'Last scan'} ${date(state.data.at)}`;
  if (state.archive) {
    const selected=state.history;
    $('history').innerHTML='<option value="">Live</option>'+state.archive.dates.map(day=>`<option value="${day}">Saved · ${day}</option>`).join('');
    $('history').value=selected;
    $('jsonStatus').textContent=state.history ? `Viewing saved history for ${state.history}. Time filters use its capture time.` :
      (state.archive.error || `JSON auto-save: ${state.archive.saved_at?date(state.archive.saved_at):'first capture pending'} · Latest capture retained for each day`);
    $('archiveInfo').textContent=`Daily JSON files: ${state.archive.directory}. Updated at most once per minute when logs change. Calendar dates use this computer's time zone. Collection continues while the app's local service runs.`;
  }
  const errors=state.data.sessions.reduce((n,s) => n+s.parse_errors,0);
  const warnings=[...state.data.warnings];
  if(state.history && state.data.sessions.some(s=>s.provider==='codex' && s.accounting_version!==2))warnings.push('Legacy Codex rows retained: log segments may overlap; per-response detail was not saved.');
  if(errors) warnings.push(`${exact(errors)} malformed log records skipped.`);
  $('warning').hidden=!warnings.length;
  $('warning').textContent=warnings.join(' · ');
  $('sourceList').innerHTML=state.data.sources.map(s => `<div class="source-item"><strong>${providerName(s.provider)}</strong> · ${exact(s.files)} local log files<code>${escapeHTML(s.path)}</code></div>`).join('');
}
function renderChart(events, target='chart') {
  const dated=events.filter(e => e.at);
  if (!dated.length) {$(target).innerHTML='<div class="empty-state">No timestamped usage in this range.</div>';if(target==='chart')$('chartRange').textContent='No dated usage';return;}
  const end=rangeEnd() || dated.reduce((latest,e)=>Math.max(latest,e.at),nowSeconds());
  const start=cutoff() || dated.reduce((earliest,e)=>Math.min(earliest,e.at),Infinity);
  const span=Math.max(60,end-start);
  // Ranges of two days or more get one clickable bar per calendar day; a single day gets hourly bars.
  const days=[];
  if(span>=172800)for(let key=dayKey(start);dayStart(key)<end;key=shiftDay(key,1))days.push(key);
  const count=days.length || (state.day ? 24 : 36);
  const buckets=Array.from({length:count},(_,i)=>({input:0,output:0,day:days[i] || null}));
  const index=e=>days.length ? days.indexOf(dayKey(e.at)) : Math.min(count-1,Math.floor((e.at-start)/span*count));
  for(const e of dated){const b=buckets[index(e)];if(!b)continue;b.input+=e.input+e.cached+e.write;b.output+=e.output;}
  const max=Math.max(1,...buckets.map(b=>b.input+b.output));
  const width=target==='chart'?1000:440,height=165,left=49,right=10,top=12,bottom=25;
  const plotHeight=height-top-bottom, step=(width-left-right)/count;
  let svg=`<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${escapeHTML('Token consumption, '+date(start)+' to '+date(end))}">`;
  for(let i=0;i<4;i++){const y=top+plotHeight*i/3;svg+=`<line x1="${left}" y1="${y}" x2="${width-right}" y2="${y}" stroke="#edf0e7" stroke-dasharray="3 4"/><text x="0" y="${y+3}">${compact(max*(1-i/3))}</text>`;}
  buckets.forEach((b,i)=>{const x=left+i*step+2,ih=b.input/max*plotHeight,oh=b.output/max*plotHeight;const from=b.day?dayStart(b.day):start+span*i/count;const clickable=b.day && target==='chart';svg+=`<g${clickable?` data-day="${b.day}" class="bar-link" role="button" tabindex="0" aria-label="${escapeHTML('Show '+dayLabel(b.day))}"`:''}><title>${escapeHTML(b.day?dayLabel(b.day)+' · click to view this day':date(from))}\nInput: ${exact(b.input)}\nOutput: ${exact(b.output)}</title><rect x="${x}" y="${top+plotHeight-ih}" width="${Math.max(1,step-4)}" height="${ih}" rx="1" fill="#b0c49e"/><rect x="${x}" y="${top+plotHeight-ih-oh}" width="${Math.max(1,step-4)}" height="${oh}" rx="1" fill="#d9916b"/></g>`;});
  for(let i=0;i<5;i++){const at=start+span*i/4;const text=new Date(at*1000).toLocaleDateString(undefined,{month:'short',day:'numeric'});svg+=`<text x="${left+(width-left-right)*i/4}" y="${height-3}" text-anchor="${i===0?'start':i===4?'end':'middle'}">${escapeHTML(span<172800?new Date(at*1000).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'}):text)}</text>`;}
  $(target).innerHTML=svg+'</svg>';
  if(target!=='chart')return;
  $('chartRange').textContent=state.day?dayLabel(state.day):`${new Date(start*1000).toLocaleDateString()} to ${new Date(end*1000).toLocaleDateString()}`;
  $('activityDescription').textContent=`${exact(dated.length)} timestamped usage updates in selected range`;
}
const capacityLabel = s => ({configured:'configured capacity','model ID [1m]':'capacity from [1m] model ID'})[s.capacity_source] || 'logged capacity';
const capacityNote = s => s.capacity_source==='configured' ? 'Not in the log. Set per model in config.json beside the history folder.' : '';
function renderContextDetails(s) {
  if(!s.latest_usage)return '<p class="context-note">No per-response detail in this capture.</p>';
  const usage=s.latest_usage;
  return `<div class="context-categories">${[...fields,'reasoning'].map((k,i)=>`<span>${k==='reasoning'?'Reasoning (in output)':labels[i]}<b>${exact(usage[k])}</b></span>`).join('')}<span>Free space<b>${s.capacity && s.context!==null?exact(Math.max(0,s.capacity-s.context)):'Unreported'}</b></span></div><p class="context-note">Latest request: ${escapeHTML(date(s.latest_usage_at))}. ${providerName(s.provider)} logs omit system, tool, memory, and skill token attribution.</p>`;
}
function renderUsageBreakdown(usage, unavailable, events=[]) {
  const bar=fields.map((k,i)=>`<span style="width:${usage.total?usage[k]/usage.total*100:0}%;background:${colors[i]}"></span>`).join('');
  const rows=fields.map((k,i)=>`<div class="breakdown-row"><span><i class="swatch" style="background:${colors[i]}"></i>${labels[i]}</span><strong>${unavailable?'Unreported':exact(usage[k])}</strong></div>`).join('');
  return `<div class="breakdown-heading">Token breakdown <span>${unavailable?'Unreported':exact(usage.total)} recorded</span></div><div class="usage-bar">${bar}</div>${rows}<div class="breakdown-row"><span>↳ Reasoning, included in output</span><strong>${unavailable?'Unreported':exact(usage.reasoning)}</strong></div>${renderCacheSummary(events)}`;
}
function renderCombinedInspector(sessions) {
  const events=sessions.flatMap(s=>s.events), usage=sum(events);
  const missing=sessions.filter(s=>s.usage_source==='unavailable').length;
  $('inspector').dataset.id='all-conversations';
  $('inspector').innerHTML=`<div class="inspector-label">COMBINED USAGE</div><h2>All conversations</h2><div class="meta">${exact(sessions.length)} ${sessions.length===1?'chat':'chats'} matching current filters and search</div><div class="context-card"><div class="context-heading">Context windows are per conversation</div><p>Select a chat to inspect its context usage and capacity.</p></div><div class="chat-activity"><div class="breakdown-heading">Combined token activity</div><p>Selected time range · input and cache in green · output in orange</p><div id="conversationChart" class="conversation-chart"></div></div>${renderUsageBreakdown(usage,!!sessions.length && missing===sessions.length,events)}<div class="detail-facts"><div><span>Usage updates in range</span><strong>${exact(events.length)}</strong></div><div><span>Chats with unreported usage</span><strong>${exact(missing)}</strong></div></div>`;
  renderChart(events,'conversationChart');
}
function renderInspector(s, sessions=[]) {
  if(!s){renderCombinedInspector(sessions);return;}
  const expanded=$('inspector').querySelector('details')?.open && $('inspector').dataset.id===s.id;
  $('inspector').dataset.id=s.id;
  const usage=s.scope, capacity=s.capacity, context=s.context;
  const pct=capacity && context!==null ? context/capacity*100:null;
  const rate=s.rate_limits;
  const quota=rate ? ['primary','secondary'].filter(k=>rate[k]).map(k=>{const r=rate[k];return `<div><span>${r.window_minutes===300?'5-hour':r.window_minutes===10080?'Weekly':`${r.window_minutes}-minute`} account quota</span><strong>${r.used_percent ?? 'Unreported'}% used · resets ${escapeHTML(date(r.resets_at))}</strong></div>`;}).join('') : '';
  const stream=s.events.slice().sort((a,b)=>(b.at || 0)-(a.at || 0)).slice(0,20);
  $('inspector').innerHTML=`<div class="inspector-label">CONVERSATION INSPECTOR</div><button type="button" class="quiet" data-clear-selection>← All conversations</button><h2>${escapeHTML(s.title)}</h2><div class="meta"><span class="provider-badge ${s.provider}">${providerName(s.provider)}</span> &nbsp; ${escapeHTML(s.model)}</div><div class="context-card"><div class="context-heading"><span>◒ &nbsp; Context window</span><strong>${pct===null?'Capacity unreported':`${pct.toFixed(1)}%`}</strong></div><p>${context===null?'Latest request usage unavailable':`${exact(context)} tokens, latest recorded input + output`}</p><div class="context-track"><span class="context-used" style="width:${pct===null?0:Math.min(100,pct)}%"></span></div><div class="context-footer"><span title="${escapeHTML(capacityNote(s))}">${capacity?`${compact(capacity)} ${capacityLabel(s)}`:'Window size unreported'}</span><span>${capacity && context!==null ? `${compact(Math.max(0,capacity-context))} free`:'Free space unknown'}</span></div>${renderContextDetails(s)}</div><div class="chat-activity"><div class="breakdown-heading">Chat token activity</div><p>Selected time range · input and cache in green · output in orange${s.agent_count?` · includes ${exact(s.agent_count)} ${s.agent_count===1?'subagent':'subagents'}`:s.subagent?' · subagent only':''}</p><div id="conversationChart" class="conversation-chart"></div></div>${renderUsageBreakdown(usage,s.usage_source==='unavailable',s.events)}<div class="detail-facts"><div><span>Recorded compactions, lifetime</span><strong>${exact(s.compactions)}</strong></div><div><span>Usage source</span><strong>${escapeHTML(s.usage_source)}</strong></div><div><span>Usage updates in range</span><strong>${exact(s.events.length)}</strong></div><div><span>Lifetime recorded tokens</span><strong>${s.usage_source==='unavailable'?'Unreported':exact(s.totals.total)}</strong></div><div><span>${s.cost_source==='session end'?'Reported cost at session end':'Reported lifetime cost'}</span><strong>${s.reported_cost===null?'Unreported':`$${Number(s.reported_cost).toFixed(2)}`}</strong></div>${quota}<div><span>Session ID</span><strong>${escapeHTML(s.session_id)}</strong></div></div><details><summary>Recent usage updates</summary><div class="event-list">${stream.length?stream.map(e=>`<div><span title="${escapeHTML(date(e.at))}">${relative(e.at)}</span><span>${exact(eventTotal(e))} tokens</span></div>`).join(''):'No recorded usage.'}</div><div class="source-path">${escapeHTML(s.source)}</div></details>`;
  renderChart(s.events,'conversationChart');
  if(expanded)$('inspector').querySelector('details').open=true;
}
async function refresh() {
  if(state.fetching || state.paused || state.history)return;
  state.fetching=true;
  try {
    const response=await fetch('/api/usage',{cache:'no-store'});
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    const data=await response.json();
    if(state.paused || state.history)return;
    state.data=data;
    state.archive=data.archive || null;
    $('connectionText').textContent='Live · local logs';$('connectionDot').classList.remove('disconnected');
    render();
  } catch(error) {
    $('connectionText').textContent='Collector disconnected';$('connectionDot').classList.add('disconnected');
    $('warning').hidden=false;$('warning').textContent=`Cannot read collector: ${error.message}. Start server.py and reload. Displayed data may be stale.`;
  } finally {state.fetching=false;}
}
document.querySelectorAll('[data-provider]').forEach(button=>button.addEventListener('click',()=>{state.provider=button.dataset.provider;document.querySelectorAll('[data-provider]').forEach(b=>b.classList.toggle('selected',b===button));render();}));
$('range').addEventListener('change',()=>{state.day=null;render();});
$('agents').addEventListener('change',render);
function showDay(day){state.day=day;state.selected=null;render();}
function clearDay(){state.day=null;render();}
function dayFromEvent(event){const target=event.target.closest?.('[data-day]');if(target){event.preventDefault();showDay(target.dataset.day);}}
$('chart').addEventListener('click',dayFromEvent);
$('chart').addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' ')dayFromEvent(event);});
$('dayFilter').addEventListener('click',clearDay);
$('search').addEventListener('input',render);
function sortBy(key) {
  state.sortDirection=state.sort===key && state.sortDirection==='desc'?'asc':'desc';
  state.sort=key;
  render();
}
$('sortButton').addEventListener('click',()=>sortBy('tokens'));
$('activitySortButton').addEventListener('click',()=>sortBy('recent'));
function selectRow(event){const row=event.target.closest('tr[data-id]');if(row){state.selected=state.selected===row.dataset.id?null:row.dataset.id;render();}}
$('inspector').addEventListener('click',event=>{if(event.target.closest('[data-clear-selection]')){state.selected=null;render();}});
$('sessions').addEventListener('click',selectRow);
$('sessions').addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();selectRow(event);}});
$('pauseButton').addEventListener('click',()=>{state.paused=!state.paused;$('pauseButton').textContent=state.paused?'Resume':'Pause';$('connectionText').textContent=state.paused?'Paused · snapshot held':'Live · local logs';if(!state.paused)refresh();});
$('sourcesButton').addEventListener('click',()=>$('sourcesDialog').showModal());
$('closeSources').addEventListener('click',()=>$('sourcesDialog').close());
$('history').addEventListener('change',async()=>{
  const day=$('history').value;
  state.history=day;
  state.paused=false;
  $('pauseButton').disabled=!!day;
  $('pauseButton').textContent='Pause';
  if(!day){await refresh();return;}
  $('connectionText').textContent='Loading saved history';
  try {
    const response=await fetch(`/api/history/${encodeURIComponent(day)}`,{cache:'no-store'});
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    const data=await response.json();
    if(state.history!==day)return;
    state.data=data;
    $('connectionText').textContent=`Saved · ${day}`;
    render();
  } catch(error) {
    if(state.history!==day)return;
    $('connectionText').textContent='History unavailable';
    $('warning').hidden=false;
    $('warning').textContent=`Cannot open saved history: ${error.message}. Return to Live to continue.`;
  }
});
function downloadFile(content,type,name) {
  const url=URL.createObjectURL(new Blob([content],{type}));
  const a=document.createElement('a');a.href=url;a.download=name;a.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
$('jsonButton').addEventListener('click',()=>{
  if(!state.data)return;
  const query=$('search').value.toLowerCase();
  const sessions=scoped().filter(s=>`${s.title} ${s.model} ${s.project} ${s.session_id}`.toLowerCase().includes(query))
    .map(({scope,...session})=>({...session,filtered_totals:scope}));
  const payload={schema_version:1,accounting_version:state.data.accounting_version || 1,exported_at:new Date().toISOString(),snapshot_at:new Date(state.data.at*1000).toISOString(),
    filters:{provider:state.provider,range:$('range').value,day:state.day,since:cutoff() || null,until:rangeEnd(),include_subagents:$('agents').checked,search:$('search').value,saved_day:state.history || null},
    sessions,sources:state.data.sources,warnings:state.data.warnings};
  downloadFile(JSON.stringify(payload,null,2),'application/json',`token-usage-${new Date().toISOString().slice(0,19).replace(/:/g,'-')}.json`);
});
$('exportButton').addEventListener('click',()=>{
  if(!state.data)return;
  const columns=['provider','title','session_id','model','input','cached','write','output','reasoning','total','last_activity'];
  // Spreadsheet apps can treat text beginning with these characters as formulas.
  const cell=value=>{let s=String(value??'');if(/^[=+@\-\t\r\n]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"';};
  const rows=scoped().filter(s=>`${s.title} ${s.model} ${s.project} ${s.session_id}`.toLowerCase().includes($('search').value.toLowerCase())).map(s=>[s.provider,s.title,s.session_id,s.model,...[...fields,'reasoning','total'].map(k=>s.usage_source==='unavailable'?'':s.scope[k]),s.last?new Date(s.last*1000).toISOString():'']);
  downloadFile('\ufeff'+[columns,...rows].map(row=>row.map(cell).join(',')).join('\r\n'),'text/csv;charset=utf-8',`token-usage-${new Date().toISOString().slice(0,10)}.csv`);
});
refresh();setInterval(refresh,2000);
