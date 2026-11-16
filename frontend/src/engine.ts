import {MARD_COLORS} from './palettes/mard';
import {refinePalette,REFINED_ALGORITHM} from './refinement';
export {REFINED_ALGORITHM} from './refinement';
import {hexRgb,srgbToOklab,distanceSquared,hueDistanceSquared} from './color';
export {hexRgb,srgbToOklab,distanceSquared,hueDistanceSquared} from './color';
export type Color={code:string,hex:string,name?:string};
export type PaletteInfo={brand:string,series:string,version:string,source:string,license:string,note:string};
export type Pattern={width:number,height:number,palette:Color[],cells:(string|null)[],colorLimit:number,paletteName:string,paletteInfo?:PaletteInfo,algorithm?:string,sampling?:SamplingMode};
export type SamplingMode='mean'|'dominant';
export type SampleGrid={width:number,height:number,crop:[number,number,number,number],values:(number[]|null)[]};
export const DEMO=['#171C25','#454B59','#808895','#BEC4CC','#FAF6EB','#59383C','#985051','#DC8B80','#F0BD9E','#643B29','#A56B39','#D4A257','#F1D77B','#354C39','#637B46','#9FAE6D','#174C50','#378687','#91BABB','#253858','#516D9C','#A1AED4','#694F7E','#AA85AE'].map((hex,i)=>({code:`D${String(i+1).padStart(2,'0')}`,hex}));
export const DEFAULT_PALETTE:Color[]=MARD_COLORS;
export const DEFAULT_PALETTE_INFO:PaletteInfo={brand:'MARD',series:'经典221编号体系中的当前220色子集（暂不纳入H1）',version:'beadcolors社区参考 2026-11-15',source:'https://github.com/maxcleme/beadcolors/blob/master/raw/mard.csv',license:'MIT · Copyright (c) 2020 maxcleme',note:'社区屏幕参考色，非厂家认证；H1暂不纳入当前子集，其材质属性待核实。备料与色差需核对实物。'};
export const DEFAULT_PALETTE_NAME='MARD 221体系 · 220实色参考';
export const COLOR_ALGORITHM='oklab-hue-v4';
const V3_ALGORITHM='oklab-greedy-v3';
type Metric=(a:number[],b:number[])=>number;
export function stats(cells:(string|null)[]){const counts:Record<string,number>=Object.create(null);for(const c of cells)if(c!==null)counts[c]=(counts[c]??0)+1;return{total:Object.values(counts).reduce((a,b)=>a+b,0),counts}}
export function canvasPoint(x:number,y:number,rect:{left:number,top:number,width:number,height:number},width:number,height:number){return{x:Math.min(width-1,Math.max(0,(x-rect.left)*width/rect.width)),y:Math.min(height-1,Math.max(0,(y-rect.top)*height/rect.height))}}
export const isCurrent=(a:string,b:number,c:string,d:number)=>a===c&&b===d;
function validate(colors:Color[],k:number){if(![8,12,16,24,32].includes(k))throw Error('颜色上限无效');if(!colors.length||colors.some(c=>!/^#[0-9a-f]{6}$/i.test(c.hex)||typeof c.code!=='string'||!c.code)||new Set(colors.map(c=>c.code)).size!==colors.length)throw Error('色卡无效')}
// Optional flat-art representative: group valid foreground RGB into 16-wide bins,
// pick the largest group, then its actual pixel nearest to that group's centroid.
// This is an independent implementation. It can discard minority line/detail colors;
// therefore it is opt-in and never changes the grid's foreground coverage decision.
function dominantSample(rgba:Uint8ClampedArray,w:number,mask:Uint8Array,sx:number,ex:number,sy:number,ey:number):number[]{
 const bins=new Map<number,number[]>();
 const keyAt=(i:number)=>((rgba[i]>>4)<<8)|((rgba[i+1]>>4)<<4)|(rgba[i+2]>>4);
 for(let y=sy;y<ey;y++)for(let x=sx;x<ex;x++){
  const q=y*w+x,i=q*4;if(!mask[q]||!rgba[i+3])continue;
  const key=keyAt(i),entry=bins.get(key)??[0,0,0,0];
  entry[0]++;for(let c=0;c<3;c++)entry[c+1]+=rgba[i+c];bins.set(key,entry);
 }
 let winner=-1,support=0;
 for(const [key,entry] of bins)if(entry[0]>support||(entry[0]===support&&key<winner)){winner=key;support=entry[0]}
 const group=bins.get(winner)!;const mean=group.slice(1).map(v=>v/support);
 let score=Infinity,result=mean;
 for(let y=sy;y<ey;y++)for(let x=sx;x<ex;x++){
  const q=y*w+x,i=q*4;if(!mask[q]||!rgba[i+3]||keyAt(i)!==winner)continue;
  const pixel=[rgba[i],rgba[i+1],rgba[i+2]],d=distanceSquared(pixel,mean);
  if(d<score){score=d;result=pixel}
 }
 return result;
}
// V2 sampling deliberately retained for a controlled color-only comparison.
// Nonzero alpha is a binary validity gate; opaque and partially transparent foreground have equal weight.
export function sampleGrid(rgba:Uint8ClampedArray,w:number,h:number,mask:Uint8Array,n:number,sampling:SamplingMode='mean'):SampleGrid{
 if(![32,48,64].includes(n))throw Error('尺寸无效');if(!['mean','dominant'].includes(sampling))throw Error('取色模式无效');
 if(!Number.isInteger(w)||!Number.isInteger(h)||w<1||h<1||rgba.length!==w*h*4||mask.length!==w*h)throw Error('图像和掩码尺寸不一致');
 let x0=w,y0=h,x1=-1,y1=-1;for(let y=0;y<h;y++)for(let x=0;x<w;x++)if(mask[y*w+x]&&rgba[(y*w+x)*4+3]){x0=Math.min(x0,x);y0=Math.min(y0,y);x1=Math.max(x1,x);y1=Math.max(y1,y)}
 if(x1<0)throw Error('没有可生成的前景，请修正选区');
 const pad=Math.max(1,Math.round(Math.max(x1-x0+1,y1-y0+1)*.025));x0=Math.max(0,x0-pad);y0=Math.max(0,y0-pad);x1=Math.min(w,x1+pad+1);y1=Math.min(h,y1+pad+1);
 const gh=Math.round(n*(y1-y0)/(x1-x0));if(gh<1||gh>128||gh*n>8192)throw Error('主体比例过于狭长，请调整选区');
 const values:(number[]|null)[]=[];for(let j=0;j<gh;j++)for(let i=0;i<n;i++){
 const sx=Math.floor(x0+i*(x1-x0)/n),ex=Math.min(w,Math.max(sx+1,Math.ceil(x0+(i+1)*(x1-x0)/n))),sy=Math.floor(y0+j*(y1-y0)/gh),ey=Math.min(h,Math.max(sy+1,Math.ceil(y0+(j+1)*(y1-y0)/gh)));let count=0;const sum=[0,0,0];for(let y=sy;y<ey;y++)for(let x=sx;x<ex;x++){const q=y*w+x;if(mask[q]&&rgba[q*4+3]){count++;for(let c=0;c<3;c++)sum[c]+=rgba[q*4+c]}}values.push(count/Math.max(1,(ex-sx)*(ey-sy))>=.35?(sampling==='dominant'?dominantSample(rgba,w,mask,sx,ex,sy,ey):sum.map(s=>s/count)):null)}
 if(!values.some(v=>v!==null))throw Error('网格中没有有效前景');
 return{width:n,height:gh,crop:[x0,y0,x1,y1],values};
}
function nearestIndex(v:number[],coordinates:number[][],metric:Metric=distanceSquared){let best=0,score=Infinity;for(let i=0;i<coordinates.length;i++){const d=metric(v,coordinates[i]);if(d<score){score=d;best=i}}return best}
function legacySubset(grid:SampleGrid,colors:Color[],k:number){const rgb=colors.map(c=>hexRgb(c.hex)),freq:Record<string,number>=Object.create(null);for(const v of grid.values)if(v){const code=colors[nearestIndex(v,rgb)].code;freq[code]=(freq[code]??0)+1}return Object.keys(freq).sort((a,b)=>freq[b]-freq[a]||a.localeCompare(b)).slice(0,k).map(code=>colors.findIndex(c=>c.code===code))}
function makePattern(grid:SampleGrid,colors:Color[],indices:number[],k:number,perceptual:boolean,algorithm:string,metric:Metric=distanceSquared):Pattern{
 const coords=indices.map(i=>perceptual?srgbToOklab(hexRgb(colors[i].hex)):hexRgb(colors[i].hex));
 const cells=grid.values.map(v=>v?colors[indices[nearestIndex(perceptual?srgbToOklab(v):v,coords,metric)]].code:null),used=new Set(cells);
 return{width:grid.width,height:grid.height,palette:indices.map(i=>colors[i]).filter(c=>used.has(c.code)).map(c=>({...c})),cells,colorLimit:k,paletteName:colors===DEFAULT_PALETTE?DEFAULT_PALETTE_NAME:colors===DEMO?'通用演示色板 · 非品牌实物色号':'用户自带色卡',...(colors===DEFAULT_PALETTE?{paletteInfo:{...DEFAULT_PALETTE_INFO}}:{}),algorithm};
}
// All grid cells have equal weight; duplicate representative colors aggregate their cell counts.
function optimize(grid:SampleGrid,colors:Color[],k:number,metric:Metric=distanceSquared,extraCandidate?:number[]){
 const hist=new Map<string,{lab:number[],weight:number}>();for(const v of grid.values)if(v){const key=v.join(',');const item=hist.get(key);if(item)item.weight++;else hist.set(key,{lab:srgbToOklab(v),weight:1})}
 const points=[...hist.values()],labs=colors.map(c=>srgbToOklab(hexRgb(c.hex)));
 const distances=points.map(p=>Float64Array.from(labs,c=>metric(p.lab,c)));
 const best=new Float64Array(points.length).fill(Infinity),selected:number[]=[];
 for(let iteration=0;iteration<Math.min(k,colors.length);iteration++){
  let choice=-1,score=Infinity;
  for(let c=0;c<colors.length;c++){if(selected.includes(c))continue;let e=0;for(let i=0;i<points.length;i++)e+=Math.min(best[i],distances[i][c])*points[i].weight;if(e<score){score=e;choice=c}}
  let current=0;for(let i=0;i<points.length;i++)current+=best[i]*points[i].weight;
  if(choice<0||score>=current-1e-15)break;selected.push(choice);for(let i=0;i<points.length;i++)best[i]=Math.min(best[i],distances[i][choice]);
 }
 const fallback=legacySubset(grid,colors,k);
 const error=(indices:number[])=>points.reduce((sum,p,i)=>sum+Math.min(...indices.map(c=>distances[i][c]))*p.weight,0);
 let result=error(fallback)<error(selected)?fallback:selected;if(extraCandidate?.length&&error(extraCandidate)<error(result))result=extraCandidate;return result;
}
export function generateLegacyPattern(rgba:Uint8ClampedArray,w:number,h:number,mask:Uint8Array,n:number,k:number,colors:Color[]=DEFAULT_PALETTE):Pattern{validate(colors,k);const g=sampleGrid(rgba,w,h,mask,n);return makePattern(g,colors,legacySubset(g,colors,k),k,false,'rgb-frequency-v2')}
export function generateV3Pattern(rgba:Uint8ClampedArray,w:number,h:number,mask:Uint8Array,n:number,k:number,colors:Color[]=DEFAULT_PALETTE):Pattern{validate(colors,k);const g=sampleGrid(rgba,w,h,mask,n);return makePattern(g,colors,optimize(g,colors,k),k,true,V3_ALGORITHM)}
export function generatePattern(rgba:Uint8ClampedArray,w:number,h:number,mask:Uint8Array,n:number,k:number,colors:Color[]=DEFAULT_PALETTE,sampling:SamplingMode='mean'):Pattern{validate(colors,k);const g=sampleGrid(rgba,w,h,mask,n,sampling),v3=optimize(g,colors,k);const p=makePattern(g,colors,optimize(g,colors,k,hueDistanceSquared,v3),k,true,COLOR_ALGORITHM,hueDistanceSquared);return sampling==='dominant'?{...p,sampling}:p}
export function generateRefinedPattern(rgba:Uint8ClampedArray,w:number,h:number,mask:Uint8Array,n:number,k:number,colors:Color[]=DEFAULT_PALETTE,sampling:SamplingMode='mean'):Pattern{
 const baseline=generatePattern(rgba,w,h,mask,n,k,colors,sampling),grid=sampleGrid(rgba,w,h,mask,n,sampling);
 const indices=baseline.palette.map(c=>colors.findIndex(v=>v.code===c.code));
 const p=makePattern(grid,colors,refinePalette(grid.values,colors,indices),k,true,REFINED_ALGORITHM,hueDistanceSquared);
 return sampling==='dominant'?{...p,sampling}:p;
}
export function diagnoseRefinement(rgba:Uint8ClampedArray,w:number,h:number,mask:Uint8Array,n:number,k:number,colors:Color[]=DEFAULT_PALETTE,sampling:SamplingMode='mean'){
 const grid=sampleGrid(rgba,w,h,mask,n,sampling),baseline=generatePattern(rgba,w,h,mask,n,k,colors,sampling),refined=generateRefinedPattern(rgba,w,h,mask,n,k,colors,sampling);
 return{grid,baseline,refined,errors:{baseline:patternHueError(grid,baseline),refined:patternHueError(grid,refined)}};
}
export function generateCandidates(rgba:Uint8ClampedArray,w:number,h:number,mask:Uint8Array,colors:Color[]=DEFAULT_PALETTE){return[{label:'更好拼',n:32,k:8},{label:'推荐',n:48,k:12},{label:'更细致',n:64,k:16}].map(({label,n,k})=>({label,pattern:generatePattern(rgba,w,h,mask,n,k,colors)}))}
export function patternError(grid:SampleGrid,pattern:Pattern){const labs=new Map(pattern.palette.map(c=>[c.code,srgbToOklab(hexRgb(c.hex))]));let sum=0,count=0;for(let i=0;i<grid.values.length;i++){const v=grid.values[i];if(v){const c=labs.get(pattern.cells[i]!);if(!c)throw Error('图纸缺失有效色');sum+=distanceSquared(srgbToOklab(v),c);count++}}return sum/count}
export function diagnosePattern(rgba:Uint8ClampedArray,w:number,h:number,mask:Uint8Array,n:number,k:number,colors:Color[]=DEFAULT_PALETTE){validate(colors,k);const grid=sampleGrid(rgba,w,h,mask,n),subset=legacySubset(grid,colors,k),legacy=makePattern(grid,colors,subset,k,false,'rgb-frequency-v2'),remapped=makePattern(grid,colors,subset,k,true,'legacy-subset-oklab-remap'),optimized=makePattern(grid,colors,optimize(grid,colors,k),k,true,V3_ALGORITHM),full=makePattern(grid,colors,colors.map((_,i)=>i),colors.length,true,'oklab-full-diagnostic');return{grid,full,legacy,optimized,errors:{legacy:patternError(grid,legacy),legacyRemapped:patternError(grid,remapped),optimized:patternError(grid,optimized),full:patternError(grid,full)}}}
export function rareColors(pattern:Pattern):string[]{const {counts,total}=stats(pattern.cells);return Object.keys(counts).filter(code=>counts[code]<5||counts[code]/total<.005).sort((a,b)=>counts[a]-counts[b]||a.localeCompare(b))}
// Both provenance and exact reference colors are required: a demo/foreign palette
// can share a code such as D11 while assigning a completely different RGB value.
export function isDefaultPaletteCompatible(pattern:Pattern):boolean{
 if(pattern.paletteInfo?.source!==DEFAULT_PALETTE_INFO.source||!pattern.palette.length)return false;
 const allowed=new Map(DEFAULT_PALETTE.map(c=>[c.code,c.hex.toLowerCase()]));
 const codes=new Set<string>();
 for(const c of pattern.palette){
  if(typeof c.code!=='string'||typeof c.hex!=='string'||allowed.get(c.code)!==c.hex.toLowerCase()||codes.has(c.code))return false;
  codes.add(c.code);
 }
 return pattern.cells.every(code=>code===null||codes.has(code));
}
export function planColorReplace(pattern:Pattern,fromCode:string,toCode:string,locked:string[]=[]):{pattern:Pattern,affected:number}{
 if(!isDefaultPaletteCompatible(pattern))throw Error('当前图纸与所选来源色卡不兼容，请使用当前参考色卡重新生成后再整色替换');
 if(fromCode===toCode)throw Error('替换后的色号不能与原色号相同');
 const target=DEFAULT_PALETTE.find(c=>c.code===toCode);
 if(!target)throw Error('目标色号不在当前参考色卡中');
 if(!pattern.palette.some(c=>c.code===fromCode))throw Error('原色号不在当前图纸色表中');
 if(locked.includes(fromCode))throw Error('原色号已锁定，请先解锁再替换');
 const affected=stats(pattern.cells).counts[fromCode]??0;
 if(!affected)throw Error('原色号在当前图纸中没有实际用量');
 const palette=pattern.palette.filter(c=>c.code!==fromCode).map(c=>({...c}));
 if(!palette.some(c=>c.code===toCode))palette.push({...target});
 if(!Number.isInteger(pattern.colorLimit)||palette.length>pattern.colorLimit)throw Error('替换后的色表超过当前颜色上限，请先调整方案');
 const cells=pattern.cells.map(code=>code===fromCode?toCode:code);
 return{pattern:{...pattern,palette,cells,...(pattern.paletteInfo?{paletteInfo:{...pattern.paletteInfo}}:{})},affected};
}
export function planMerge(pattern:Pattern,locked:string[]=[]):{pattern:Pattern,mapping:Record<string,string>,affected:number}{
 const {counts}=stats(pattern.cells),used=pattern.palette.filter(c=>(counts[c.code]??0)>0),protectedCodes=new Set(locked),rare=new Set(rareColors(pattern));
 let targets=used.filter(c=>!rare.has(c.code)||protectedCodes.has(c.code));if(!targets.length&&used.length)targets=[used.slice().sort((a,b)=>counts[b.code]-counts[a.code]||a.code.localeCompare(b.code))[0]];
 const metric=pattern.algorithm===COLOR_ALGORITHM||pattern.algorithm===REFINED_ALGORITHM?hueDistanceSquared:distanceSquared;
 const coords=targets.map(c=>srgbToOklab(hexRgb(c.hex))),targetCodes=new Set(targets.map(c=>c.code)),mapping:Record<string,string>=Object.create(null);
 for(const c of used)if(rare.has(c.code)&&!protectedCodes.has(c.code)&&!targetCodes.has(c.code))mapping[c.code]=targets[nearestIndex(srgbToOklab(hexRgb(c.hex)),coords,metric)].code;
 let affected=0;const cells=pattern.cells.map(code=>{if(code!==null&&Object.hasOwn(mapping,code)){affected++;return mapping[code]}return code}),after=stats(cells).counts;
 return{pattern:{...pattern,palette:pattern.palette.filter(c=>(after[c.code]??0)>0||protectedCodes.has(c.code)).map(c=>({...c})),cells},mapping,affected};
}

export function patternHueError(grid:SampleGrid,pattern:Pattern){const labs=new Map(pattern.palette.map(c=>[c.code,srgbToOklab(hexRgb(c.hex))]));let sum=0,count=0;for(let i=0;i<grid.values.length;i++){const v=grid.values[i];if(v){const c=labs.get(pattern.cells[i]!);if(!c)throw Error('图纸缺失有效色');sum+=hueDistanceSquared(srgbToOklab(v),c);count++}}return sum/count}
export function diagnoseHuePattern(rgba:Uint8ClampedArray,w:number,h:number,mask:Uint8Array,n:number,k:number,colors:Color[]=DEFAULT_PALETTE){
 validate(colors,k);const grid=sampleGrid(rgba,w,h,mask,n),v3Indices=optimize(grid,colors,k);
 const legacy=makePattern(grid,colors,legacySubset(grid,colors,k),k,false,'rgb-frequency-v2');
 const previous=makePattern(grid,colors,v3Indices,k,true,V3_ALGORITHM);
 const optimized=makePattern(grid,colors,optimize(grid,colors,k,hueDistanceSquared,v3Indices),k,true,COLOR_ALGORITHM,hueDistanceSquared);
 const full=makePattern(grid,colors,colors.map((_,i)=>i),colors.length,true,'oklab-hue-full-diagnostic',hueDistanceSquared);
 const measure=(p:Pattern)=>({oklab:patternError(grid,p),hue:patternHueError(grid,p)});
 return{grid,legacy,previous,v3:previous,optimized,full,errors:{legacy:measure(legacy),v3:measure(previous),optimized:measure(optimized),full:measure(full)}};
}
