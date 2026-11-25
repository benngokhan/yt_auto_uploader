"""Deterministic two-line Boston206 cover. No model calls; no silent fallback."""
from pathlib import Path
import json,unicodedata
import numpy as np
from PIL import Image,ImageDraw,ImageFont,ImageOps,ImageEnhance
ASSETS=Path(__file__).resolve().parent/'assets'
GOLD='#c5a774';WHITE='#f6f1e6'
def upper(s):return unicodedata.normalize('NFC',str(s).translate(str.maketrans({'i':'İ','ı':'I'})).upper())
def font(n,b=False):return ImageFont.truetype(str(ASSETS/('Poppins-SemiBold.ttf' if b else 'Poppins-Regular.ttf')),n)
def layout_title(lines):
 if not isinstance(lines,list) or len(lines)!=2 or any(not isinstance(x,str) or not x.strip() or '\n' in x for x in lines):raise ValueError('Cover requires exactly two nonempty title lines')
 lines=[upper(x.strip()) for x in lines]
 n=192
 while n>=110:
  f=ImageFont.truetype(str(ASSETS/'Anton-Regular.ttf'),n)
  widths=[f.getlength(t) for t in lines]
  if max(widths)<=916:break
  n-=1
 if n<110:raise ValueError('Cover title too long; rewrite, do not shrink below readable size')
 if min(widths)/max(widths)<.66:raise ValueError('Cover line widths unbalanced; rewrite or review title')
 b0,b1=[f.getbbox(t,anchor='ls') for t in lines]
 pitch=max(207,b0[3]-b1[1]+12+4)
 bases=[476,476+pitch]
 if bases[0]+b0[1]<265 or bases[1]+b1[3]>875:raise ValueError('Cover accents exceed safe title region')
 return {'lines':lines,'font_size':n,'baselines':bases,'widths':widths,'outline_px':2,'min_accent_gap_px':bases[1]+b1[1]-bases[0]-b0[3]-4}
def render_cover(source,dest,lines,category='',subtitle='',disclosure='Yapay zekâ ile temsili canlandırma'):
 try:from .boston206 import verify_template_lock
 except ImportError:from boston206 import verify_template_lock
 verify_template_lock()
 target=Path(dest)
 if target.exists():raise FileExistsError('Cover exists; no implicit overwrite')
 layout=layout_title(lines);im=ImageOps.fit(Image.open(source).convert('RGB'),(1080,1920),centering=(.59,.5));im=ImageEnhance.Color(im).enhance(.76)
 a=np.array(im).astype(float);y=np.linspace(0,1,1920)[:,None];shade=.10+.76*np.maximum(np.clip((.46-y)/.46,0,1)**.6,np.clip((y-.65)/.35,0,1));a=a*(1-shade[:,:,None])+np.array([12,17,17])*shade[:,:,None];im=Image.fromarray(a.astype('uint8'));d=ImageDraw.Draw(im)
 d.text((80,106),'BİLGİ DOZU',font=font(31,True),fill=WHITE,anchor='lt');d.line((80,175,998,175),fill='#79705d',width=1)
 if font(23).getlength(category)>916:raise ValueError('Cover category too long')
 d.text((80,224),category,font=font(23),fill=GOLD,anchor='lt')
 f=ImageFont.truetype(str(ASSETS/'Anton-Regular.ttf'),layout['font_size'])
 for i,(t,b) in enumerate(zip(layout['lines'],layout['baselines'])):d.text((77,b),t,font=f,fill=WHITE if i==0 else GOLD,stroke_width=2,stroke_fill='#0d1313',anchor='ls')
 rule_y=max(750,layout['baselines'][-1]+f.getbbox(layout['lines'][-1],anchor='ls')[3]+55)
 d.line((83,rule_y,294,rule_y),fill=GOLD,width=6)
 words=str(subtitle).split();rows=[];cur='';ff=font(33,True)
 for word in words:
  if ff.getlength(word)>850:raise ValueError('Cover footer word too long')
  trial=(cur+' '+word).strip()
  if ff.getlength(trial)>850:rows.append(cur);cur=word
  else:cur=trial
 if cur:rows.append(cur)
 if '\n' in str(subtitle):rows=str(subtitle).splitlines()
 if any(ff.getlength(t)>850 for t in rows):raise ValueError('Cover footer line too wide')
 if len(rows)>2:raise ValueError('Cover footer too long; rewrite instead of truncation')
 if rows:
  d.line((83,1544,84,1698),fill=GOLD,width=4)
  for i,t in enumerate(rows):d.text((110,1560+55*i),t,font=ff,fill=WHITE,anchor='lt')
 if font(20).getlength(disclosure)>916:raise ValueError('Cover disclosure too long')
 d.text((540,1806),disclosure,font=font(20),fill='#bcb6a7',anchor='mt')
 target.parent.mkdir(parents=True,exist_ok=True);im.save(target,quality=94,optimize=True)
 layout['subtitle_lines']=rows
 target.with_suffix('.layout.json').write_text(json.dumps(layout,ensure_ascii=False,indent=2),encoding='utf-8')
 return target
