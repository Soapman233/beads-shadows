import test from 'node:test';
import assert from 'node:assert/strict';
import {generateCandidates,rareColors,planMerge,stats,type Pattern} from '../frontend/src/engine.ts';
test('candidate presets use legal capped colors and count white beads',()=>{
 const rgba=new Uint8ClampedArray(32*32*4);for(let i=0;i<1024;i++)rgba.set([255,255,255,255],i*4);
 const candidates=generateCandidates(rgba,32,32,new Uint8Array(1024).fill(255),[{code:'W',hex:'#FFFFFF'}]);
 assert.deepEqual(candidates.map(c=>[c.pattern.width,c.pattern.colorLimit]),[[32,8],[48,12],[64,16]]);
 for(const {pattern:p} of candidates){assert.ok(stats(p.cells).total>0);assert.ok(p.cells.every(c=>c==='W'));}
});
test('merge preserves locks, quantity and source; all rare colors retain a target',()=>{
 const p:Pattern={width:10,height:10,cells:[...Array(97).fill('A'),'B','C',null],palette:[{code:'A',hex:'#000000'},{code:'B',hex:'#010101'},{code:'C',hex:'#FFFFFF'}],colorLimit:8,paletteName:'fixture'};
 const original=structuredClone(p);assert.deepEqual(rareColors(p),['B','C']);
 const merged=planMerge(p,['C']);assert.deepEqual(p,original);assert.equal(merged.mapping.B,'A');assert.equal(merged.mapping.C,undefined);assert.equal(merged.affected,1);assert.equal(stats(merged.pattern.cells).total,99);assert.ok(merged.pattern.palette.some(c=>c.code==='C'));
 assert.deepEqual(structuredClone(p),original);assert.equal(planMerge(p,['A','B','C']).affected,0);
 const tiny={...p,width:2,height:1,cells:['B','C']};const tinyMerged=planMerge(tiny,[]);assert.equal(stats(tinyMerged.pattern.cells).total,2);assert.equal(Object.keys(stats(tinyMerged.pattern.cells).counts).length,1);
 const zero={...p,palette:[...p.palette,{code:'Z',hex:'#FF0000'}]};assert.ok(planMerge(zero,['Z']).pattern.palette.some(c=>c.code==='Z'));
});
