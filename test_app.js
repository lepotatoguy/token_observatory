'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map();
const node = id => {
  if(!nodes.has(id))nodes.set(id,{value:id==='range'?'all':'',checked:true,innerHTML:'',dataset:{},addEventListener(){},querySelector(){return null;}});
  return nodes.get(id);
};
const context = vm.createContext({document:{getElementById:node,querySelectorAll:()=>[]},
  fetch:()=>new Promise(()=>{}),setInterval(){},console});
vm.runInContext(fs.readFileSync(__dirname+'/app.js','utf8'),context);
const run = source => vm.runInContext(source,context);
run(`function fixture(id, options={}) {
  const event={at:1792252800,input:80,cached:20,write:0,output:10,reasoning:4};
  return {id,session_id:id,conversation_id:'root',provider:'codex',title:'Same title',project:'p',
    model:'m',models:['m'],last:event.at,modified:event.at,events:[event],totals:{...event,total:110},
    source:id,source_files:[id],compactions:0,parse_errors:0,context:110,capacity:1000,
    latest_usage:event,latest_usage_at:event.at,usage_source:'response usage',subagent:false,reported_cost:null,...options};
}
const root=fixture('root'), child=fixture('child',{subagent:true}),
  other=fixture('other',{conversation_id:'other'}), claude=fixture('claude',{provider:'claude'});
state.data={at:1792252800,sessions:[root,child,other,claude]};`);
assert.equal(run('scoped().length'),3);
assert.equal(run("scoped().find(s=>s.id==='codex-conversation:root').scope.total"),220);
assert.equal(run("scoped().find(s=>s.id==='codex-conversation:root').agent_count"),1);
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
assert.match(run('renderContextDetails(claude)'),/System prompt<b>n\/a/);
run("renderInspector(scoped().find(s=>s.id==='codex-conversation:root'))");
assert.match(node('conversationChart').innerHTML,/Token consumption/);
assert.match(node('conversationChart').innerHTML,/Input: 100/);
node('range').value='all';
run('renderChart([],"conversationChart")');
assert.match(node('conversationChart').innerHTML,/No timestamped usage/);
console.log('Frontend grouping, filters, context details, and selected-chat chart passed.');
