import {createHash} from 'node:crypto';
import {imageSize} from './vendor/image-size/dist/index.mjs';
import webp,{init as initWebp} from './vendor/webp/decode.js';
import jpeg,{init as initJpeg} from './vendor/jpeg/decode.js';
import png,{init as initPng} from './vendor/png/decode.js';
import {assets} from './decoder_assets.mjs';
// Some Edge runtimes have neither the browser ImageData container nor the
// Node/Cloudflare compatibility branch shipped by the public codec. This
// supplies only its typed RGBA container; all pixel decoding remains in WASM.
function ensureImageData(){
 if(typeof globalThis.ImageData!=='undefined')return;
 globalThis.ImageData=class ImageData{
  constructor(data,width,height){
   if(!(data instanceof Uint8ClampedArray)||!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1||width>16384||height>16384||width*height>16000000||data.length!==width*height*4)throw new TypeError('invalid_image_data');
   this.data=data;this.width=width;this.height=height;
  }
 };
}
const modules={};let busy=false;
async function initialized(kind){ensureImageData();if(!modules[kind])modules[kind]=(async()=>{const bytes=Uint8Array.from(atob(assets[kind]),c=>c.charCodeAt(0));const compiled=await WebAssembly.compile(bytes);await ({webp:initWebp,jpeg:initJpeg,png:initPng}[kind])(compiled);})();await modules[kind];}
// Container animation flags are checked before calling the mature codec; these are not pixel decoders.
function staticImage(data,type){const v=new DataView(data.buffer,data.byteOffset,data.byteLength);if(type==='png'){for(let p=8;p+12<=data.length;){const n=v.getUint32(p);if(n>data.length-p-12)throw Error();const tag=new TextDecoder().decode(data.subarray(p+4,p+8));if(tag==='acTL')throw Error();p+=n+12;}}if(type==='webp'){for(let p=12;p+8<=data.length;){const n=v.getUint32(p+4,true);if(n>data.length-p-8)throw Error();const tag=new TextDecoder().decode(data.subarray(p,p+4));if(tag==='ANIM'||tag==='ANMF'||tag==='VP8X'&&(data[p+8]&2))throw Error();p+=8+n+(n%2);}}}
export async function decodeImage(data,maxBytes=2097152){
 if(busy)throw new Error('image_decoder_busy');busy=true;let phase='metadata';
 try{if(!(data instanceof Uint8Array)||!data.length||![2097152,26214400].includes(maxBytes)||data.length>maxBytes)throw Error();const meta=imageSize(data),kind=meta.type==='jpg'?'jpeg':meta.type;
 if(!['webp','jpeg','png'].includes(kind)||!Number.isInteger(meta.width)||!Number.isInteger(meta.height)||meta.width<1||meta.height<1||meta.width>16384||meta.height>16384||meta.width*meta.height>16000000)throw Error();staticImage(data,kind);
 phase='initialization';await initialized(kind);phase='decode';const image=await ({webp,jpeg,png}[kind])(data.buffer.slice(data.byteOffset,data.byteOffset+data.byteLength));if(image.width!==meta.width||image.height!==meta.height||!(image.data instanceof Uint8ClampedArray||image.data instanceof Uint8Array)||image.data.byteLength!==meta.width*meta.height*4)throw Error();phase='pixel_hash';const rgba=new Uint8Array(image.data.buffer,image.data.byteOffset,image.data.byteLength);return {format:{webp:'WEBP',jpeg:'JPEG',png:'PNG'}[kind],width:image.width,height:image.height,frames:1,pixel_sha256:createHash('sha256').update(rgba).digest('hex')};
 }catch(e){const error=new Error(e.message==='image_decoder_busy'?'image_decoder_busy':'image_object_mismatch');error.image_decode_stage=phase;throw error;}finally{busy=false;}
}
