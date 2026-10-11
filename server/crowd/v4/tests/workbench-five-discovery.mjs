import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Run the shipped mode-change handler with real checkbox state. No API/source calls.
const source=fs.readFileSync(new URL('../multiplatform/owner-ui.js',import.meta.url),'utf8');
const start=source.indexOf("  $('owner_mode').onchange = () => {");
const end=source.indexOf("  $('owner_file').onchange",start);
assert.ok(start>=0&&end>start);
const elements=new Map(),platforms=['xhs','dy','ks','bili','wb','tieba','zhihu'].map(value=>({value,checked:true,disabled:false}));
for(const id of ['owner_mode','owner_watch_options','owner_continuous','owner_targets','owner_file','owner_target_help','owner_total'])elements.set(id,{value:'',parentElement:{}});
elements.set('owner_platforms',{
  querySelectorAll:selector=>selector==='input:checked'?platforms.filter(x=>x.checked):platforms,
  querySelector:()=>platforms.find(x=>!x.disabled),
});
let invalidations=0;
const context=vm.createContext({$:id=>elements.get(id),invalidate:()=>invalidations++});
vm.runInContext(source.slice(start,end),context);
const change=elements.get('owner_mode').onchange;
elements.get('owner_mode').value='homefeed';elements.get('owner_total').value='60';change();
assert.equal(platforms.filter(x=>!x.disabled&&x.checked).length,7);
assert.equal(elements.get('owner_targets').required,false);
assert.equal(elements.get('owner_targets').parentElement.hidden,true);
assert.equal(elements.get('owner_total').value,2);
elements.get('owner_mode').value='trending';change();
assert.deepEqual(platforms.filter(x=>!x.disabled).map(x=>x.value),['bili']);
assert.deepEqual(platforms.filter(x=>x.checked).map(x=>x.value),['bili']);
elements.get('owner_mode').value='homefeed';change();
assert.equal(platforms.filter(x=>!x.disabled).length,7);
elements.get('owner_mode').value='search';change();
assert.equal(elements.get('owner_targets').required,true);
assert.equal(elements.get('owner_targets').parentElement.hidden,false);
assert.equal(platforms.filter(x=>!x.disabled).length,7);
assert.equal(invalidations,4);
console.log(JSON.stringify({ok:true,cases:4,real_mode_handler:true,source_requests:0,model_requests:0,live_feed_verification:false}));
