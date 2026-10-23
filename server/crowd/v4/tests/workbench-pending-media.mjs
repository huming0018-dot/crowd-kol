import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const html=fs.readFileSync('crowd-kol/server/crowd/v4/multiplatform/dashboard.html','utf8');
const functions=html.split('\n').filter(line=>line.startsWith('function isPendingMedia(')||line.startsWith('function renderResults(')).join('\n');
const buttons=[],elements={};
class Element {
  constructor(tag,text){this.tag=tag;this.textContent=text;this.children=[];this.dataset={};}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  setAttribute(){}
}
for(const id of ['records','result_tabs'])elements[id]=new Element('div');
const context=vm.createContext({document:{activeElement:null},resultData:{records:[],media:[]},resultKind:'media',node:(tag,text)=>new Element(tag,text),button:(text,fn)=>{buttons.push(text);return new Element('button',text);},$:id=>elements[id],kindOf:r=>r.kind});
vm.runInContext(functions,context);
const media={path:'output/bili/media/BV1ocaW6rETo/video.mp4',content_id:'117355149531810',sha256:'a'.repeat(64),source_kind:'mediacrawler_api'};
for(const path of ['output/bili/media/BV1ocaW6rETo/.tmp-73983-8545c8cb/merged.mp4','output/bili/media/BV1ocaW6rETo/.tmp/merged.mp4','output/bili/media/BV1ocaW6rETo/video.mp4.part']){
  buttons.length=0;context.resultData.media=[{...media,path}];vm.runInContext('renderResults()',context);
  assert(!buttons.includes('下载文件'));assert(!buttons.includes('本地 OCR / 转写'));assert(!buttons.includes('云保存已采视频'));assert(buttons.includes('媒体 / 词云 · 0'));
}
buttons.length=0;context.resultData.media=[media,{...media,path:'output/bili/media/BV1ocaW6rETo/.tmp-abc/merged.mp4'}];vm.runInContext('renderResults()',context);
assert.equal(buttons.filter(x=>x==='下载文件').length,1);assert.equal(buttons.filter(x=>x==='云保存已采视频').length,1);assert(buttons.includes('媒体 / 词云 · 1'));
buttons.length=0;context.resultData.media=[];context.resultData.artifacts=[{path:'output/wordcloud.png',source_kind:'derived_local'}];vm.runInContext('renderResults()',context);
assert(buttons.includes('下载文件'));assert(!buttons.includes('本地 OCR / 转写'));assert(!buttons.includes('云保存已采视频'));
assert(html.includes('data.media?.filter(media=>!isPendingMedia(media)).length'));
assert(html.includes('未完成的临时文件已保留，未计入可用媒体。'));
console.log(JSON.stringify({ok:true,cases:5,temporary_media_not_offered_as_download_or_processing:true,final_media_and_derivatives_preserved:true,source_requests:0}));
