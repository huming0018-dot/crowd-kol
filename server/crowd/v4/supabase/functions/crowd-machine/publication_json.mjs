// Reuse existing strict machine JSON reader; publication scores additionally allow finite numbers.
import {assert,canonical} from './contract.mjs';
export function publicationJSON(text) {
  let index=0,nodes=0;
  const ws=()=>{while(/\s/.test(text[index]||'') && index<text.length)index++;};
  function tokenString(){const start=index++;for(;;){assert(index<text.length,'invalid_json');const c=text[index++];if(c==='"')break;if(c==='\\'){assert(index<text.length,'invalid_json');index++;}else assert(c.charCodeAt(0)>=32,'invalid_json');}const value=JSON.parse(text.slice(start,index));canonical(value);return value;}
  function parse(depth=0){ws();assert(depth<=12&&++nodes<=5000,'encoding_limit');const c=text[index];
    if(c==='"')return tokenString();
    if(c==='{'||c==='['){index++;ws();const object=c==='{',end=object?'}':']',value=object?Object.create(null):[],keys=new Set();if(text[index]===end){index++;return value;}for(;;){let key;if(object){assert(text[index]==='"','invalid_json');key=tokenString();assert(!keys.has(key),'duplicate_json_key');keys.add(key);ws();assert(text[index++]===':','invalid_json');}const v=parse(depth+1);if(object)value[key]=v;else value.push(v);ws();if(text[index]===end){index++;break;}assert(text[index++ ]===',','invalid_json');ws();}return value;}
    const tail=text.slice(index),literal=/^(true|false|null)/.exec(tail);if(literal){index+=literal[0].length;return JSON.parse(literal[0]);}
    const match=/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(tail);assert(match,'invalid_json');index+=match[0].length;
    const number=Number(match[0]);assert(Number.isFinite(number)&&Math.abs(number)<=Number.MAX_SAFE_INTEGER,'invalid_json');return number;
  }
  const value=parse();ws();assert(index===text.length,'invalid_json');return value;
}