// Björn Ottosson's Oklab, https://bottosson.github.io/posts/oklab/ .
// Input channels are gamma encoded sRGB in [0,255]; output uses L approximately [0,1].
export function hexRgb(h:string):number[]{return [1,3,5].map(i=>parseInt(h.slice(i,i+2),16))}
export function srgbToOklab(rgb:number[]):number[]{
 const [r,g,b]=rgb.map(v=>{const c=v/255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4});
 const l=Math.cbrt(.4122214708*r+.5363325363*g+.0514459929*b);
 const m=Math.cbrt(.2119034982*r+.6806995451*g+.1073969566*b);
 const s=Math.cbrt(.0883024619*r+.2817188376*g+.6299787005*b);
 return [.2104542553*l+.793617785*m-.0040720468*s,1.9779984951*l-2.428592205*m+.4505937099*s,.0259040371*l+.7827717662*m-.808675766*s];
}
export function distanceSquared(a:number[],b:number[]):number{return (a[0]-b[0])**2+(a[1]-b[1])**2+(a[2]-b[2])**2}
// Explicit product preference for preserving hue at a cost in lightness/chroma fit.
// Delta-H squared is continuous at neutral colors; no angle or special blue rule.
export function hueDistanceSquared(a:number[],b:number[]):number{
 const dl=(a[0]-b[0])**2,dc=(Math.hypot(a[1],a[2])-Math.hypot(b[1],b[2]))**2;
 const dh=Math.max(0,(a[1]-b[1])**2+(a[2]-b[2])**2-dc);
 return dl+dc+4*dh;
}
