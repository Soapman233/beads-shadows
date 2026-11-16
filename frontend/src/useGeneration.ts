import {ref,onBeforeUnmount} from 'vue';
import type {Pattern} from './engine';
export function useGeneration(){
 const busy=ref(false);let worker:Worker|undefined,serial=0,rejectPending:((e:Error)=>void)|undefined;
 function cancel(){serial++;worker?.terminate();worker=undefined;busy.value=false;rejectPending?.(new Error('已取消'));rejectPending=undefined}
 function run(pixels:Uint8ClampedArray,mask:Uint8Array,width:number,height:number,custom=false,n=64,k=16){
  cancel();const id=++serial;busy.value=true;
  return new Promise<{label:string,pattern:Pattern}[]>((resolve,reject)=>{rejectPending=reject;worker=new Worker(new URL('./generation.worker.ts',import.meta.url),{type:'module'});const finish=()=>{worker?.terminate();worker=undefined;busy.value=false;rejectPending=undefined};worker.onmessage=({data:v})=>{if(id!==serial)return;finish();v.error?reject(Error(v.error)):resolve(v.result)};worker.onerror=()=>{if(id!==serial)return;finish();reject(Error('生成失败'))};const p=pixels.slice(),m=mask.slice();worker.postMessage({id,pixels:p.buffer,mask:m.buffer,width,height,custom,n,k},[p.buffer,m.buffer])});
 }
 onBeforeUnmount(cancel);return{busy,run,cancel};
}
