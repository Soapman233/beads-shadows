import {hexRgb, srgbToOklab, hueDistanceSquared} from './color';

export const REFINED_ALGORITHM = 'oklab-hue-swap-v1';

/** Independent, bounded one-color swap search. No change to source sampling. */
export function refinePalette(values: (number[] | null)[], colors: {code:string, hex:string}[], initial: number[]): number[] {
 const hist = new Map<string, {lab:number[], weight:number}>();
 for(const v of values)if(v){const key=v.join(',');const item=hist.get(key);if(item)item.weight++;else hist.set(key,{lab:srgbToOklab(v),weight:1})}
 const points=[...hist.values()],labs=colors.map(c=>srgbToOklab(hexRgb(c.hex)));
 const distances=points.map(p=>Float64Array.from(labs,c=>hueDistanceSquared(p.lab,c)));
 const frequencies=new Float64Array(colors.length);
 for(let i=0;i<points.length;i++){
  let nearest=0;for(let c=1;c<colors.length;c++)if(distances[i][c]<distances[i][nearest])nearest=c;
  frequencies[nearest]+=points[i].weight;
 }
 // Deterministic candidate pool: at most 24 actually used full-palette nearest colors.
 const candidates=colors.map((_,i)=>i).filter(i=>frequencies[i]>0)
  .sort((a,b)=>frequencies[b]-frequencies[a]||a-b).slice(0,24);
 const selected=initial.slice();
 const error=(indices:number[])=>points.reduce((sum,p,i)=>{
  let best=Infinity;for(const c of indices)best=Math.min(best,distances[i][c]);return sum+best*p.weight;
 },0);
 let current=error(selected);
 for(let round=0;round<2;round++){
  let nextError=current,slot=-1,replacement=-1;
  for(let s=0;s<selected.length;s++){
   const without=Float64Array.from(points,(_,i)=>{
    let best=Infinity;for(let j=0;j<selected.length;j++)if(j!==s)best=Math.min(best,distances[i][selected[j]]);return best;
   });
   for(const candidate of candidates){
    if(selected.includes(candidate))continue;
    let e=0;for(let i=0;i<points.length;i++)e+=Math.min(without[i],distances[i][candidate])*points[i].weight;
    if(e<nextError-1e-12){nextError=e;slot=s;replacement=candidate}
   }
  }
  if(slot<0)break;
  selected[slot]=replacement;current=nextError;
 }
 return selected;
}
