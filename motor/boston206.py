"""Versioned Boston206 renderer. Imported, reviewed assets only; no provider calls."""
from pathlib import Path
import hashlib,json,math,subprocess,sys,wave
import numpy as np
from PIL import Image,ImageDraw,ImageFont,ImageOps,ImageEnhance,ImageFilter
import imageio_ffmpeg
try:
 from .boston206_button import follow as premium_follow, animated_button
except ImportError:
 from boston206_button import follow as premium_follow, animated_button
TEMPLATE_VERSION='boston-v1-206.1'
FONT_DIR=Path(__file__).resolve().parent/'assets'
W,H,FPS,DURATION,SR=1080,1920,30,53.0,24000

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2))
def read(p):return json.loads(Path(p).read_text())
def font(size,bold=False):return ImageFont.truetype(str(FONT_DIR/('Poppins-SemiBold.ttf' if bold else 'Poppins-Regular.ttf')),size)
def ease(v):v=min(1,max(0,v));return v*v*(3-2*v)

def safe_asset(folder,name):
 import re
 if not isinstance(name,str) or not re.fullmatch(r'scene0[1-8]\.(png|jpg|jpeg)',name):raise ValueError('Unsafe scene filename')
 p=folder/name
 if p.is_symlink() or p.resolve().parent!=folder.resolve():raise ValueError('Scene path escapes bundle')
 return p

def validate_edges(edges):
 if not isinstance(edges,list) or len(edges)!=9:raise ValueError('Exactly eight scene intervals required')
 edges=[float(x) for x in edges]
 if edges[0]!=0 or edges[-1]!=53 or not all(math.isfinite(x) for x in edges) or not all(a<b for a,b in zip(edges,edges[1:])):raise ValueError('Invalid scene intervals')
 return edges

def verify_template_lock():
 lock=read(Path(__file__).with_name('boston206_lock.json'))
 if lock['version']!=TEMPLATE_VERSION:raise ValueError('Template version mismatch')
 for name,expected in lock['sha256'].items():
  p=Path(__file__).parent/name
  if sha(p)!=expected:raise ValueError('Locked template file changed: '+name)
 return lock

