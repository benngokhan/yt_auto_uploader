import ast,copy,hashlib,importlib.util,json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
import numpy as np
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'motor'))
import boston206 as engine
import boston206_cover as cover
from boston206_job import run_bundle

class BostonContractTests(unittest.TestCase):
 def test_lock_matches_all_code_and_fonts(self):self.assertEqual(engine.verify_template_lock()['version'],'boston-v1-206.1')
 def test_bad_lock_fails_closed(self):
  with mock.patch.object(engine,'sha',return_value='wrong'):
   with self.assertRaisesRegex(ValueError,'changed'):engine.verify_template_lock()
 def test_template_size_and_duration(self):self.assertEqual((engine.W,engine.H,engine.FPS,engine.DURATION),(1080,1920,30,53))
 def test_edges_require_eight_scenes(self):
  with self.assertRaises(ValueError):engine.validate_edges([0,10,53])
 def test_reverse_edges_rejected(self):
  with self.assertRaises(ValueError):engine.validate_edges([0,4,8,12,11,22,34,45,53])
 def test_nan_edges_rejected(self):
  with self.assertRaises(ValueError):engine.validate_edges([0,4,8,12,float('nan'),22,34,45,53])
 def test_traversal_rejected(self):
  with self.assertRaises(ValueError):engine.safe_asset(Path('/tmp'),'../voice.wav')
 def test_turkish_upper(self):self.assertEqual(cover.upper('fatih’in ışığı'),'FATİH’İN IŞIĞI')
 def test_two_line_title_required(self):
  with self.assertRaises(ValueError):cover.layout_title(['TANKLAR','GERÇEK','DEĞİLDİ'])
 def test_empty_title_rejected(self):
  with self.assertRaises(ValueError):cover.layout_title(['','RESSAMI'])
 def test_oversize_title_rejected(self):
  with self.assertRaises(ValueError):cover.layout_title(['A'*150,'B'*150])
 def test_unbalanced_line_widths_rejected(self):
  with self.assertRaises(ValueError):cover.layout_title(['İ','GERÇEK DEĞİLDİ'])
 def test_same_font_size_and_baselines_for_206(self):
  l=cover.layout_title(['FATİH’İN','RESSAMI']);self.assertEqual(l['font_size'],192);self.assertEqual(l['baselines'],[476,683])
 def test_cedilla_breve_clearance(self):
  l=cover.layout_title(['GERÇEK','DEĞİLDİ']);self.assertGreaterEqual(l['min_accent_gap_px'],12)
 def test_approved_cover_colors_and_outline(self):self.assertEqual((cover.GOLD,cover.WHITE),('#c5a774','#f6f1e6'));self.assertEqual(cover.layout_title(['FATİH’İN','RESSAMI'])['outline_px'],2)
 def test_missing_bundle_no_provider_fallback(self):
  with self.assertRaises(ValueError):run_bundle('/this-does-not-exist','/unused-output')
 def test_existing_output_never_overwritten(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(ValueError):run_bundle(d,d)
 def test_invalid_mode_rejected_before_io(self):
  with self.assertRaises(ValueError):run_bundle('/missing','/missing','publish')
 def test_no_provider_queue_or_network_imports(self):
  for name in ['boston206.py','boston206_button.py','boston206_cover.py','boston206_job.py']:
   tree=ast.parse((ROOT/'motor'/name).read_text());imports=[]
   for n in ast.walk(tree):
    if isinstance(n,ast.Import):imports.extend(a.name for a in n.names)
    elif isinstance(n,ast.ImportFrom):imports.append(n.module or '')
   self.assertFalse(any(x.split('.')[0] in {'requests','urllib','tts','gorsel_uret','uploader','google','openai'} for x in imports),name)
 def test_compact_button_font_and_text_occupancy(self):
  from types import SimpleNamespace
  import boston206_button
  f=engine.font(44,True);im=boston206_button.follow(SimpleNamespace(button_font=f));self.assertGreater(f.getlength('Takip Et')/250,.68)
  self.assertEqual(im.size,(1080,1920));self.assertEqual(im.getpixel((540,1080))[3]>0,True)
 def test_cover_created_without_model_or_video(self):
  with tempfile.TemporaryDirectory() as d:
   src=Path(d)/'source.png';Image.new('RGB',(768,1376),(90,60,40)).save(src);out=Path(d)/'kapak.jpg'
   cover.render_cover(src,out,['FATİH’İN','RESSAMI'],category='TARİH',subtitle='Bir portrenin hikâyesi.')
   with Image.open(out) as im:self.assertEqual(im.size,(1080,1920));self.assertEqual(im.mode,'RGB')
   self.assertFalse(list(Path(d).glob('*.mp4')))
 def test_cover_overwrite_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'x.jpg';p.write_bytes(b'keep')
   with self.assertRaises(FileExistsError):cover.render_cover('/missing',p,['FATİH’İN','RESSAMI'])
   self.assertEqual(p.read_bytes(),b'keep')
 def test_long_cover_footer_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'x.jpg';Image.new('RGB',(100,200)).save(p)
   with self.assertRaisesRegex(ValueError,'footer'):cover.render_cover(p,Path(d)/'out.jpg',['FATİH’İN','RESSAMI'],subtitle='uzun cümle '*100)
 def test_cli_check_is_default(self):
  text=(ROOT/'motor/uret.py').read_text();self.assertIn('choices=("check", "stills", "render"), default="check"',text)
 def test_cli_handoff_precedes_legacy_providers(self):
  text=(ROOT/'motor/uret.py').read_text();start=text.index('    a = ap.parse_args()');end=text.index('    ayar = ayar_yukle()',start)
  self.assertIn('return 0',text[start:end]);self.assertIn('a.onay_verildi',text[start:end])

if __name__=='__main__':unittest.main()
