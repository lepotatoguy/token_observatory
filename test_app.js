'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map();
const node = id => {
  if(!nodes.has(id))nodes.set(id,{value:id==='range'?'all':'',checked:true,innerHTML:'',dataset:{},attributes:{},setAttribute(name,value){this.attributes[name]=value;},listeners:{},addEventListener(type,handler){this.listeners[type]=handler;},querySelector(){return null;}});
  return nodes.get(id);
};
const context = vm.createContext({document:{getElementById:node,querySelectorAll:()=>[]},
  fetch:()=>new Promise(()=>{}),setInterval(){},console});
vm.runInContext(fs.readFileSync(__dirname+'/app.js','utf8'),context);
vm.runInContext(fs.readFileSync(__dirname+'/insights.js','utf8'),context);
const run = source => vm.runInContext(source,context);
assert.equal(run('state.sort'),'recent');
assert.equal(run('state.sortDirection'),'desc');
run(`function fixture(id, options={}) {
  const event={at:1792252800,input:80,cached:20,write:0,output:10,reasoning:4};
  return {id,session_id:id,conversation_id:'root',provider:'codex',title:'Same title',project:'p',
    model:'m',models:['m'],last:event.at,modified:event.at,events:[event],totals:{...event,total:110},
    source:id,source_files:[id],compactions:0,parse_errors:0,context:110,capacity:1000,
    latest_usage:event,latest_usage_at:event.at,usage_source:'response usage',subagent:false,reported_cost:null,...options};
}
const root=fixture('root'), child=fixture('child',{subagent:true}),
  other=fixture('other',{conversation_id:'other'}), claude=fixture('claude',{provider:'claude',conversation_id:'claude'}),
  claudeChild=fixture('claude-child',{provider:'claude',conversation_id:'claude',subagent:true});
state.data={at:1792252800,sessions:[root,child,other,claude,claudeChild],warnings:[],sources:[]};`);
assert.equal(run('scoped().length'),3);
assert.equal(run("scoped().find(s=>s.id==='codex-conversation:root').scope.total"),220);
assert.equal(run("scoped().find(s=>s.id==='codex-conversation:root').agent_count"),1);
// Claude subagent usage counts toward its parent chat, like Codex threads.
assert.equal(run("scoped().find(s=>s.id==='claude-conversation:claude').scope.total"),220);
assert.equal(run("scoped().find(s=>s.id==='claude-conversation:claude').agent_count"),1);
node('agents').checked=false;
assert.equal(run("scoped().find(s=>s.id==='codex-conversation:root').scope.total"),110);
node('range').value='48h';
run('state.history="2026-10-17"');
assert.equal(run('scoped().length'),3);
const detail=run('renderContextDetails(root)');
assert.match(detail,/Fresh input<b>80/);
assert.match(detail,/Cache read<b>20/);
assert.match(detail,/Reasoning \(in output\)<b>4/);
assert.match(detail,/Free space<b>890/);
assert.doesNotMatch(detail,/n\/a/);
assert.match(run('renderContextDetails({...root,latest_usage:null})'),/No per-response detail/);
assert.match(run('renderContextDetails(claude)'),/Fresh input<b>80/);
assert.doesNotMatch(run('renderContextDetails(claude)'),/n\/a/);
run("renderInspector(scoped().find(s=>s.id==='codex-conversation:root'))");
assert.match(node('conversationChart').innerHTML,/Token consumption/);
assert.match(node('conversationChart').innerHTML,/Input: 100/);
node('range').value='all';
run('renderChart([],"conversationChart")');
assert.match(node('conversationChart').innerHTML,/No timestamped usage/);
node('agents').checked=true;
run('state.selected=null;render()');
assert.equal(run('state.selected'),null);
assert.match(node('inspector').innerHTML,/<h2>All conversations<\/h2>/);
assert.match(node('inspector').innerHTML,/3 chats matching current filters and search/);
assert.match(node('inspector').innerHTML,/550 recorded/);
assert.match(node('inspector').innerHTML,/Context windows are per conversation/);
assert.doesNotMatch(node('inspector').innerHTML,/context-track/);
assert.doesNotMatch(node('sessions').innerHTML,/class="active"/);
assert.match(node('conversationChart').innerHTML,/Input: 500/);
const chooseRoot = () => run(`selectRow({target:{closest:()=>({dataset:{id:'codex-conversation:root'}})}})`);
chooseRoot();
assert.equal(run('state.selected'),'codex-conversation:root');
assert.match(node('inspector').innerHTML,/220 recorded/);
assert.match(node('inspector').innerHTML,/data-clear-selection/);
run('render()');
assert.equal(run('state.selected'),'codex-conversation:root');
chooseRoot();
assert.equal(run('state.selected'),null);
assert.match(node('inspector').innerHTML,/COMBINED USAGE/);
chooseRoot();
node('inspector').listeners.click({target:{closest:()=>({})}});
assert.equal(run('state.selected'),null);
chooseRoot();
run("state.provider='claude';render()");
assert.equal(run('state.selected'),null);
assert.match(node('inspector').innerHTML,/1 chat matching/);
assert.match(node('inspector').innerHTML,/220 recorded/);
node('agents').checked=false;
run('render()');
assert.match(node('inspector').innerHTML,/110 recorded/);
run("state.provider='all'");
node('search').value='other';
run('render()');
assert.match(node('inspector').innerHTML,/1 chat matching/);
assert.match(node('inspector').innerHTML,/110 recorded/);
node('search').value='nothing-matches';
run('render()');
assert.match(node('inspector').innerHTML,/0 chats matching/);
assert.match(node('inspector').innerHTML,/0 recorded/);
assert.match(node('conversationChart').innerHTML,/No timestamped usage/);
node('search').value='';
run(`state.data.sessions=[
  fixture('older',{conversation_id:'older',last:100,events:[{...root.events[0],input:300}]}),
  fixture('newest',{conversation_id:'newest',last:300,events:[{...root.events[0],input:100}]}),
  fixture('middle',{conversation_id:'middle',last:200,events:[{...root.events[0],input:200}]})
];render();`);
const rowOrder=()=>[...node('sessions').innerHTML.matchAll(/data-id="([^"]+)"/g)].map(match=>match[1]);
const latest=['codex-conversation:newest','codex-conversation:middle','codex-conversation:older'];
assert.deepEqual(rowOrder(),latest);
assert.equal(node('activityHeader').attributes['aria-sort'],'descending');
assert.equal(node('activitySortButton').textContent,'Last activity ↓');
assert.equal(node('sortButton').textContent,'Tokens');
node('sortButton').listeners.click();
assert.deepEqual(rowOrder(),latest.slice().reverse());
assert.equal(node('tokensHeader').attributes['aria-sort'],'descending');
assert.equal(node('activityHeader').attributes['aria-sort'],'none');
assert.equal(node('sortButton').textContent,'Tokens ↓');
node('sortButton').listeners.click();
assert.deepEqual(rowOrder(),latest);
assert.equal(node('tokensHeader').attributes['aria-sort'],'ascending');
assert.equal(node('sortButton').textContent,'Tokens ↑');
node('activitySortButton').listeners.click();
assert.deepEqual(rowOrder(),latest);
assert.equal(node('activityHeader').attributes['aria-sort'],'descending');
node('activitySortButton').listeners.click();
assert.deepEqual(rowOrder(),latest.slice().reverse());
assert.equal(node('activityHeader').attributes['aria-sort'],'ascending');
assert.equal(node('activitySortButton').textContent,'Last activity ↑');
run('render()');
assert.deepEqual(rowOrder(),latest.slice().reverse());
// Insights: day drill-down, breakdowns, cache, trends, quota and budget.
run(`const local=(d,h)=>new Date(2026,9,d,h).getTime()/1000;
  state.history='2026-10-17'; state.selected=null;
  state.data={at:local(17,12),warnings:[],sources:[],limits:{},sessions:[
    fixture('d1',{conversation_id:'d1',project:'alpha',last:local(16,10),events:[{at:local(16,10),model:'m1',input:100,cached:300,write:0,output:10,reasoning:0}]}),
    fixture('d2',{conversation_id:'d2',project:'beta',last:local(17,9),events:[{at:local(17,9),model:'m2',input:50,cached:0,write:50,write_1h:20,output:5,reasoning:0}]})]};`);
