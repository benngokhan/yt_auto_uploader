"""Fail-closed provider transport. Atomic reservations, safe typed receipts, no retries.
Never persist URLs, headers, provider messages, request bodies or credentials.
HTTP success alone does not imply visual acceptance.
"""
from pathlib import Path
import hashlib,json,os,urllib.request,urllib.error,socket

class Stop(RuntimeError):pass
class ProviderFailure(Stop):
 def __init__(self,kind,category,status=None):
  self.kind=kind;self.category=category;self.http_status=status
  super().__init__(f'{kind}: {category}'+(f' (HTTP {status})' if status else '')+'; no automatic retry')
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**kw):return None

def atomic_json(path,obj):
 p=Path(path);temp=p.with_suffix(p.suffix+'.tmp');raw=json.dumps(obj,ensure_ascii=False,indent=2)
 with temp.open('x',encoding='utf-8') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 os.replace(temp,p)

def http_category(code):
 if code==429:return 'rate_limited'
 if code in (401,403):return 'access_denied'
 if code==404:return 'endpoint_or_model_not_found'
 if 500<=code<=599:return 'provider_server_error'
 if 300<=code<=399:return 'redirect_refused'
 return 'request_rejected'

class Budget:
 def __init__(self,folder,limits=None,opener=None):
  self.root=Path(folder);self.root.mkdir(exist_ok=False)
  self.limits=dict(limits or {'tts':1,'images':8,'review':1})
  if set(self.limits)!={'tts','images','review'} or any(type(v)is not int or v<0 for v in self.limits.values()):raise ValueError('Invalid call limits')
  self.count=dict.fromkeys(self.limits,0)
  self.opener=opener or urllib.request.build_opener(NoRedirect)
 def reserve(self,kind,body):
  if kind not in self.limits or self.count[kind]>=self.limits[kind]:raise Stop('Budget exhausted; no retry')
  i=self.count[kind]+1;p=self.root/f'{kind}_{i}.json'
  record={'state':'reserved_before_post','kind':kind,'attempt':i,'request_sha256':hashlib.sha256(body).hexdigest(),'automatic_retry':False,'outcome':'unknown','http_status':None}
  with p.open('x',encoding='utf-8') as f:json.dump(record,f);f.flush();os.fsync(f.fileno())
  self.count[kind]=i;return p,record
 def post(self,kind,url,body,headers,maximum):
  # Reserve BEFORE request; uncertain/failed responses consume this attempt.
  p,receipt=self.reserve(kind,body)
  def fail(category,status=None):
   receipt.update(state='call_failed',outcome=category,http_status=status);atomic_json(p,receipt)
   raise ProviderFailure(kind,category,status) from None
  try:
   req=urllib.request.Request(url,data=body,headers=headers,method='POST')
   with self.opener.open(req,timeout=180) as resp:
    code=resp.status
    if not 200<=code<300:return fail(http_category(code),code)
    raw=resp.read(maximum+1);ct=resp.headers.get('Content-Type','')
   if len(raw)>maximum:return fail('response_too_large',code)
  except urllib.error.HTTPError as exc:
   # Do NOT read the error body: it may echo credentials or private prompts.
   code=exc.code;exc.close();return fail(http_category(code),code)
  except (TimeoutError,socket.timeout):return fail('timeout_uncertain')
  except urllib.error.URLError:return fail('network_uncertain')
  except ProviderFailure:raise
  except Exception:return fail('transport_uncertain')
  receipt.update(state='response_received',outcome='response_received_not_quality_approval',http_status=code,response_sha256=hashlib.sha256(raw).hexdigest(),response_bytes=len(raw));atomic_json(p,receipt)
  return raw,ct
