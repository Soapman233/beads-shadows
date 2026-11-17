import test from 'node:test';
import assert from 'node:assert/strict';
import {generateConstrainedPattern,validateConstraints} from '../frontend/src/constraints';
import {generatePattern,stats} from '../frontend/src/engine';
import {parseProject} from '../frontend/src/project';

test('required candidate is retained without forcing unrelated cells; ROI keeps geometry and budget',()=>{
 const rgba=new Uint8ClampedArray(32*32*4),mask=new Uint8Array(32*32).fill(1);
 for(let i=0;i<mask.length;i++)rgba.set(i%32<16?[255,255,255,255]:[130,180,220,255],i*4);
 mask[0]=0;
 const normal=generatePattern(rgba,32,32,mask,32,8);
 const unconstrained=generateConstrainedPattern(rgba,32,32,mask,32,8,{required:[]});
 assert.deepEqual(unconstrained.cells,normal.cells);
 const p=generateConstrainedPattern(rgba,32,32,mask,32,8,{required:['H7'],roi:[0,0,.5,1],weight:3});
 assert.ok(p.palette.some(c=>c.code==='H7'));assert.ok(p.palette.length<=8);
 assert.deepEqual(p.cells.map(c=>c===null),normal.cells.map(c=>c===null));
 assert.equal(stats(p.cells).total,stats(normal.cells).total);
 assert.equal(stats(p.cells).counts.H7??0,0,'unused required candidate must not force any pixel');
 const restored=parseProject(JSON.stringify({schemaVersion:2,pattern:p,points:[],locked:[],step:3,pitch:2.6}));
 assert.deepEqual(restored.pattern!.constraints,p.constraints);
 assert.throws(()=>validateConstraints({required:['C24','C24']}));
 assert.throws(()=>validateConstraints({required:['not-a-color']}));
 assert.throws(()=>validateConstraints({required:[],roi:[.8,0,.2,1]}));
 assert.throws(()=>validateConstraints({required:[],weight:Infinity}));
});
