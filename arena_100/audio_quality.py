"""Independent, unprompted acoustic verification; no TTS or provider calls.
Original full-ASR is preserved. Never treat forced alignment as content proof.
Segment solely from waveform energy (not expected text or forced word timings).
"""
import hashlib,json,re,unicodedata
from difflib import SequenceMatcher
from pathlib import Path
import numpy as np

DIGITS={'sıfır':0,'bir':1,'iki':2,'üç':3,'dört':4,'beş':5,'altı':6,'yedi':7,'sekiz':8,'dokuz':9,'on':10,'yirmi':20,'otuz':30,'kırk':40,'elli':50,'altmış':60,'yetmiş':70,'seksen':80,'doksan':90}

def spoken_numbers(text):
 # Only normalize digit sequences and well-defined Turkish integer words.
 tokens=re.findall(r'\d+(?:[.,]\d+)?|[^\W\d_]+',text.casefold(),re.UNICODE);out=[];subtotal=0;total=0;active=False
 def flush():
  nonlocal subtotal,total,active
  if active:out.append(str(total+subtotal))
  subtotal=total=0;active=False
 for token in tokens:
  if token=='buçuk' and active:
   out.append(str(total+subtotal)+'.5');subtotal=total=0;active=False
  elif token in DIGITS:subtotal+=DIGITS[token];active=True
  elif token=='yüz':subtotal=max(1,subtotal)*100;active=True
  elif token=='bin':total+=max(1,subtotal)*1000;subtotal=0;active=True
  else:flush();out.append(token.replace(',','.') if re.fullmatch(r'\d+(?:[.,]\d+)?',token) else token)
 flush();return ' '.join(out)

def canonical(text):return ''.join(c for c in unicodedata.normalize('NFKD',spoken_numbers(text).replace('ı','i')) if c.isalnum() and not unicodedata.combining(c))
def similarity(a,b):return SequenceMatcher(None,canonical(a),canonical(b),autojunk=False).ratio()
def numeric_entities(text):return re.findall(r'(?<![\w.])\d+(?:\.\d+)?(?![\w.])',spoken_numbers(text))

def acoustic_windows(audio,sr=16000,target_seconds=11,max_seconds=14,min_seconds=5):
 if sr<=0 or not len(audio):raise ValueError('Empty audio or invalid sample rate')
 if not 0<min_seconds<target_seconds<max_seconds:raise ValueError('Invalid window limits')
 hop=max(1,round(sr*.02));pad=(-len(audio))%hop;x=np.pad(np.asarray(audio,dtype='float32'),(0,pad));rms=np.sqrt(np.mean(x.reshape(-1,hop)**2,axis=1));cuts=[0];n=len(audio)
 while (n-cuts[-1])/sr>max_seconds:
  start=cuts[-1];lo=round((start+min_seconds*sr)/hop);hi=min(len(rms),round((start+max_seconds*sr)/hop));ids=np.arange(lo,hi)
  if not len(ids):raise ValueError('No acoustic split candidate')
  # Prefer sustained quiet (>=160ms), not a single low-energy consonant.
  threshold=min(.012,max(.003,float(np.quantile(rms[ids],.18))))
  quiet=ids[rms[ids]<=threshold];runs=[]
  for idx in quiet:
   if not runs or idx!=runs[-1][-1]+1:runs.append([int(idx)])
   else:runs[-1].append(int(idx))
  midpoints=[run[len(run)//2] for run in runs if len(run)*hop/sr>=.16]
  pool=midpoints if midpoints else ids
  ideal=start+target_seconds*sr;best=int(min(pool,key=lambda i:abs(i*hop-ideal)))
  cut=min(n,best*hop)
  if not start<cut<n:raise ValueError('Invalid acoustic split')
  cuts.append(cut)
 cuts.append(n);return list(zip(cuts[:-1],cuts[1:]))

def assess(expected_lines,clips,original_full=None):
 expected=' '.join(expected_lines);recognized=' '.join(c['text'] for c in clips)
 # Whole transcript score alone can hide a missing sentence or wrong year.
 want=canonical(expected);got=canonical(recognized);matcher=SequenceMatcher(None,want,got,autojunk=False);matched=set()
 for block in matcher.get_matching_blocks():matched.update(range(block.a,block.a+block.size))
 coverage=[];offset=0
 for line in expected_lines:
  n=len(canonical(line));coverage.append(sum(i in matched for i in range(offset,offset+n))/max(1,n));offset+=n
 score=similarity(expected,recognized);numbers_ok=numeric_entities(expected)==numeric_entities(recognized)
 ending_ok=bool(expected_lines) and got.endswith(canonical(expected_lines[-1]))
 passed=score>=.95 and bool(coverage) and min(coverage)>=.85 and numbers_ok and ending_ok
 return {'ending_matches':ending_ok,'state':'audio_verified' if passed else 'audio_needs_review','method':'unprompted waveform-only acoustic segmentation; no expected-text prompt','similarity':score,'threshold':.95,'line_coverage':coverage,'minimum_line_coverage':.85,'numeric_entities_match':numbers_ok,'expected_numeric_entities':numeric_entities(expected),'recognized_numeric_entities':numeric_entities(recognized),'recognized_text':recognized,'clips':clips,'original_full_asr':original_full,'automatic_tts_retry':False,'timings_validated_by_this_check':False,'caveat':'ASR agreement is not proof of pronunciation or historical truth.'}

def verify_file(source,lines,model,original_full=None):
 import soundfile as sf
 from scipy.signal import resample_poly
 source=Path(source);y,sr=sf.read(source,dtype='float32',always_2d=True)
 if y.shape[1]!=1:raise ValueError('Expected untouched mono narration')
 if not 40<=len(y)/sr<=53:raise ValueError('Natural narration must be40–53s; do not stretch')
 audio=resample_poly(y[:,0],16000,sr).astype('float32');clips=[]
 for left,right in acoustic_windows(audio):
  segments,_=model.transcribe(audio[left:right],language='tr',beam_size=5,condition_on_previous_text=False,word_timestamps=False,vad_filter=False,initial_prompt=None)
  text=' '.join(s.text.strip() for s in segments)
  clips.append({'start':left/16000,'end':right/16000,'text':text})
 report=assess(lines,clips,original_full);report.update(audio_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),natural_seconds=len(y)/sr,new_provider_calls=0)
 return report

if __name__=='__main__':
 import argparse
 from faster_whisper import WhisperModel
 p=argparse.ArgumentParser();p.add_argument('--bundle',required=True);p.add_argument('--model',required=True);p.add_argument('--output',required=True);args=p.parse_args();root=Path(args.bundle);dest=Path(args.output)
 if dest.exists():raise SystemExit('No overwrite of prior evidence')
 plan=json.loads((root/'plan.json').read_text());old=json.loads((root/'alignment.json').read_text()) if (root/'alignment.json').exists() else None
 model=WhisperModel(args.model,device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
 report=verify_file(root/'assets/narration.wav',plan['script_lines'],model,old)
 with dest.open('x') as f:json.dump(report,f,ensure_ascii=False,indent=2)
 print(json.dumps({k:report[k] for k in ['state','similarity','line_coverage','numeric_entities_match']},indent=2));raise SystemExit(0 if report['state']=='audio_verified' else 2)