class Story:
 def __init__(self,bundle):
  self.root=Path(bundle).resolve();self.assets=self.root/'assets'
  if not self.root.is_dir():raise ValueError('Bundle directory missing')
  verify_template_lock()
  self.plan=read(self.root/'plan.json');self.edges=validate_edges(self.plan.get('timeline_edges'));self.a=read(self.root/'alignment.json');self.reviews=read(self.root/'asset_review.json')
  source=self.assets/'narration.wav'
  if sha(source)!=self.a['audio_sha256'] or self.a['asr_similarity']<.95:raise ValueError('Audio not verified')
  if self.plan['voice_id']!='voice-00' or self.plan['motor_integration'] is not False:raise ValueError('Independent selected voice required')
  if [w['word'] for w in self.a['words']]!=' '.join(self.plan['script_lines']).split():raise ValueError('Narration/caption mismatch')
  if [w for g in self.a['groups'] for w in g]!=self.a['words']:raise ValueError('Caption grouping differs from aligned words')
  previous=0.0
  for w in self.a['words']:
   if not 0<=w['start']<=w['end']<=self.a['audio_duration_seconds'] or w['start']<previous-.04:raise ValueError('Invalid acoustic word timing')
   previous=w['end']
  if not 40<=self.a['audio_duration_seconds']<=DURATION:raise ValueError('Do not stretch, cut or replace narration')
  if len(self.reviews)!=8:raise ValueError('8 image reviews required')
  if not self.plan['script_lines'] or self.plan['script_lines'][-1]!='Merakını besle, Bilgi Dozu’nu takip et!':raise ValueError('Exact closing CTA required')
  hashes=[];pixels=[];self.plates=[]
  for i,row in enumerate(self.reviews,1):
   p=safe_asset(self.assets,row['file'])
   if row['scene']!=i or row['sha256']!=sha(p) or not row['approved_for_illustrative_draft']:raise ValueError('Unreviewed asset')
   with Image.open(p) as im:
    pixels.append(hashlib.sha256(im.convert('RGB').tobytes()).hexdigest());
    if row.get('pixel_sha256')!=pixels[-1]:raise ValueError('Decoded pixel review changed')
    rgb=im.convert('RGB');self.plates.append(self.plate(rgb))
   hashes.append(sha(p))
  if len(set(hashes))!=8 or len(set(pixels))!=8:raise ValueError('Repeated image forbidden')
  self.groups=self.a['groups'];self.types=[self.layout(self.display_group(i,g),i==0) for i,g in enumerate(self.groups)]
  slogan=self.groups[-1];self.click=next(w['start'] for w in slogan if w['word']=='takip');self.button_start=self.click-.95;self.button_end=52.0
  self.button_font=font(44,True);self.static=self.static_overlay();self.buttons={False:self.follow(False),True:self.follow(True)}
  self.prepare_mix()
  save(self.root/'editing.json',{'duration':DURATION,'fps':FPS,'canvas':[W,H],'scenes':[{'image':self.reviews[i]['file'],'start':self.edges[i],'end':self.edges[i+1]} for i in range(8)],'caption_method':self.a['method'],'caption_asr_similarity':self.a['asr_similarity'],'slogan_start':slogan[0]['start'],'button_window':[self.button_start,self.button_end],'button_click':self.click,'template_version':TEMPLATE_VERSION,'publication':False})
 def plate(self,image):
  image=ImageOps.fit(image,(1210,2152),method=Image.Resampling.LANCZOS)
  image=ImageEnhance.Color(image).enhance(.90);image=ImageEnhance.Contrast(image).enhance(1.025)
  a=np.array(image,dtype=np.float32);height,width=a.shape[:2]
  y=np.linspace(0,1,height)[:,None];x=np.linspace(-1,1,width)[None,:]
  bottom=np.clip((y-.57)/.43,0,1)**1.35*.78
  top=np.clip((.18-y)/.18,0,1)**1.5*.30
  radial=(x*x+(2*y-1)**2)*.035
  mask=np.clip(np.maximum(top,bottom)+radial,0,.86)[...,None]
  dark=np.array([12,13,15],dtype=np.float32)
  a=a*(1-mask)+dark*mask
  return Image.fromarray(np.clip(a,0,255).astype('uint8'),'RGB')
 def display_group(self,i,g):
  return g
 def layout(self,group,large=False):
  f=font(66 if large else 50,True if large else False);lh=92 if large else 72;x0=102;y0=590 if large else 1210;limit=820
  space=f.getlength(' ');x=x0;y=y0;items=[]
  for w in group:
   tw=f.getlength(w['word'])
   if x>x0 and x+tw>x0+limit:x=x0;y+=lh
   if tw>limit or y+lh>1499:raise ValueError('Caption cannot fit without redesign')
   glyph=Image.new('RGBA',(math.ceil(tw)+18,lh+16),(0,0,0,0));draw=ImageDraw.Draw(glyph)
   draw.text((5,0),w['word'],font=f,fill=(197,167,116,255) if w['word'].lower().strip('.,;:!?') in set(self.plan.get('highlight_words',[])) else (255,253,247,255),stroke_width=1,stroke_fill=(0,0,0,150))
   items.append((w,round(x)-5,y,glyph));x+=tw+space
  return {'items':items,'rule':(73,y0+13,76,y+lh-10)}
 def static_overlay(self):
  out=Image.new('RGBA',(W,H),(0,0,0,0));d=ImageDraw.Draw(out);f=font(20,True);x=82
  for letter in 'BİLGİ DOZU':
   d.text((x,103),letter,font=f,fill=(246,239,222,215));x+=round(f.getlength(letter))+4
  f=font(19)
  for y,t in [(1510,self.plan.get('visual_disclosure','Yapay zekâ ile temsili canlandırma')),(1541,'Kaynak: '+self.plan['source']['label'])]:
   if d.textbbox((0,0),t,font=f)[2]>906:raise ValueError('Source/disclosure label too long')
   d.text((87,y),t,font=f,fill=(235,228,212,185),stroke_width=1,stroke_fill=(0,0,0,120))
  return out
 follow=premium_follow
 def background(self,i,t):
  p=ease((t-self.edges[i])/(self.edges[i+1]-self.edges[i]));plate=self.plates[i]
  zoom=1.01+.065*p if i%2==0 else 1.075-.060*p
  cw,ch=plate.width/zoom,plate.height/zoom
  cx=.5+(.009*(p-.5) if i%3==1 else 0);cy=.5+(.012*(p-.5) if i%3==2 else 0)
  x0=min(max(0,plate.width*cx-cw/2),plate.width-cw);y0=min(max(0,plate.height*cy-ch/2),plate.height-ch)
  return plate.resize((W,H),Image.Resampling.BILINEAR,box=(x0,y0,x0+cw,y0+ch))
 def frame(self,t):
  i=min(7,next((j for j in range(8) if self.edges[j]<=t<self.edges[j+1]),7));bg=self.background(i,t)
  if i and t-self.edges[i]<.36:
   before=self.background(i-1,self.edges[i]);bg=Image.blend(before,bg,ease((t-self.edges[i])/.36))
  frame=Image.alpha_composite(bg.convert('RGBA'),self.static)
  gi=None
  for j,g in enumerate(self.groups):
   start=0 if j==0 else g[0]['start'];end=self.groups[j+1][0]['start']-.02 if j+1<len(self.groups) else DURATION
   if start<=t<end:gi=j;break
  if gi is not None:
   layout=self.types[gi];ImageDraw.Draw(frame).rectangle(layout['rule'],fill=(229,215,183,225))
   for w,x,y,glyph in layout['items']:
    alpha=min(1,max(0,(t-w['start']+.035)/.13))
    if alpha<=0:continue
    if alpha<1:
     glyph=glyph.copy();glyph.putalpha(glyph.getchannel('A').point(lambda v:round(v*alpha)))
    frame.alpha_composite(glyph,(x,y))
  frame=animated_button(self,frame,t)
  fade=min(1,max(0,(DURATION-t)/.75))
  if fade<1:frame=Image.blend(Image.new('RGBA',(W,H),(0,0,0,255)),frame,fade)
  return frame.convert('RGB')
 def prepare_mix(self):
  output=self.root/'audio_mix.wav'
  if output.exists():
   m=read(self.root/'mix_manifest.json')
   if m['original_voice_sha256']!=sha(self.assets/'narration.wav') or m['mix_sha256']!=sha(output):raise ValueError('Existing mix changed')
   return
  with wave.open(str(self.assets/'narration.wav')) as f:
   if (f.getnchannels(),f.getsampwidth(),f.getframerate())!=(1,2,SR):raise ValueError('Wrong voice format')
   raw=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').astype(float)
  count=round(DURATION*SR);narration=np.zeros(count);narration[:len(raw)]=raw
  time=np.arange(count)/SR
  # Original, locally synthesized, low-level instrumental atmosphere. No recording sampled.
  bed=np.zeros(count)
  chords=[(73.416,146.832,174.614,220.0),(58.270,146.832,174.614,233.082),(87.307,130.813,174.614,220.0),(65.406,146.832,195.998,261.626)]
  for j,chord in enumerate(chords):
   start=j*DURATION/4;end=(j+1)*DURATION/4;local=time-start
   envelope=np.clip(local/2,0,1)*np.clip((end+2-time)/2,0,1)
   for k,hz in enumerate(chord):bed+=np.sin(2*np.pi*hz*time+0.23*k)*envelope/(4*(1+k*.18))
  bed/=max(1e-9,float(np.sqrt(np.mean(bed*bed))));bed*=32767*10**(-38/20)
  # Duck the bed ONLY; never compress, speed up, pitch-shift or filter the voice.
  win=1200;energy=np.sqrt(np.mean(np.pad(narration,(0,(-count)%win)).reshape(-1,win)**2,axis=1))/32767
  env=np.interp(np.arange(count)/win,np.arange(len(energy)),energy);duck=1-.60*np.clip(env/.045,0,1)
  fade=np.clip(time/.8,0,1)*np.clip((DURATION-time)/1.8,0,1);bed*=duck*fade
  effect=np.zeros(count);at=round(self.click*SR);et=np.arange(round(.38*SR))/SR
  ding=(np.sin(2*np.pi*1046.5*et)+.28*np.sin(2*np.pi*1569.75*et))*np.exp(-et*15)*np.clip(et/.005,0,1)
  ding*=32767*10**(-28/20)/max(1,float(np.max(np.abs(ding))));effect[at:at+len(ding)]+=ding
  mix=narration+bed+effect
  if np.max(abs(mix))>=32767:raise ValueError('Clipping risk; stop rather than alter narration')
  with wave.open(str(output),'wb') as w:w.setparams((1,2,SR,0,'NONE','not compressed'));w.writeframes(np.rint(mix).astype('<i2').tobytes())
  save(self.root/'mix_manifest.json',{'original_voice_sha256':sha(self.assets/'narration.wav'),'mix_sha256':sha(output),'natural_voice_seconds':len(raw)/SR,'output_seconds':DURATION,'voice_speed_factor':1.0,'voice_amplitude_processing':False,'narration_sample_positions_unchanged':True,'tail_padding_seconds':DURATION-len(raw)/SR,'music':'Original locally synthesized quiet instrumental pad; voice unchanged','sfx':'Original locally synthesized subdued bell at spoken takip','sfx_start':self.click,'peak_pcm16':float(np.max(abs(mix))),'publication':False,'template_version':TEMPLATE_VERSION})

