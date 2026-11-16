import test from 'node:test';
import assert from 'node:assert/strict';
import {hueDistanceSquared,distanceSquared} from '../frontend/src/color.ts';
import {generatePattern,generateV3Pattern,stats} from '../frontend/src/engine.ts';
import {parseProject} from '../frontend/src/project.ts';
test('v4 objective is continuous at neutral and treats red green blue directions equally',()=>{
 const neutral=[.5,0,0];assert.equal(hueDistanceSquared(neutral,neutral),0);assert.ok(Math.abs(hueDistanceSquared(neutral,[.6,0,0])-.01)<1e-12);
 for(const theta of [0,2*Math.PI/3,4*Math.PI/3]){
  const a=[.6,.1*Math.cos(theta),.1*Math.sin(theta)],sameHue=[.6,.08*Math.cos(theta),.08*Math.sin(theta)],rotated=[.6,.1*Math.cos(theta+.3),.1*Math.sin(theta+.3)];
  assert.ok(Math.abs(hueDistanceSquared(a,sameHue)-distanceSquared(a,sameHue))<1e-12);assert.ok(hueDistanceSquared(a,rotated)>distanceSquared(a,rotated));assert.ok(Math.abs(hueDistanceSquared(a,rotated)-hueDistanceSquared(rotated,a))<1e-12);
  const tiny=[.6,1e-10*Math.cos(theta),1e-10*Math.sin(theta)];assert.ok(hueDistanceSquared(tiny,[.6,0,0])<1e-15);
 }
});
test('v3 and v4 project grids coexist with capped valid colors and unchanged bead mask',()=>{
 const rgba=new Uint8ClampedArray(64*64*4),mask=new Uint8Array(64*64).fill(1);const colors=[[145,201,228],[88,160,100],[220,72,85],[235,235,235],[242,201,180]];
 for(let i=0;i<4096;i++)rgba.set([...colors[Math.floor(i/820)%colors.length],255],i*4);for(let i=0;i<64;i++){rgba[i*4+3]=0;mask[i]=0}
 const old=generateV3Pattern(rgba,64,64,mask,64,8),p=generatePattern(rgba,64,64,mask,64,8);
 assert.deepEqual(p.cells.map(c=>c===null),old.cells.map(c=>c===null));assert.equal(stats(p.cells).total,stats(old.cells).total);assert.ok(p.palette.length<=8);assert.notEqual(p.algorithm,old.algorithm);
 for(const pattern of [old,p]){const data={schemaVersion:2,pattern,locked:[],points:[],step:3,pitch:2.6,selectionMode:'whole',selectionDirty:false};const restored=parseProject(JSON.stringify(data)).pattern!;assert.deepEqual(restored.cells,pattern.cells);assert.equal(restored.algorithm,pattern.algorithm)}
});


