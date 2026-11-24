"""082 bounded generation only. No renderer, publisher, queue or retries."""
from pathlib import Path
import hashlib,json,os,sys,zipfile

ROOT=Path(__file__).resolve().parents[1]
PAYLOAD=Path(__file__).with_name('payload.zip')
WORK=ROOT/'work_082'
WORK.mkdir(exist_ok=False)
with zipfile.ZipFile(PAYLOAD) as z:
    allowed={'accepted071_contract.py','accepted071_providers.py','accepted071_flow.py','cinematic30_contract.py','plan.json','permit.json'}
    if set(z.namelist())!=allowed:raise SystemExit('payload entries mismatch')
    if sum(x.file_size for x in z.infolist())>150000:raise SystemExit('payload too large')
    z.extractall(WORK)
sys.path.insert(0,str(WORK))
from accepted071_contract import validate_plan,digest_json
from accepted071_flow import generate
plan=json.loads((WORK/'plan.json').read_text())
permit=json.loads((WORK/'permit.json').read_text())
check=validate_plan(plan)
if plan['script_lines'][0]!='Yağmurdan sonra toprak neden güzel kokar?' or permit['authorization_id']!='PETRICHOR_CINEMATIC_082_ONCE':raise SystemExit('wrong authorization')
print('082: exactly bounded TTS and five-image generation; retries disabled.',flush=True)
status=generate(plan,permit,ROOT/'result_082',ROOT/'authorization_082')
print('082: generation completed; no rendering, no queue, no publication.',flush=True)
