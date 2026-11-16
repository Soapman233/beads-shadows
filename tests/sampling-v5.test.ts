import test from 'node:test';import assert from 'node:assert/strict';
import {sampleGrid,generatePattern,stats} from '../frontend/src/engine.ts';import {validateProject} from '../frontend/src/project.ts';
test('dominant keeps real red at a red-white boundary; mask and transparent pixels remain consistent',()=>{
 const w=128,h=128,rgba=new Uint8ClampedArray(w*h*4),mask=new Uint8Array(w*h).fill(1);
 for(let y=0;y<h;y++)for(let x=0;x<w;x++)rgba.set(y%4===0?[255,255,255,255]:[255,0,0,255],(y*w+x)*4);
 const mean=sampleGrid(rgba,w,h,mask,32,'mean'),dom=sampleGrid(rgba,w,h,mask,32,'dominant');
 assert.deepEqual(mean.values[0],[255,63.75,63.75]);assert.deepEqual(dom.values[0],[255,0,0]);assert.deepEqual(mean.crop,dom.crop);assert.deepEqual(mean.values.map(v=>v===null),dom.values.map(v=>v===null));
 for(let i=0;i<16;i++){rgba.set([0,255,255,0],i*4);mask[i]=0}
 const colors=[{code:'R',hex:'#FF0000'},{code:'W',hex:'#FFFFFF'}];const a=generatePattern(rgba,w,h,mask,32,8,colors,'mean'),b=generatePattern(rgba,w,h,mask,32,8,colors,'dominant');assert.equal(stats(a.cells).total,stats(b.cells).total);assert.ok(b.cells.every(c=>c===null||c==='R'));assert.equal(b.sampling,'dominant');
});
test('sampling metadata accepts mean/dominant only and preserves existing grids',()=>{
 const pattern={width:2,height:1,palette:[{code:'R',hex:'#FF0000'}],cells:['R',null],colorLimit:8,paletteName:'fixture',algorithm:'oklab-hue-v4'};
 for(const sampling of ['mean','dominant']){const p=validateProject({schemaVersion:2,pattern:{...pattern,sampling},points:[],locked:[],step:3,pitch:2.6,selectionMode:'whole',selectionDirty:false});assert.equal(p.pattern!.sampling,sampling);assert.deepEqual(p.pattern!.cells,pattern.cells)}
assert.throws(()=>validateProject({schemaVersion:2,pattern:{...pattern,sampling:'mystery'},points:[]}));
});

