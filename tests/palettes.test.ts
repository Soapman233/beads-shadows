import test from 'node:test';
import assert from 'node:assert/strict';
import {PALETTES,getPalette,restorePublicPaletteCache} from '../frontend/src/palettes/catalog';
import {generateConstrainedPattern} from '../frontend/src/constraints';
import {generatePattern,hexRgb,getPatternPalette,planColorReplace,stats} from '../frontend/src/engine';
import {parseProject} from '../frontend/src/project';

test('available reference palettes preserve brand snapshots through generation, restore and replacement',()=>{
 const available=PALETTES.filter(p=>p.available);
 assert.ok(available.length>=2);
 for(const reference of available){
  const first=reference.colors[0],rgb=hexRgb(first.hex);
  const last=reference.colors.slice().sort((a,b)=>{
   const distance=(hex:string)=>hexRgb(hex).reduce((s,v,i)=>s+(v-rgb[i])**2,0);
   return distance(b.hex)-distance(a.hex);
  })[0];
  const pixels=new Uint8ClampedArray(32*32*4),mask=new Uint8Array(1024).fill(1);
  for(let i=0;i<mask.length;i++)pixels.set([...hexRgb(i%32<16?first.hex:last.hex),255],i*4);
  mask[0]=0;
  const generated=generateConstrainedPattern(pixels,32,32,mask,32,8,{required:[first.code],roi:[0,0,.5,1],weight:3},reference.colors);
  // Same metadata attachment as production Worker. The algorithm is called
  // directly here; this test does not claim a browser/Worker transport check.
  const pattern={...generated,paletteId:reference.id,paletteName:reference.name,paletteInfo:{...reference.info}};
  const saved=parseProject(JSON.stringify({schemaVersion:2,pattern,paletteId:reference.id,constraints:generated.constraints,points:[],locked:[],step:3,pitch:2.6}));
  assert.equal(saved.paletteId,reference.id);
  assert.equal(saved.pattern!.paletteId,reference.id);
  assert.deepEqual(saved.pattern!.cells,pattern.cells);
  assert.deepEqual(saved.pattern!.palette,pattern.palette.map(({code,hex})=>({code,hex})));
  assert.deepEqual(saved.pattern!.constraints,generated.constraints);
  assert.equal(getPatternPalette(saved.pattern!)?.id,reference.id);
  const used=Object.keys(stats(saved.pattern!.cells).counts);assert.ok(used.length>=2);
  const replacement=planColorReplace(saved.pattern!,used[0],used[1]);
  assert.equal(replacement.pattern.paletteId,reference.id);
  assert.equal(stats(replacement.pattern.cells).total,stats(pattern.cells).total);
  assert.ok(replacement.pattern.cells.every((v,i)=>(v===null)===(pattern.cells[i]===null)));
  const other=available.find(p=>p.info.source!==reference.info.source)!;
  assert.ok(other);
  // A shared code must not let a different brand reinterpret saved colors.
  assert.throws(()=>planColorReplace({...saved.pattern!,paletteId:other.id},used[0],used[1]));
  const foreignCode=other.colors.find(c=>!reference.colors.some(v=>v.code===c.code));
  if(foreignCode)assert.throws(()=>planColorReplace(saved.pattern!,used[0],foreignCode.code));
 }
 assert.equal(getPalette('unknown-brand'),undefined);
});

test('cold start restores a public database palette and ignores invalid cached colors', () => {
  const version = {
    id: '00000000-0000-4000-8000-000000000001',
    brand: 'Fixture', series: 'Offline', sizeMm: 2.6, version: 'v1',
    source: 'https://example.test/fixture', licenseStatus: 'internal', status: 'published',
    colors: [{ code: 'B1', hex: '#112233' }, { code: 'R1', hex: '#FF1100' }],
  };
  const bad = { ...version, id: '00000000-0000-4000-8000-000000000002',
    colors: [{ code: 'B1', hex: 'invalid' }] };
  const original = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: { getItem: () => JSON.stringify([version, bad]) },
  });
  try {
    assert.equal(getPalette('db:' + version.id), undefined);
    restorePublicPaletteCache();
    const cached = getPalette('db:' + version.id);
    assert.ok(cached?.cached && cached.available);
    assert.deepEqual(cached.colors, version.colors);
    assert.equal(getPalette('db:' + bad.id), undefined);
    const rgba = new Uint8ClampedArray(32 * 32 * 4);
    for (let offset = 0; offset < rgba.length; offset += 4) rgba.set([17, 34, 51, 255], offset);
    const grid = generatePattern(rgba, 32, 32, new Uint8Array(1024).fill(1), 32, 8, cached.colors);
    assert.equal(stats(grid.cells).counts.B1, 1024);
  } finally {
    if (original) Object.defineProperty(globalThis, 'localStorage', original);
    else Reflect.deleteProperty(globalThis, 'localStorage');
  }
});
