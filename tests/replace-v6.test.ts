import test from 'node:test';import assert from 'node:assert/strict';
import {planColorReplace,isDefaultPaletteCompatible,DEFAULT_PALETTE,DEFAULT_PALETTE_INFO,DEFAULT_PALETTE_NAME,stats,type Pattern} from '../frontend/src/engine.ts';
import {parseProject} from '../frontend/src/project.ts';
const color=(code:string)=>({...DEFAULT_PALETTE.find(c=>c.code===code)!});
const fixture=():Pattern=>({width:3,height:2,palette:[color('C24'),color('C28')],cells:['C24',null,'C28','C24','C28','C24'],colorLimit:2,paletteName:DEFAULT_PALETTE_NAME,paletteInfo:{...DEFAULT_PALETTE_INFO},algorithm:'oklab-hue-v4'});
test('global replacement changes every source, merges existing target and preserves geometry/quantity immutably',()=>{
 const p=fixture(),before=structuredClone(p);assert.equal(isDefaultPaletteCompatible(p),true);const r=planColorReplace(p,'C24','C28');
 assert.equal(r.affected,3);assert.deepEqual(p,before);assert.deepEqual(r.pattern.cells,['C28',null,'C28','C28','C28','C28']);assert.equal(r.pattern.width,p.width);assert.equal(r.pattern.height,p.height);assert.equal(stats(r.pattern.cells).total,stats(p.cells).total);assert.equal(r.pattern.palette.length,1);assert.equal(r.pattern.palette[0].code,'C28');assert.deepEqual(r.pattern.paletteInfo,p.paletteInfo);
 const newTarget=planColorReplace(p,'C24','C3');assert.equal(newTarget.pattern.palette.length,2);assert.ok(!newTarget.pattern.palette.some(c=>c.code==='C24'));assert.ok(newTarget.pattern.palette.some(c=>c.code==='C3'));assert.ok(newTarget.pattern.palette.length<=p.colorLimit);
 const project={schemaVersion:2,pattern:newTarget.pattern,locked:[],points:[],step:3,pitch:2.6,selectionMode:'whole',selectionDirty:false};assert.deepEqual(parseProject(JSON.stringify(project)).pattern?.cells,newTarget.pattern.cells);assert.ok(parseProject(JSON.stringify(project)).pattern!.palette.length<=p.colorLimit);
});
test('replacement rejects locked source, invalid/no-op colors and incompatible palette snapshots',()=>{
 const p=fixture();assert.throws(()=>planColorReplace(p,'C24','C28',['C24']));assert.throws(()=>planColorReplace(p,'C24','C24'));assert.throws(()=>planColorReplace(p,'C24','NO_SUCH_CODE'));assert.throws(()=>planColorReplace(p,'C3','C28'));
 const foreign={...p,paletteInfo:{...DEFAULT_PALETTE_INFO,source:'https://example.invalid/foreign.csv'}};assert.equal(isDefaultPaletteCompatible(foreign),false);assert.throws(()=>planColorReplace(foreign,'C24','C28'));
 const changedHex={...p,palette:p.palette.map(c=>c.code==='C24'?{...c,hex:'#010203'}:c)};assert.equal(isDefaultPaletteCompatible(changedHex),false);assert.throws(()=>planColorReplace(changedHex,'C24','C28'));assert.equal(isDefaultPaletteCompatible({...p,paletteInfo:undefined}),false);
});