node('range').value='7';
run('renderChart(scoped().flatMap(s=>s.events))');
assert.match(node('chart').innerHTML,/data-day="2026-10-16"/);
assert.match(node('chart').innerHTML,/data-day="2026-10-17"/);
run('showDay("2026-10-16")');
assert.equal(run('JSON.stringify(scoped().map(s=>s.session_id))'),'["d1"]');
assert.equal(node('dayFilter').hidden,false);
run('clearDay()');
assert.equal(run('scoped().length'),2);
assert.equal(node('dayFilter').hidden,true);
assert.equal(run("JSON.stringify(breakdownRows(scoped(),'model').map(r=>[r.name,r.total]))"),'[["m1",410],["m2",105]]');
assert.equal(run("breakdownRows(scoped(),'project')[1].name"),'beta');
// Pricing, cost card, expandable rows and the Other group.
assert.equal(run("eventCost({input:1e6,cached:1e6,write:1e6,write_1h:0,output:1e6},'claude-opus-4-7')"),5+0.5+6.25+25);
assert.equal(run("eventCost({input:1e6,output:1e6},'claude-sonnet-5-5')"),12);
assert.ok(Math.abs(run("eventCost({input:1e5,output:1e6},'claude-haiku-5-5')")-0.51)<1e-9);
assert.ok(Math.abs(run("eventCost({input:100001,output:1e6},'claude-haiku-5-5')")-2.5500005)<1e-9);
assert.equal(run("eventCost({input:1,output:1},'mystery-model')"),null);
assert.equal(run("breakdownRows(scoped(),'model')[0].output"),10);
run("state.expanded.clear(); renderBreakdown(scoped())");
assert.doesNotMatch(node('breakdown').innerHTML,/breakdown-detail/);
assert.match(node('breakdown').innerHTML,/<b>In<\/b>/);
run("state.expanded.add('model:m1'); renderBreakdown(scoped())");
assert.match(node('breakdown').innerHTML,/Cache write/);
run(`state.expanded.clear(); globalThis.savedSessions=state.data.sessions; state.data.sessions=[fixture('many',{events:Array.from({length:10},(_,i)=>({at:1792252800,model:'x'+i,input:10+i,cached:0,write:0,output:1,reasoning:0}))})]`);
run("renderBreakdown(scoped())");
assert.match(node('breakdown').innerHTML,/Other \(2\)/);
assert.doesNotMatch(node('breakdown').innerHTML,/breakdown-nested/);
run("state.expanded.add('model:other'); renderBreakdown(scoped())");
assert.match(node('breakdown').innerHTML,/breakdown-nested/);
assert.match(node('breakdown').innerHTML,/>x0</);
run("state.expanded.clear(); state.data.sessions=savedSessions");

