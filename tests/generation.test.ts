import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {MessageChannel} from 'node:worker_threads';
import {useGeneration} from '../frontend/src/useGeneration';

const {ref,createRenderer}=createRequire(new URL('../frontend/package.json',import.meta.url))('vue');

test('Vue reactive constraints cross a native structured-clone message boundary',async()=>{
 const observed:any[]=[];
 // Transport adapter only: actual MessagePort serialization/receipt, no algorithm.
 class TransportWorker {
  onmessage?: (event:any)=>void;
  onerror?:()=>void;
  private channel=new MessageChannel();
  constructor(){
   this.channel.port2.on('message',data=>{
    observed.push(data);
    this.onmessage?.({data:{id:data.id,result:[]}});
   });
  }
  postMessage(data:any,transfer:ArrayBuffer[]){this.channel.port1.postMessage(data,transfer)}
  terminate(){this.channel.port1.close();this.channel.port2.close()}
 }
 const original=Object.getOwnPropertyDescriptor(globalThis,'Worker');
 Object.defineProperty(globalThis,'Worker',{value:TransportWorker,configurable:true,writable:true});
 let generation!:ReturnType<typeof useGeneration>;
 // Mount minimal Vue host to register composable cleanup without browser/DOM.
 const renderer=createRenderer({insert(){},remove(){},createElement(){return {}},createText(){return {}},createComment(){return {}},setText(){},setElementText(){},parentNode(){return null},nextSibling(){return null},patchProp(){}});
 const app=renderer.createApp({setup(){generation=useGeneration();return ()=>null}});
 app.mount({});
 try{
  for(const input of [{required:ref([]).value,weight:3},{required:ref(['H7']).value,roi:ref([0,0,.5,1]).value,weight:3}]){
   const pixels=new Uint8ClampedArray([255,255,255,255]),mask=new Uint8Array([1]);
   const result=await generation.run(pixels,mask,1,1,true,32,8,input);
   assert.deepEqual(result,[]);
   assert.equal(generation.busy.value,false);
   const received=observed.at(-1);
   assert.deepEqual(received.constraints.required,Array.from(input.required));
   assert.deepEqual(received.constraints.roi,input.roi?Array.from(input.roi):undefined);
   assert.equal(received.constraints.weight,3);
   assert.deepEqual(Array.from(new Uint8ClampedArray(received.pixels)),[255,255,255,255]);
   assert.deepEqual(Array.from(new Uint8Array(received.mask)),[1]);
   assert.equal(pixels.byteLength,4);assert.equal(mask.byteLength,1);
  }
  assert.equal(observed.length,2);
 }finally{
  app.unmount();
  if(original)Object.defineProperty(globalThis,'Worker',original);else delete (globalThis as any).Worker;
 }
});
