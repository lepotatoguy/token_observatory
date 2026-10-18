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
console.log('Frontend grouping, combined usage, selection, sorting, filters, context details, and charts passed.');
