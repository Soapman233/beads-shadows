"""Render three public diagnostic sheets and summarize measured experiment results."""
import json
from pathlib import Path
from PIL import Image,ImageDraw
root=Path(__file__).resolve().parents[1];data=root/'experiments/generated';result=json.loads((data/'results.json').read_text(encoding='utf-8'));rows=result['rows'];bg=(237,240,234)
for name in ['astronaut','chelsea','synthetic-3']:
 d=json.loads((data/f'{name}-comparison.json').read_text(encoding='utf-8'));sheet=Image.new('RGB',(1440,320),bg);draw=ImageDraw.Draw(sheet)
 src=Image.open(data/f'{name}.png').crop(d['grid']['crop']);images=[('source',src)]
 raw=Image.new('RGB',(d['grid']['width'],d['grid']['height']),bg);raw.putdata([tuple(round(c) for c in v) if v else bg for v in d['grid']['values']]);images.append(('grid mean',raw))
 for key in ['full','rgb','hue4','swap']:
  p=d['runs'][key]['pattern'];im=Image.new('RGB',(p['width'],p['height']),bg);pal={c['code']:tuple(bytes.fromhex(c['hex'][1:])) for c in p['palette']};im.putdata([pal.get(c,bg) for c in p['cells']]);images.append((key,im))
 for col,(label,im) in enumerate(images):
  draw.text((col*240+10,8),label,fill='black');scale=min(220/im.width,270/im.height);im=im.resize((round(im.width*scale),round(im.height*scale)),Image.Resampling.NEAREST if im.width<=128 else Image.Resampling.LANCZOS);sheet.paste(im,(col*240+10,35),im if im.mode=='RGBA' else None)
 sheet.save(data/f'{name}-comparison.png')
lines=['# P2 可控实验记录','','日期：2026-11-16。输入12份：3张真实照片（NASA public domain、CC0）和9份原创合成边界/平涂/渐变样例；合成样例不冒充真实照片。未计算文件哈希。','','## 方法和来源','','固定每份规范化source、有效alpha mask、crop、64格宽、K16和MARD社区220色版本；不重分割。A组同mean代表色比较RGB频次、普通Oklab、色相权重4与两步单色交换候选。全色库仅诊断。所有DE00采用独立sRGB→线性RGB→XYZ D65→CIELAB→CIEDE2000，参数kL=kC=kH=1。均值为有效格等权，P95为有效格颜色误差分位数，不是少量运行时间的P95。','','公式及已知对：[Sharma/Wu/Dalal作者页面](https://hajim.rochester.edu/ece/sites/gsharma/ciede2000/)、[2005论文](https://hajim.rochester.edu/ece/sites/gsharma/ciede2000/ciede2000noteCRNA.pdf)、[作者测试数据](https://hajim.rochester.edu/ece/sites/gsharma/ciede2000/dataNprograms/ciede2000testdata.txt)。独立实现没有复制作者MATLAB代码；8个已知对覆盖蓝色交叉项符号、零色度、色相跨界/近180度，容差0.0001；黑白sRGB转换一并通过。','','真实图来源沿用mvp/samples/SOURCES.md：scikit-image v0.25.2 astronaut NASA、公有领域；chelsea CC0 Stefan van der Walt；coffee CC0 Rachel Michetti。原图既有资源仅读取，不重新下载。输入清单在experiments/generated/manifest.json。所有实验生成数据和图在gitignored目录，用户角色图未复制或上传。','','## A组：同取样配色','','|样例|RGB均值|Oklab均值|hue4均值|swap均值|hue4 P95|swap P95|豆数|hue4色数→swap|','|---|---:|---:|---:|---:|---:|---:|---:|---|']
for row in rows:
 r=row['runs'];lines.append(f"|{row['id']}|{r['rgb']['mean']:.4f}|{r['oklab']['mean']:.4f}|{r['hue4']['mean']:.4f}|{r['swap']['mean']:.4f}|{r['hue4']['p95']:.4f}|{r['swap']['p95']:.4f}|{r['hue4']['beans']}|{r['hue4']['colors']}→{r['swap']['colors']}|")
lines+=['','每图完整hue目标、颜色数、豆数、8邻域孤立格和单次生成耗时在results.json。目标函数与DE00不同，不把hue下降当成独立指标必然改善。12图中swap仅astronaut小幅改善（DE00约6.5723→6.5591），其余11图相同；不足以更换默认，保留hue4默认，将swap保留研究候选。不是全局最优。','','## B组：相同原像素参考的取样对照','','固定匹配hue4/K16，mean与dominant都对照同一前景原图像素。将原图像素中心映射到输出格；仅统计mask有效、alpha>0且对应非空格的像素，以alpha/255为权重。边界和非边界本轮未另列，未宣称完成所有采样质量验证；格均值与源像素加权均值不可混用。P95同样按累计alpha权重定义。','','|样例|mean像素DE00均值|dominant像素DE00均值|mean P95|dominant P95|8邻域孤立格mean→dominant|','|---|---:|---:|---:|---:|---|']
for row in rows:
 if 'sampling' not in row:continue
 a=row['sampling']['mean'];b=row['sampling']['dominant'];lines.append(f"|{row['id']}|{a['pixelWeightedMean']:.4f}|{b['pixelWeightedMean']:.4f}|{a['pixelWeightedP95']:.4f}|{b['pixelWeightedP95']:.4f}|{a['isolated8']}→{b['isolated8']}|")
lines+=['','主色取样有保留大色块与损失细线的取舍；孤立格仅代理指标，不是越少必然越好。未自动删格。','','## 验证范围和复现','','命令（仓库根目录）：旧mvp虚拟环境python运行tests/prepare_experiments.py；tsx experiments/run.ts；python tests/render_experiments.py。指标测试tsx --test tests/metrics.test.ts。复用现有环境，不下载模型。','','本轮实验是小样本探索，非全面质量结论。三张对照图来自合法公开素材，需实际看图；不以指标单独证明人眼满意。尚未完成真实新手实验、轻薄本实机测试、实体色差。C组敏感性、3次预热性能与Worker UI响应由主agent继续补充；本记录不冒称已完成。']
(root/'docs/experiments.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(root/'docs/experiments.md')
