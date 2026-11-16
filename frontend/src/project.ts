import {stats,type Pattern} from './engine';
export type Project={schemaVersion:2,pattern?:Pattern,source?:string,mask?:string,box?:number[],points:{x:number,y:number,label:number}[],locked:string[],step:number,pitch:number,selectionMode:string,selectionDirty:boolean,tuning?:{width:number,colors:number}};
const fail=()=>{throw Error('项目格式无效或超过限制')};
export function validateProject(raw:any):Project{
 if(!raw||![1,2].includes(raw.schemaVersion))throw Error('不支持的项目版本');
 const p=raw.schemaVersion===1?raw:raw.pattern;
 let pattern:Pattern|undefined;
 if(p){
  if(!Number.isInteger(p.width)||!Number.isInteger(p.height)||p.width<1||p.width>128||p.height<1||p.height>128||p.width*p.height>8192||!Array.isArray(p.cells)||p.cells.length!==p.width*p.height||!Array.isArray(p.palette)||p.palette.length<1||p.palette.length>512||!Number.isInteger(p.colorLimit)||p.colorLimit<1||p.colorLimit>512)fail();
  const codes=new Set<string>();
  for(const c of p.palette){if(!c||typeof c.code!=='string'||!c.code.length||c.code.length>40||['__proto__','constructor','prototype'].includes(c.code)||codes.has(c.code)||!/^#[0-9a-f]{6}$/i.test(c.hex))fail();codes.add(c.code)}
  if(p.cells.some((c:unknown)=>c!==null&&(typeof c!=='string'||!codes.has(c))))fail();
  if(Object.keys(stats(p.cells).counts).length>p.colorLimit||p.palette.length>p.colorLimit)fail();
  pattern={width:p.width,height:p.height,cells:p.cells.slice(),palette:p.palette.map((c:any)=>({code:c.code,hex:c.hex})),colorLimit:p.colorLimit,paletteName:typeof p.paletteName==='string'?p.paletteName.slice(0,200):'导入色板'};
  if(p.paletteInfo){const info:any={};for(const key of ['brand','series','version','source','license','note']){if(typeof p.paletteInfo[key]!=='string'||p.paletteInfo[key].length>2000)fail();info[key]=p.paletteInfo[key]}pattern.paletteInfo=info}
  if(p.algorithm!==undefined){if(typeof p.algorithm!=='string'||p.algorithm.length>100)fail();pattern.algorithm=p.algorithm}
  if(p.sampling!==undefined){if(!['mean','dominant'].includes(p.sampling))fail();pattern.sampling=p.sampling}
 }
 const resource=(v:any)=>{if(v===undefined)return undefined;if(typeof v!=='string'||v.length>24_000_000||!/^data:image\/png;base64,[A-Za-z0-9+/]+=*$/.test(v))fail();return v as string};
 const source=resource(raw.source),mask=resource(raw.mask);
 if(!pattern&&!source)fail();if(mask&&!source)fail();
 const points=raw.points??[];if(!Array.isArray(points)||points.length>1000||points.some((p:any)=>!p||![p.x,p.y].every(v=>Number.isFinite(v)&&v>=0&&v<=1536)||![0,1].includes(p.label)))fail();
 const box=raw.box;if(box!==undefined&&(!Array.isArray(box)||box.length!==4||!box.every(v=>Number.isFinite(v)&&v>=0&&v<=1536)||box[2]<=box[0]||box[3]<=box[1]))fail();
 const locked=raw.locked??[];if(!Array.isArray(locked)||locked.some((c:any)=>typeof c!=='string'||!pattern?.palette.some(x=>x.code===c)))fail();
 if(raw.step!==undefined&&(!Number.isInteger(raw.step)||raw.step<1||raw.step>3))fail();
 if(raw.tuning&&(![32,48,64].includes(raw.tuning.width)||![8,12,16,24,32].includes(raw.tuning.colors)))fail();
 return{schemaVersion:2,pattern,source,mask,box,points:points.map((p:any)=>({x:p.x,y:p.y,label:p.label})),locked:[...new Set<string>(locked)],step:pattern&&raw.step!==2?(raw.step??3):1,pitch:raw.pitch===5?5:2.6,selectionMode:raw.selectionMode==='object'?'object':'whole',selectionDirty:!!raw.selectionDirty,...(raw.tuning?{tuning:{width:raw.tuning.width,colors:raw.tuning.colors}}:{})};
}
export function parseProject(text:string){if(text.length>50_000_000)throw Error('项目文件过大');return validateProject(JSON.parse(text))}
