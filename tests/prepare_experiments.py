"""Three permissive public images and nine original synthetic fixtures; no downloads or private copies."""
import json
from pathlib import Path
from PIL import Image,ImageDraw
root=Path(__file__).resolve().parents[1];out=root/'experiments/generated';out.mkdir(parents=True,exist_ok=True);old=root/'examples/dataset';manifest=[]
def save(name,im,kind,source,license):
 im.thumbnail((192,192));im=im.convert('RGBA');raw=list(im.tobytes());mask=[1 if raw[i+3]>0 else 0 for i in range(0,len(raw),4)];(out/f'{name}.json').write_text(json.dumps({'width':im.width,'height':im.height,'rgba':raw,'mask':mask}));im.save(out/f'{name}.png');manifest.append({'id':name,'kind':kind,'source':source,'license':license,'public':True,'mask':'whole image effective alpha; no model segmentation'})
for file,name,license in [('person.png','astronaut','NASA public domain'),('pet.png','chelsea','CC0, Stefan van der Walt'),('object.png','coffee','CC0, Rachel Michetti')]:save(name,Image.open(old/file),'real photo','scikit-image v0.25.2, attribution in examples/dataset/SOURCES.md',license)
for n in range(9):
 im=Image.new('RGBA',(128,128),(0,0,0,0) if n in [3,4] else 'white');d=ImageDraw.Draw(im)
 if n==0:
  for x in range(128):d.line((x,0,x,127),fill=(x*2,180,255-x,255))
 elif n==1:
  for y in range(0,128,16):
   for x in range(0,128,16):d.rectangle((x,y,x+15,y+15),fill=['#98CCE8','#E8CEC1','#424E63','#F8F4E8'][(x//16+y//16)%4])
 elif n==2:
  d.ellipse((30,10,98,78),fill='#F6CFB8');d.rectangle((20,78,108,126),fill='#8ABFDE');d.ellipse((45,38,50,44),fill='#29374B');d.ellipse((78,38,83,44),fill='#29374B')
 elif n==3:d.ellipse((16,16,112,112),fill=(235,80,60,160));d.rectangle((48,4,80,124),fill='#EDE5CE')
 elif n==4:
  for i in range(4,124,8):d.line((4,i,124,127-i),fill='#263F68',width=1)
 elif n==5:
  for x in range(128):d.line((x,0,x,127),fill=(x*2,x*2,x*2,255))
 elif n==6:
  d.rectangle((16,20,100,110),fill='#668953');d.rectangle((40,40,88,70),fill='#D3CB88');d.ellipse((89,40,124,85),outline='#668953',width=8)
 elif n==7:
  for y in range(128):d.line((0,y,127,y),fill=(210+y//4,190+y//4,170+y//4,255))
 else:
  for i,c in enumerate(['#EA6955','#62AB70','#639CD9','#C59ED5']):d.rectangle((i*32,0,i*32+31,127),fill=c)
 save('synthetic-'+str(n+1),im,'original synthetic','tests/prepare_experiments.py','Original project fixture, MIT')
(out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8');print(len(manifest),'inputs prepared')
