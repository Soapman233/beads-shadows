import test from 'node:test';
import assert from 'node:assert/strict';
import {generatePattern,stats,canvasPoint,isCurrent,DEMO} from '../frontend/src/engine.ts';

test('scaled canvas coordinates and clamping',()=>{
 assert.deepEqual(canvasPoint(110,70,{left:10,top:20,width:200,height:100},400,200),{x:200,y:100});
 assert.deepEqual(canvasPoint(-1,999,{left:10,top:20,width:200,height:100},400,200),{x:0,y:199});
});
test('empty foreground is rejected',()=>{
 assert.throws(()=>generatePattern(new Uint8ClampedArray(16),2,2,new Uint8Array(4),32,8),/前景/);
});
test('transparent background cannot contaminate foreground color',()=>{
 const rgba=new Uint8ClampedArray(64*64*4),mask=new Uint8Array(64*64);
 for(let i=0;i<4096;i++){rgba.set([0,0,0,0],i*4);if(i%64>=16&&i%64<48&&Math.floor(i/64)>=16&&Math.floor(i/64)<48){rgba.set([250,246,235,255],i*4);mask[i]=255}}
 const pattern=generatePattern(rgba,64,64,mask,32,8,DEMO);
 assert.deepEqual(pattern.palette.map(c=>c.hex),['#FAF6EB']);
 assert.ok(pattern.cells.some(c=>c===null));
});
test('color cap, valid codes and quantities survive edit and undo',()=>{
 const rgba=new Uint8ClampedArray(64*64*4),mask=new Uint8Array(4096).fill(255);
 for(let i=0;i<4096;i++)rgba.set([(i*31)%256,(i*71)%256,(i*113)%256,255],i*4);
 const p=generatePattern(rgba,64,64,mask,48,8),codes=new Set(p.palette.map(c=>c.code));
 assert.ok(codes.size<=8);assert.equal(p.cells.length,p.width*p.height);assert.ok(p.cells.every(c=>c===null||codes.has(c)));
 const before=stats(p.cells),old=p.cells[0];p.cells[0]=null;assert.equal(stats(p.cells).total,before.total-1);p.cells[0]=old;assert.deepEqual(stats(p.cells),before);
 assert.equal(Object.values(before.counts).reduce((a,b)=>a+b,0),p.cells.filter(c=>c!==null).length);
});
test('old image and stale revision results are rejected',()=>{
 assert.equal(isCurrent('old',2,'new',2),false);assert.equal(isCurrent('new',1,'new',2),false);assert.equal(isCurrent('new',2,'new',2),true);
});
