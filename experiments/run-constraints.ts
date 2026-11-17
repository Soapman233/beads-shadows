/** Fixed protocol. No tuning, downloads, private image publication or hashes. */
import fs from 'node:fs';
import os from 'node:os';
import assert from 'node:assert/strict';
import {generateConstrainedPattern,type Constraints} from '../frontend/src/constraints';
import {generatePattern,sampleGrid,DEFAULT_PALETTE,hexRgb,stats,type Pattern} from '../frontend/src/engine';
import {srgbLab,deltaE00,summarize} from './metrics';

const dir='experiments/generated';
const manifest=JSON.parse(fs.readFileSync(dir+'/manifest.json','utf8'));
// Fixed before evaluation: no tuning on this split or after seeing holdout results.
const newHoldout=new Set(['brick','grass','gravel','camera','clock','rocket']);
const roiFor=(id:string):[number,number,number,number]=>newHoldout.has(id)?[.25,.25,.75,.75]:id==='astronaut'?[.28,.1,.62,.52]:id==='chelsea'?[.25,.15,.7,.65]:id==='coffee'?[.1,.25,.8,.85]:[.25,.2,.75,.65];
const splitFor=(id:string)=>id==='astronaut'||/^synthetic-[13579]$/.test(id)?'development':'holdout';
const protocol={grid:64,k:16,sampling:'mean',weight:3,split:'astronaut + odd synthetic development; chelsea/coffee + even synthetic + all six new real photos holdout',required:'one current palette color nearest to ROI mean, chosen from input only',roi:'normalized source coordinates; predefined by sample id; all six new real photos center .25,.25,.75,.75',boundary:'valid grid cell with a 4-neighbor outside mask/grid or sampled-reference CIEDE2000 > 10',pixelReference:'all effective source pixels mapped by pixel center to grid cell; alpha/255 weights; no resampling per algorithm',control:'selector-control is full-frame ROI weight1; default hue4 separately shown because its initialization differs',limitation:'six new real photos include five grayscale and one color scene; no licensed color illustration holdout',tuned:false};
fs.writeFileSync(dir+'/constraints-protocol.json',JSON.stringify({protocol,inputs:manifest.map((m:any)=>({id:m.id,split:splitFor(m.id),roi:roiFor(m.id),source:m.source,license:m.license}))},null,2));