assert.match(run("costCard(scoped())"),/Estimated cost/);

const cache=run("renderCacheSummary(scoped().find(s=>s.session_id==='d2').events)");
assert.match(cache,/30 \/ 20/);
assert.match(cache,/0\.0%/);
assert.equal(run('contextPercent({capacity:1000,context:850})'),85);
assert.equal(run('contextPercent({capacity:null,context:850})'),null);
const trend=run('trendSummary(state.data.sessions)');
assert.equal(trend.today,105);
assert.equal(trend.average,410/7);
assert.equal(trend.busiest.day,'2026-10-16');
assert.match(run('limitRow({used_percent:21,window_minutes:300,resets_at:state.data.at+2*3600+5*60})'),/5-hour[\s\S]*resets in 2h 5m/);
assert.match(run('limitRow({used_percent:50,window_minutes:10080,resets_at:state.data.at-60})'),/Weekly[\s\S]*reset since this snapshot/);
assert.equal(run('todayTokens()'),105);
run(`state.history=''; state.data.sessions.push(fixture('hot',{conversation_id:'hot',title:'Busy chat',last:Date.now()/1000-60,capacity:1000,context:900}));`);
run('renderPressure()');
assert.equal(node('pressure').hidden,false);
assert.match(node('pressure').innerHTML,/Busy chat \(90%\)/);
// Both providers' limits, and a suggested daily budget from each weekly quota.
run(`state.history='2026-10-17'; state.data.sessions=state.data.sessions.filter(s=>s.session_id!=='hot');
  state.data.limits={codex:{observed_at:state.data.at,primary:{used_percent:3,window_minutes:300,resets_at:state.data.at+3600},secondary:{used_percent:20,window_minutes:10080,resets_at:state.data.at+2*86400}},
    claude:{observed_at:state.data.at-600,primary:{used_percent:100,window_minutes:300,resets_at:null},secondary:{used_percent:50,window_minutes:10080,resets_at:state.data.at+3*86400,resets_estimated:true}}};`);