def stills(story):
 folder=story.root/'layout_checks';folder.mkdir(exist_ok=True);times=[2.7,7.5,13.0,20.6,26.2,32.1,39.7,46.1,49.3,51.2];sheet=Image.new('RGB',(270*5,480*2))
 for i,t in enumerate(times):
  frame=story.frame(t);frame.save(folder/f'{i+1:02}_{t:.2f}.jpg',quality=92);sheet.paste(frame.resize((270,480)),(i%5*270,i//5*480))
 sheet.save(folder/'overview.jpg',quality=94);print('10 layout stills saved; no video encoding.',flush=True)
def render(story):
 out=story.root/'video.mp4'
 verify_template_lock()
 if out.exists():raise ValueError('Final video exists; no implicit overwrite')
 journal=story.root/'render_journal.json'
 with journal.open('x') as f:json.dump({'state':'reserved_before_single_final_render','template_version':TEMPLATE_VERSION,'publication':False},f)
 cmd=[imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','-','-i',str(story.root/'audio_mix.wav'),'-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','veryfast','-crf','20','-maxrate','5500k','-bufsize','11000k','-threads','4','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart','-n',str(out)]
 with (story.root/'encoder.log').open('wb') as log:
  proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=log)
  try:
   for n in range(round(FPS*DURATION)):
    proc.stdin.write(story.frame(n/FPS).tobytes())
    if n%300==0:print('Independent final frame',n,'/',round(FPS*DURATION),flush=True)
   proc.stdin.close();status=proc.wait()
  except BaseException:
   proc.kill();proc.wait();raise
 if status:raise RuntimeError('Encoder failed; do not automatically rerender')
 save(journal,{'state':'completed','mp4_sha256':sha(out),'bytes':out.stat().st_size,'template_version':TEMPLATE_VERSION,'publication':False});print('Final independent video completed:',out.name,flush=True)