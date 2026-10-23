import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';
const text=fs.readFileSync(process.env.CROWD_RESULTS_UI||new URL('./results-ui.js',import.meta.url),'utf8');
const a=text.indexOf('  const projectsLink='),b=text.indexOf('  // Explicit Owner action;',a);assert(a>=0&&b>a);
class Element{constructor(tag,text=''){this.tag=tag;this.textContent=text;this.children=[];}append(...items){this.children.push(...items);}}
let inserted=null;const selectors=[];const context={node:(tag,text)=>new Element(tag,text),document:{createTextNode:t=>new Element('text',t)},dialog:{querySelector:s=>{selectors.push(s);return{after:(...items)=>inserted=items};}}};
vm.createContext(context);vm.runInContext(text.slice(a,b),context);
assert.deepEqual(selectors,['#library_export']);assert.equal(inserted.length,3);
assert.equal(inserted[0].textContent,'按项目查看数据与导出');assert.equal(inserted[0].href,'/data-products');assert.equal(inserted[0].target,'_blank');assert.equal(inserted[0].rel,'noopener');
assert.equal(inserted[1].href,'/data-product');
assert.deepEqual(inserted[2].children.filter(x=>x.tag==='a').map(x=>x.href),['/data-product/report.json','/data-product/items.jsonl','/data-product/items.csv']);
console.log('PASS visible project entry, original domain link and exports retained; no API calls');
