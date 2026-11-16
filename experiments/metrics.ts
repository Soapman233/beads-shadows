// Independent evaluation implementation from Sharma/Wu/Dalal (2005), equations 2–22.
// References: https://hajim.rochester.edu/ece/sites/gsharma/ciede2000/
// Not the generation optimizer; sRGB D65 -> XYZ -> CIELAB, kL=kC=kH=1.
export function srgbLab(rgb:number[]):number[]{
 const [r,g,b]=rgb.map(v=>{const s=v/255;return s<=.04045?s/12.92:((s+.055)/1.055)**2.4});
 const xyz=[(.4124564*r+.3575761*g+.1804375*b)/.95047,.2126729*r+.7151522*g+.072175*b,(.0193339*r+.119192*g+.9503041*b)/1.08883];
 const [x,y,z]=xyz.map(t=>t>216/24389?Math.cbrt(t):(24389/27*t+16)/116);return[116*y-16,500*(x-y),200*(y-z)];
}
const rad=(d:number)=>d*Math.PI/180,deg=(r:number)=>r*180/Math.PI;
export function deltaE00(a:number[],b:number[]):number{
 const [L1,a1,b1]=a,[L2,a2,b2]=b,C1=Math.hypot(a1,b1),C2=Math.hypot(a2,b2),C=(C1+C2)/2,G=.5*(1-Math.sqrt(C**7/(C**7+25**7)));
 const ap1=(1+G)*a1,ap2=(1+G)*a2,cp1=Math.hypot(ap1,b1),cp2=Math.hypot(ap2,b2);
 const hue=(x:number,y:number)=>x===0&&y===0?0:(deg(Math.atan2(y,x))+360)%360,h1=hue(ap1,b1),h2=hue(ap2,b2),dl=L2-L1,dc=cp2-cp1;
 let dh=h2-h1;if(cp1*cp2===0)dh=0;else if(dh>180)dh-=360;else if(dh< -180)dh+=360;
 const dH=2*Math.sqrt(cp1*cp2)*Math.sin(rad(dh/2)),lm=(L1+L2)/2,cm=(cp1+cp2)/2;
 let hm:number;if(cp1*cp2===0)hm=h1+h2;else if(Math.abs(h1-h2)<=180)hm=(h1+h2)/2;else hm=(h1+h2+(h1+h2<360?360:-360))/2;
 const T=1-.17*Math.cos(rad(hm-30))+.24*Math.cos(rad(2*hm))+.32*Math.cos(rad(3*hm+6))-.20*Math.cos(rad(4*hm-63));
 const sl=1+.015*(lm-50)**2/Math.sqrt(20+(lm-50)**2),sc=1+.045*cm,sh=1+.015*cm*T,rc=2*Math.sqrt(cm**7/(cm**7+25**7)),rt=-Math.sin(rad(60*Math.exp(-(((hm-275)/25)**2))))*rc;
 const l=dl/sl,c=dc/sc,h=dH/sh;return Math.sqrt(Math.max(0,l*l+c*c+h*h+rt*c*h));
}
export function summarize(values:number[]){const sorted=values.slice().sort((a,b)=>a-b);return{mean:values.reduce((s,v)=>s+v,0)/values.length,p95:sorted[Math.max(0,Math.ceil(.95*sorted.length)-1)],count:values.length}}