function weighted(values:{v:number,w:number}[]){
 if(!values.length)return {mean:null,p95:null,count:0};
 const total=values.reduce((s,v)=>s+v.w,0),sorted=values.slice().sort((a,b)=>a.v-b.v);let running=0,p95=0;
 for(const v of sorted){running+=v.w;if(running>=total*.95){p95=v.v;break}}
 return{mean:values.reduce((s,v)=>s+v.w*v.v,0)/total,p95,count:values.length};
}
function isolated(p:Pattern){return p.cells.filter((code,i)=>code!==null&&![-1,0,1].some(dy=>[-1,0,1].some(dx=>{const x=i%p.width+dx,y=Math.floor(i/p.width)+dy;return (dx||dy)&&x>=0&&y>=0&&x<p.width&&y<p.height&&p.cells[y*p.width+x]===code}))).length}
const rows:any[]=[];
const sources=[...manifest.map((m:any)=>({...m,path:dir+'/'+m.id+'.json'})),{id:'private-user',public:false,path:'../mvp/samples/color-v3/user-anime/source.json',kind:'private illustration'}];
for(const item of sources){
 if(!fs.existsSync(item.path))continue;
 const input=JSON.parse(fs.readFileSync(item.path,'utf8')),rgba=new Uint8ClampedArray(input.rgba),mask=new Uint8Array(input.mask),grid=sampleGrid(rgba,input.width,input.height,mask,64),roi=roiFor(item.id);
 const refs=grid.values.map(v=>v?srgbLab(v):null),roiCells=grid.values.map((v,i)=>{
  const x=(grid.crop[0]+(i%grid.width+.5)*(grid.crop[2]-grid.crop[0])/grid.width)/input.width,y=(grid.crop[1]+(Math.floor(i/grid.width)+.5)*(grid.crop[3]-grid.crop[1])/grid.height)/input.height;
  return !!v&&x>=roi[0]&&x<=roi[2]&&y>=roi[1]&&y<=roi[3];
 });
 const chosen=grid.values.filter((v,i)=>v&&roiCells[i]) as number[][];
 const mean=chosen.length?[0,1,2].map(c=>chosen.reduce((s,v)=>s+v[c],0)/chosen.length):[128,128,128];
 const required=DEFAULT_PALETTE.slice().sort((a,b)=>deltaE00(srgbLab(mean),srgbLab(hexRgb(a.hex)))-deltaE00(srgbLab(mean),srgbLab(hexRgb(b.hex))))[0].code;
 const boundary=refs.map((v,i)=>v&&[[1,0],[-1,0],[0,1],[0,-1]].some(([dx,dy])=>{const x=i%grid.width+dx,y=Math.floor(i/grid.width)+dy;if(x<0||y<0||x>=grid.width||y>=grid.height)return true;const n=refs[y*grid.width+x];return !n||deltaE00(v,n)>10}));
 const variants:[string,Constraints|null][]=[['default',null],['selector-control',{required:[],roi:[0,0,1,1],weight:1}],['required',{required:[required]}],['roi',{required:[],roi,weight:3}],['combined',{required:[required],roi,weight:3}]];
 const runs:any={},previews:any={};let base:Pattern|undefined;
 for(const [name,c] of variants){
  const start=performance.now(),p=c?generateConstrainedPattern(rgba,input.width,input.height,mask,64,16,c):generatePattern(rgba,input.width,input.height,mask,64,16),elapsedMs=performance.now()-start;
  base??=p;assert.deepEqual(p.cells.map(v=>v===null),base.cells.map(v=>v===null));assert.ok(p.palette.length<=16);
  const colors=new Map(p.palette.map(c=>[c.code,srgbLab(hexRgb(c.hex))]));
  const cells=refs.flatMap((v,i)=>v?[{v:deltaE00(v,colors.get(p.cells[i]!)!),i}]:[]);
  const pixelGroups:Record<string,{v:number,w:number}[]>={all:[],roi:[],nonRoi:[],boundary:[],nonBoundary:[]};
  const [x0,y0,x1,y1]=grid.crop;
  for(let y=y0;y<y1;y++)for(let x=x0;x<x1;x++){
   const q=y*input.width+x,alpha=rgba[q*4+3]/255;if(!mask[q]||!alpha)continue;
   const gx=Math.min(grid.width-1,Math.floor((x+.5-x0)*grid.width/(x1-x0))),gy=Math.min(grid.height-1,Math.floor((y+.5-y0)*grid.height/(y1-y0))),i=gy*grid.width+gx,code=p.cells[i];if(code===null)continue;
   const e={v:deltaE00(srgbLab(Array.from(rgba.slice(q*4,q*4+3))),colors.get(code)!),w:alpha},inside=(x+.5)/input.width>=roi[0]&&(x+.5)/input.width<=roi[2]&&(y+.5)/input.height>=roi[1]&&(y+.5)/input.height<=roi[3];
   pixelGroups.all.push(e);pixelGroups[inside?'roi':'nonRoi'].push(e);pixelGroups[boundary[i]?'boundary':'nonBoundary'].push(e);
  }
  runs[name]={elapsedMs,beans:stats(p.cells).total,actualColors:Object.keys(stats(p.cells).counts).length,candidateColors:p.palette.length,isolated8:isolated(p),cellDE00:summarize(cells.map(e=>e.v)),pixels:Object.fromEntries(Object.entries(pixelGroups).map(([k,v])=>[k,weighted(v)]))};
  if(['astronaut','coffee','synthetic-6','rocket','camera'].includes(item.id))previews[name]=p;
  if(item.id==='astronaut'&&['default','roi'].includes(name)){
   const warm=[];for(let repeat=0;repeat<3;repeat++){const t=performance.now();if(c)generateConstrainedPattern(rgba,input.width,input.height,mask,64,16,c);else generatePattern(rgba,input.width,input.height,mask,64,16);warm.push(performance.now()-t)}
   runs[name].warm3Ms=warm;
  }
 }
 if(Object.keys(previews).length)fs.writeFileSync(dir+'/'+item.id+'-constraints-preview.json',JSON.stringify({input,patterns:previews}));
 rows.push({id:item.id,public:item.public!==false,kind:item.kind,split:splitFor(item.id),roi,required,runs});
 console.log(item.id,JSON.stringify(Object.fromEntries(Object.entries(runs).map(([k,v]:any)=>[k,{all:v.pixels.all.mean,roi:v.pixels.roi.mean,nonRoi:v.pixels.nonRoi.mean}]))));
}
const publicRows=rows.filter(r=>r.public),privateRows=rows.filter(r=>!r.public);
const machine={node:process.version,platform:process.platform,cpu:os.cpus()[0]?.model,logicalCores:os.cpus().length,ramGiB:Math.round(os.totalmem()/2**30)};
fs.writeFileSync(dir+'/constraints-results.json',JSON.stringify({protocol,machine,rows:publicRows},null,2));
fs.mkdirSync('experiments/private',{recursive:true});fs.writeFileSync('experiments/private/constraints-results.json',JSON.stringify({protocol,machine,rows:privateRows},null,2));
