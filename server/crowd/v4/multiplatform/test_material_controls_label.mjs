import fs from 'node:fs';import assert from 'node:assert/strict';import vm from 'node:vm';
const file=process.env.CROWD_RESULTS_UI||new URL('./results-ui.js',import.meta.url);
const source=fs.readFileSync(file,'utf8');const start=source.indexOf("  const participantShare=node('details')"),end=source.indexOf('  let shareScopes=',start);assert(start>0&&end>start);
const created=[];function node(tag,text=''){const x={tag,textContent:text,children:[],attrs:{},append(...v){this.children.push(...v);},setAttribute(k,v){this.attrs[k]=v;}};created.push(x);return x;}
vm.runInNewContext(source.slice(start,end),{node});
assert.equal(created[1].textContent,'参与者素材：版本、反馈与分享');
assert.equal(created[2].attrs['aria-label'],'参与者素材批次');
assert.equal(created[0].children[0],created[1]);assert.equal(created[0].children[1],created[2]);
console.log('PASS rendered participant summary and batch aria expose versions + feedback + share; no network');
