import test from 'node:test';import assert from 'node:assert/strict';import {srgbLab,deltaE00} from '../experiments/metrics.ts';
test('independent CIEDE2000 matches author pairs including sign/neutral/hue wrapping branches',()=>{
 // Selected author testdata rows 1,4,7,9,11,15,16,17; expected values are published, not optimizer-generated.
 const pairs=[[50,2.6772,-79.7751,50,0,-82.7485,2.0425],[50,-1.3802,-84.2814,50,0,-82.7485,1],[50,0,0,50,-1,2,2.3669],[50,2.49,-.001,50,-2.49,.0009,7.1792],[50,2.49,-.001,50,-2.49,.0011,7.2195],[50,-.001,2.49,50,.0011,-2.49,4.7461],[50,2.5,0,50,0,-2.5,4.3065],[50,2.5,0,73,25,-18,27.1492]];
 for(const row of pairs){const a=row.slice(0,3),b=row.slice(3,6);assert.ok(Math.abs(deltaE00(a,b)-row[6])<.0001);assert.ok(Math.abs(deltaE00(a,b)-deltaE00(b,a))<1e-10)}
 assert.deepEqual(srgbLab([0,0,0]),[0,0,0]);const white=srgbLab([255,255,255]);assert.ok(Math.abs(white[0]-100)<.001);assert.ok(Math.abs(white[1])+Math.abs(white[2])<.001);
});
