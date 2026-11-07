import json, os, urllib.request, urllib.error
GEM = ["gemini-2.5-flash","gemini-3.6-flash","gemini-2.5-flash-preview-tts"]
k=(os.getenv("GEMINI_API_KEY") or "").strip()
def iste(url, data=None, hdr=None):
    r=urllib.request.Request(url, data=data, headers=hdr or {})
    try:
        with urllib.request.urlopen(r, timeout=30) as x:
            return x.status, dict(x.headers), x.read().decode("utf-8","replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8","replace")[:300]
print("### GEMINI rate-limit basliklari")
for m in GEM:
    st,h,b = iste(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={k}",
                   data=json.dumps({"contents":[{"parts":[{"text":"a"}]}]}).encode(),
                   hdr={"Content-Type":"application/json"})
    rl={kk:v for kk,v in h.items() if "quota" in kk.lower() or "ratelimit" in kk.lower()}
    print(f"{m}: HTTP {st} | {rl if rl else 'rate-limit basligi YOK'}")
g=(os.getenv("GROQ_API_KEY") or "").strip()
st,h,b = iste("https://api.groq.com/openai/v1/models", hdr={"Authorization":"Bearer "+g})
print("\n### GROQ models")
print("HTTP",st,"| ornek:", b[:200])
rl={kk:v for kk,v in h.items() if "rate" in kk.lower() or "retry" in kk.lower()}
print("rate basliklari:", rl if rl else "YOK")