run('renderLimits()');
assert.match(node('limits').innerHTML,/Claude[\s\S]*100% used · 0% left[\s\S]*reset time unknown[\s\S]*resets in ~3d 0h \(estimated\)[\s\S]*Codex[\s\S]*3% used · 97% left/);
const suggestion=run('JSON.stringify(suggestedBudget())');
assert.equal(JSON.parse(suggestion).total,1030);
assert.match(suggestion,/"provider":"codex","daily":1030/);
assert.match(suggestion,/"missing":\["claude"\]/);
run('renderBudget()');
assert.match(node('budget').innerHTML,/Suggested[\s\S]*1\.0k/);
// Budget meter: one zone per provider, sized by its suggested share and scaled to a custom budget.
assert.equal(run('JSON.stringify(todayByProvider())'),'{"claude":0,"codex":105}');
assert.match(node('budget').innerHTML,/class="split-zone codex"/);
assert.match(node('budget').innerHTML,/Codex<strong class="">105 of 1\.0k · 10%/);
assert.doesNotMatch(node('budget').innerHTML,/split-zone claude/);
const both={total:4000,parts:[{provider:'claude',daily:1000},{provider:'codex',daily:3000}],missing:[]};
const zoned=run(`budgetMeter({claude:500,codex:3300},null,${JSON.stringify(both)})`);
assert.match(zoned,/3\.8k of 4\.0k suggested/);
assert.match(zoned,/split-zone claude" style="flex-grow:1000"><span style="width:50%/);
assert.match(zoned,/split-zone codex critical" style="flex-grow:3000"><span style="width:100%/);
assert.match(zoned,/Claude Code<strong class="">500 of 1\.0k · 50%/);
assert.match(zoned,/Codex<strong class="critical">3\.3k of 3\.0k · 110%/);
assert.match(zoned,/role="img" aria-label="Today&#39;s tokens by provider: Claude Code 500 of 1\.0k, Codex 3\.3k of 3\.0k"/);
const custom=run(`budgetMeter({claude:500,codex:3300},8000,${JSON.stringify(both)})`);
assert.match(custom,/flex-grow:2000"><span style="width:25%/);
assert.match(custom,/flex-grow:6000"><span style="width:55%/);
assert.match(custom,/class="marker" style="left:50%/);
const stacked=run(`budgetMeter({claude:1000,codex:3000},8000,{total:0,parts:[],missing:['claude','codex']})`);
assert.match(stacked,/split-meter stacked"><span class="claude" style="width:12\.5%"><\/span><span class="codex" style="width:37\.5%/);
assert.match(stacked,/Claude Code<strong class="">1\.0k today · no share/);
// Live limit sources and failed live checks.
run(`state.data.limits={claude:{observed_at:state.data.at,source:'live',primary:{used_percent:30,window_minutes:300,resets_at:null}},
  codex:{observed_at:state.data.at,source:'live',plan_type:'plus',primary:{used_percent:9,window_minutes:300,resets_at:null}}};
  state.data.live_limits={checked_at:state.data.at,errors:{claude:'claude command not found'}}; renderLimits();`);
assert.match(node('limits').innerHTML,/Checked with Claude Code's \/usage/);
assert.match(node('limits').innerHTML,/Live check failed: claude command not found/);
assert.match(node('limits').innerHTML,/Codex plus quota from the Codex app server/);
console.log('Frontend grouping, combined usage, selection, sorting, filters, context details, and charts passed.');
