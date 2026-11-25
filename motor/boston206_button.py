"""Locally drawn premium follow-button artwork and mouse animation; no external assets."""
from PIL import Image,ImageDraw,ImageFilter
import math

def follow(self,pressed=False):
 # Typography-led compact button: no icon, no nested frames or decorative rim.
 W,H=1080,1920;out=Image.new('RGBA',(W,H));cx,cy=540,1115+(2 if pressed else 0)
 bw,bh=(246,68) if pressed else (250,70)
 x0,y0=cx-bw//2,cy-bh//2;x1,y1=cx+bw//2,cy+bh//2
 shadow=Image.new('RGBA',(W,H));sd=ImageDraw.Draw(shadow)
 sd.rounded_rectangle((x0,y0+5,x1,y1+5),radius=16,fill=(0,0,0,105))
 out=Image.alpha_composite(out,shadow.filter(ImageFilter.GaussianBlur(5)));d=ImageDraw.Draw(out)
 d.rounded_rectangle((x0,y0,x1,y1),radius=16,fill=(34,34,31,250) if pressed else (27,29,28,247),outline=(170,147,104,210),width=1)
 f=self.button_font
 d.text((cx,cy+1),'Takip Et',font=f,fill=(249,243,230,255),anchor='mm')
 return out

def animated_button(self,frame,t):
 if not self.button_start<=t<self.button_end:return frame
 pressed=0<=t-self.click<.17;button=self.buttons[pressed];entry=min(1,max(0,(t-self.button_start)/.28));entry=entry*entry*(3-2*entry)
 alpha=min(entry,max(0,(self.button_end-t)/.24));dy=round(15*(1-entry))
 if alpha<1:
  button=button.copy();button.putalpha(button.getchannel('A').point(lambda v:round(v*alpha)))
 frame.alpha_composite(button,(0,dy))
 # Small, elegant white mouse pointer follows one eased arc, clicks once, then fades.
 begin=self.click-.65;finish=self.click-.08
 if begin<=t<self.click+.58:
  p=min(1,max(0,(t-begin)/(finish-begin)));p=p*p*(3-2*p)
  mx=round(785*(1-p)+627*p);my=round(1250*(1-p)+1119*p-18*math.sin(math.pi*p))
  pa=min(1,max(0,(t-begin)/.12),max(0,(self.click+.58-t)/.20))
  pointer=Image.new('RGBA',(42,57));d=ImageDraw.Draw(pointer)
  poly=[(4,3),(5,42),(15,32),(23,49),(31,45),(23,29),(37,27)]
  d.polygon([(x+2,y+3) for x,y in poly],fill=(0,0,0,100));d.polygon(poly,fill=(252,249,241,255),outline=(12,17,18,255),width=2)
  pointer.putalpha(pointer.getchannel('A').point(lambda v:round(v*pa)));frame.alpha_composite(pointer,(mx,my+(2 if pressed else 0)))
 return frame
