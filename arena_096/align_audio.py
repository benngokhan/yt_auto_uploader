"""Standalone local audio-grounded alignment. No motor or provider imports."""
from pathlib import Path
import hashlib,json,re,unicodedata
from difflib import SequenceMatcher
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from faster_whisper import WhisperModel
from faster_whisper.tokenizer import Tokenizer
from faster_whisper.audio import pad_or_trim
from faster_whisper.transcribe import merge_punctuations
import os
ROOT=Path(os.environ['BOSTON096_BUNDLE']).resolve()

def canonical(s):return ''.join(c for c in unicodedata.normalize('NFKD',s.casefold().replace('ı','i')) if c.isalnum() and not unicodedata.combining(c))
def main():
 target=ROOT/'alignment.json'
 if target.exists():raise SystemExit('Alignment already exists; no implicit overwrite')
 p=json.loads((ROOT/'plan.json').read_text());text=' '.join(p['script_lines']);expected=text.split();source=ROOT/'assets/narration.wav'
 y,sr=sf.read(source,dtype='float32',always_2d=True);y=y.mean(axis=1);duration=len(y)/sr
 if not 40<=duration<=58:raise ValueError('Narration duration needs review; never stretch')
 audio=resample_poly(y,16000,sr).astype('float32');model=WhisperModel('base',device='cpu',compute_type='int8',cpu_threads=4,local_files_only=False)
 segments,info=model.transcribe(audio,language='tr',beam_size=5,condition_on_previous_text=False,word_timestamps=True,initial_prompt=text)
 segments=list(segments);asr=' '.join(s.text.strip() for s in segments);asrwords=[{'word':w.word.strip(),'start':w.start,'end':w.end} for s in segments for w in (s.words or []) if canonical(w.word)]
 score=SequenceMatcher(None,canonical(text),canonical(asr),autojunk=False).ratio()
 (ROOT/'asr_diagnostic.json').write_text(json.dumps({'text':asr,'words':asrwords,'similarity':score},ensure_ascii=False,indent=2))
 print('Full ASR similarity:',round(score,4),'Transcript:',asr,flush=True)
 if score<0.80:raise ValueError('ASR and intended narration differ too much')
 match=SequenceMatcher(None,[canonical(w) for w in expected],[canonical(w['word']) for w in asrwords],autojunk=False)
 anchors={}
 for block in match.get_matching_blocks():
  for k in range(block.size):anchors[block.a+k]=asrwords[block.b+k]
 candidates=[]
 for i in range(1,len(expected)):
  if i-1 in anchors and i in anchors:
   left,right=anchors[i-1]['end'],anchors[i]['start'];cut=(left+right)/2
   if right>=left-.025 and 1<cut<29.7 and 1<duration-cut<29.7:candidates.append((abs(cut-duration/2),-(right-left),i,cut))
 if not candidates:raise ValueError('No measured safe midpoint; inspect audio, do not invent timing')
 _,_,split,cut=min(candidates);cut_sample=round(cut*16000);cut=cut_sample/16000
 tokenizer=Tokenizer(model.hf_tokenizer,model.model.is_multilingual,task='transcribe',language='tr')
 aligned=[]
 for clip,shown,offset in [(audio[:cut_sample],expected[:split],0.0),(audio[cut_sample:],expected[split:],cut)]:
  features=model.feature_extractor(clip);encoded=model.encode(pad_or_trim(features));tokens=tokenizer.encode(' '+' '.join(shown))
  if len(tokens)>400:raise ValueError('Too many forced alignment tokens')
  raw=model.find_alignment(tokenizer,[tokens],encoded,features.shape[-1]-1)[0];merge_punctuations(raw,'\"\'“¿([{-','\"\'.。,，!！?？:：”)]}、')
  raw=[w for w in raw if canonical(str(w.get('word','')))];pos=0
  for word in shown:
   want=canonical(word);acc='';parts=[]
   while pos<len(raw) and len(acc)<len(want):
    item=raw[pos];acc+=canonical(str(item['word']));parts.append(item);pos+=1
    if not want.startswith(acc):raise ValueError('Forced token mismatch')
   if acc!=want or not parts:raise ValueError('Missing forced word')
   aligned.append({'word':word,'start':round(offset+parts[0]['start'],4),'end':round(min(duration,offset+parts[-1]['end']),4)})
  if pos!=len(raw):raise ValueError('Unexpected remaining words')
 if len(aligned)!=len(expected):raise ValueError('Word count mismatch')
 previous=0
 for w in aligned:
  if w['start']<previous-.04 or not 0<=w['start']<=w['end']<=duration+.01:raise ValueError('Invalid acoustic timing')
  previous=w['end']
 groups=[];i=0
 for line in p['script_lines']:
  n=len(line.split());groups.append(aligned[i:i+n]);i+=n
 result={'method':'local Whisper known-text cross-attention on two audio-grounded clips','approximate':True,'audio_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'audio_duration_seconds':duration,'asr_transcript':asr,'asr_similarity':round(score,4),'split_seconds':cut,'split_word_index':split,'words':aligned,'groups':groups}
 target.write_text(json.dumps(result,ensure_ascii=False,indent=2));print('Aligned',len(aligned),'words;',round(duration,3),'s; ASR',round(score,4),'split',round(cut,3),flush=True)
 for i,g in enumerate(groups):print(i,round(g[0]['start'],2),round(g[-1]['end'],2),' '.join(w['word'] for w in g),flush=True)
 print('ASR:',asr,flush=True)
if __name__=='__main__':main()
