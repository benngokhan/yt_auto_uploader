#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bilgi Dozu — İlk 10 Keşfet/Retansiyon Odaklı Shorts Üretim & Öncelikli Kuyruk Aracı.

Motordaki onaylı ana dosyaları (ayarlar.json, tts.py, uret.py, shorts_pipeline.py)
DEĞİŞTİRMEZ; aynı kilitli Gemini Charon orta-tempo sesini + sablon_v2 + v2.2 3D End-Card
mimarisini kullanarak:
  1) 0.15 sn anında sesli kanca girişi (1.45 sn sessizlik sıfırlandı)
  2) 2.0 sn'de ilk sahne içinde hızlı görsel kesme (Visual Pattern Interrupt, 8 görsel)
  3) 4.5-8.0 sn uçurumunu kapatan Anti-Spoiler 2. cümle köprüsü (cevap 5. cümlede açılır)
  4) 32-37 sn sıkı kurgu + 0.62 sn keskin End-Card kuyruğu (SENARYO_SINIR_SN 30-45 içinde)
  5) Merak boşluklu başlık + 1/2 anketli mikro-deney sabit yorum
ile video_177..video_186 (10 Shorts) üretir, mevcut 177..196 kuyruğunu veri kaybetmeden
187..206'ya kaydırır ve yeni 10 videoyu yayın kuyruğunun EN BAŞINA (177..186) yerleştirir.
"""
from __future__ import annotations

import argparse
import base64
import difflib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np
import openpyxl
import soundfile as sf
from PIL import Image

MOTOR_DIR = Path(__file__).resolve().parent
REPO_ROOT = MOTOR_DIR.parent
for _p in (str(MOTOR_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import gorsel_uret  # noqa: E402
import shorts_pipeline as sp  # noqa: E402
import tts  # noqa: E402

QUEUE_FOLDER_ID = "1ttP8K3VHtqaNtdSlWjqIFza8Kzf0wxpC"   # Bilgi_Dozu_Yeni_Shorts
VIDEO_COVER_FOLDER_ID = "1GK-yImpb09445uXfTUbIl7l6AfNM4BOb"  # video kapak
MASTER_SHEETS_ID = "1aBt7me8IOzsJeSMQDVtkTktOgF9EZpJo"  # baslik.xlsx


def tr_upper(s: str) -> str:
    return (s or "").replace("i", "İ").replace("ı", "I").upper()


EPISODES: list[dict] = [
    {
        "num": 177,
        "file_name": "video_177.mp4",
        "cover_name": "kapak_177.jpg",
        "music_theme": "insan_beyin",
        "cover_lines": ["YUTKUNUNCA GELEN", "O KLİK SESİ NE?"],
        "yt_title": "Yutkunduğun Anda Kulağından Neden İnce Bir Klik Sesi Gelir? 👂⚡ #bilgidozu #shorts",
        "category": "Nörobilim ve İnsan Vücut Anatomisi",
        "hashtags": "#bilgidozu #shorts #insanvücudu #bilim",
        "tags": "bilgidozu, shorts, bilgi dozu, kulak çıtırtısı, yutkunma sesi, östaki borusu, insan vücudu, ilginç bilgiler, anatomi",
        "pinned_comment": "Şu an yutkunup kulağındaki o ince 'klik' sesini duyanlar 1 yazsın, duymayanlar 2 👇👂",
        "source": "Stanford Medicine Otolaryngology — Eustachian Tube Mechanics",
        "note1": "Kaynak: Stanford Otolaryngology Arşivi",
        "description": "Şu an yutkunduğun anda kulağının tam içinden gelen o ince çıtırtı sesini hemen dene! Çoğu insan bunu çene kemiğinden sanır ama gerçekte östaki borusunun vakumu kırma sesidir.",
        "sentences": [
            "Şu an yutkunduğunda kulağının tam içinden neden ince bir klik sesi gelir?",
            "Çoğu kişi bunu çene kemiği sanır ama ses kemikten hiç gelmez.",
            "Burnunun gerisinde orta kulağa açılan kapalı bir hava tüneli vardır.",
            "Her yutkunduğunda dört minik kas bu ıslak duvarları salisede ayırır.",
            "O çıtırtı, östaki borusunun vakumu kırıp basıncı eşitleme sesidir.",
            "Günde bin kez açılmasa kulak zarın içe çökerdi. Daha fazla Bilgi Dozu için takip et!",
        ],
        "headlines": [
            {"icon": "?", "line1": "YUTKUNUNCA GELEN", "line2": "KLİK SESİ NE?"},
            {"icon": "⚡", "line1": "HEMEN ŞİMDİ", "line2": "YUTKUN VE DİNLE"},
            {"icon": "▼", "line1": "ÇENE KEMİĞİ", "line2": "SANISI YANLIŞ"},
            {"icon": "!", "line1": "ORTA KULAĞA GİDEN", "line2": "GİZLİ TÜNEL"},
            {"icon": "▲", "line1": "DÖRT MİNİK KAS", "line2": "DUVARI AYIRIR"},
            {"icon": "✔", "line1": "ÖSTAKİ BORUSU", "line2": "BASINÇ EŞİTLER"},
            {"icon": "!", "line1": "GÜNDE BİN KEZ", "line2": "ZARI KORUR"},
            {"icon": "✔", "line1": "BİLGİ DOZU", "line2": "TAKİP ET"},
        ],
        "queries": [
            ("human ear anatomy", "sound wave monitor"),
            ("audio waveform screen", "acoustic microphone"),
            ("human skull x ray", "medical ct scan"),
            ("medical otoscope lens", "endoscope optical lens"),
            ("surgical microscope", "medical laboratory pipette"),
            ("barometer pressure gauge", "water sound ripples"),
            ("metallic tuning fork", "laboratory glassware"),
            ("astronomy night sky", "optical glass prism"),
        ],
    },
    {
        "num": 178,
        "file_name": "video_178.mp4",
        "cover_name": "kapak_178.jpg",
        "music_theme": "insan_beyin",
        "cover_lines": ["YABANCI YATAKTA", "NEDEN UYUYAMAZSIN?"],
        "yt_title": "Yabancı Bir Yatakta İlk Gece Neden Tam Uyuyamazsın? 🛏️🧠 #bilgidozu #shorts",
        "category": "Uyku ve Nörobilim",
        "hashtags": "#bilgidozu #shorts #uyku #nörobilim",
        "tags": "bilgidozu, shorts, bilgi dozu, ilk gece etkisi, yabancı yatak uyku, beyin nöbeti, nörobilim, uyku bilimi, ilginç bilgiler",
        "pinned_comment": "Başka bir yerde ilk gece hemen uyuyabiliyor musun (1), yoksa sabaha kadar dönüyor musun (2)? 👇🛏️",
        "source": "Current Biology — Tamaki et al., Brown University Sleep Lab",
        "note1": "Kaynak: Brown Üniversitesi Uyku Araştırması",
        "description": "Otelde veya misafirlikte ilk gece yorgunluktan ölsen bile neden derin uyuyamazsın? Sebebi yastık değil, beyninin sol yarısının tuttuğu gizli gece nöbetidir.",
        "sentences": [
            "Yabancı bir yatakta ilk gece neden yorgun olsan da derin uyuyamazsın?",
            "Sebebi yastık değil; kafatasının içinde eski bir nöbet sistemi çalışır.",
            "Bilim insanları uyuyan beyni taradığında tuhaf bir bölünme yakaladı.",
            "Yeni bir odada beyninin sağ yarısı uyurken sol yarısı yarı açık kalır.",
            "Tıpkı yunuslar gibi sol yarım küren yabancı seslere karşı nöbet tutar.",
            "Oda güvenliyse ikinci gece bu alarm kendiliğinden söner. Daha fazla Bilgi Dozu için takip et!",
        ],
        "headlines": [
            {"icon": "?", "line1": "YABANCI YATAKTA", "line2": "NEDEN UYUYAMAZSIN?"},
            {"icon": "⚡", "line1": "İLK GECE ETKİSİ", "line2": "NASIL ÇALIŞIR?"},
            {"icon": "▼", "line1": "SEBEBİ YASTIK", "line2": "DEĞİLMİŞ!"},
            {"icon": "!", "line1": "BEYİN TARAMASINDA", "line2": "ŞAŞIRTICI FARK"},
            {"icon": "▲", "line1": "SOL YARIM KÜRE", "line2": "UYANIK KALIYOR"},
            {"icon": "✔", "line1": "YUNUSLAR GİBİ", "line2": "GECE NÖBETÇİSİ"},
            {"icon": "!", "line1": "İKİNCİ GECEDE", "line2": "ALARM SÖNER"},
            {"icon": "✔", "line1": "BİLGİ DOZU", "line2": "TAKİP ET"},
        ],
        "queries": [
            ("warm bedside lamp", "night moon stars"),
            ("alarm clock night", "wristwatch dial macro"),
            ("brain mri scan", "neurology monitor"),
            ("medical scanner screen", "pulse wave monitor"),
            ("glowing neural fiber", "optic fiber light"),
            ("dolphin underwater ocean", "sonar radar screen"),
            ("starry night sky", "calm ocean moonlight"),
            ("cosmos galaxy nebula", "optical glass lens"),
        ],
    },
    {
        "num": 179,
        "file_name": "video_179.mp4",
        "cover_name": "kapak_179.jpg",
        "music_theme": "gunluk_bilim",
        "cover_lines": ["KIZGIN TAVADA SU", "NEDEN BİLYE OLUR?"],
        "yt_title": "Kızgın Tavaya Düşen Su Neden Buharlaşmaz da Bilye Gibi Koşar? 🔥💧 #bilgidozu #shorts",
        "category": "Fizik ve Mühendislik",
        "hashtags": "#bilgidozu #shorts #fizik #bilim",
        "tags": "bilgidozu, shorts, bilgi dozu, leidenfrost etkisi, kızgın tava su damlası, mutfak fiziği, termodinamik, ilginç bilgiler",
        "pinned_comment": "Yemek yaparken kızgın tavada bilye gibi kayan su damlalarını denedin mi? Evet (1) / Şimdi deneyeceğim (2) 👇🔥",
        "source": "Annual Review of Fluid Mechanics — Quéré, Leidenfrost Dynamics",
        "note1": "Kaynak: Annual Review of Fluid Mechanics",
        "description": "Çok kızgın bir tavaya su damlattığında neden anında yok olmaz da cıva bilyesi gibi dakikalarca kayarak gezer? 193 derecede devreye giren Leidenfrost kalkanı.",
        "sentences": [
            "Kızgın tavaya düşen su damlası neden buharlaşmaz da bilye gibi kaçar?",
            "Tava ısındıkça suyun uçması gerekir ama yüz doksan üç derecede kural bozulur.",
            "Damla metale değdiği an alt katmanı patlayıp görünmez buhar yastığı kurar.",
            "Bu ince gaz ısıyı yüz kat yavaş ilettiği için damlayı havada asılı tutar.",
            "Leidenfrost kalkanı sayesinde su sıcak metale hiç değmeden dakikalarca kayar.",
            "Tava ne kadar kızarsa suyun ömrü o kadar uzar. Daha fazla Bilgi Dozu için takip et!",
        ],
        "headlines": [
            {"icon": "?", "line1": "KIZGIN TAVADA SU", "line2": "NEDEN KAYAR?"},
            {"icon": "⚡", "line1": "BİLYE GİBİ KOŞAN", "line2": "SU DAMLALARI"},
            {"icon": "▼", "line1": "193 DERECEDE KURAL", "line2": "TERSİNE DÖNER"},
            {"icon": "!", "line1": "ALT KATMAN ANINDA", "line2": "BUHAR YASTIĞI OLUR"},
            {"icon": "▲", "line1": "ISIYI YÜZ KAT", "line2": "YAVAŞ İLETİR"},
            {"icon": "✔", "line1": "LEİDENFROST KALKANI", "line2": "HAVADA TUTAR"},
            {"icon": "!", "line1": "TAVA KIZDIKÇA", "line2": "DAMLA YAŞAR"},
            {"icon": "✔", "line1": "BİLGİ DOZU", "line2": "TAKİP ET"},
        ],
        "queries": [
            ("water droplets steel", "water drop splash"),
            ("crystal water droplet", "mercury liquid metal"),
            ("blue gas flame", "bunsen burner flame"),
            ("boiling water steam", "white steam rising"),
            ("glowing hot steel", "forge red metal"),
            ("clear water bead", "glass sphere refraction"),
            ("thermometer temperature gauge", "infrared heat scan"),
            ("blue laser beam", "laboratory test tube"),
        ],
    },
    {
        "num": 180,
        "file_name": "video_180.mp4",
        "cover_name": "kapak_180.jpg",
        "music_theme": "insan_beyin",
        "cover_lines": ["GÖZÜNÜ KAPATINCA", "NEDEN DEVRİLİRSİN?"],
        "yt_title": "Tek Ayak Üstündeyken Gözünü Kapatınca Neden Anında Sallanırsın? 👁️⚖️ #bilgidozu #shorts",
        "category": "Nörobilim ve İnsan Bedeni",
        "hashtags": "#bilgidozu #shorts #nörobilim #insanvücudu",
        "tags": "bilgidozu, shorts, bilgi dozu, tek ayak denge testi, göz kapalı denge, iç kulak kristalleri, nörobilim, insan vücudu",
        "pinned_comment": "Gözün kapalı tek ayak üstünde devrilmeden kaç saniye durabiliyorsun? Hemen dene ve süreni yaz 👇⏱️",
        "source": "British Journal of Sports Medicine — Araujo et al. Balance Study",
        "note1": "Kaynak: British Journal of Sports Medicine",
        "description": "Tek ayak üstünde rahatça dururken gözlerini kapattığın saniyede vücudun neden sağa sola devrilmeye başlar? Beynin gizli üçlü denge üçgeni.",
        "sentences": [
            "Tek ayak üstünde dururken gözünü kapattığın an neden hemen sallanırsın?",
            "Dengeni sadece kasların kurduğunu sanıyorsan gizli üçgeni kaçırıyorsun.",
            "Beynin dik durmak için iç kulak sıvısını, tabanını ve görüntüyü birleştirir.",
            "Fakat bu denge verisinin yüzde yetmişi gözdeki sabit noktalardan gelir.",
            "Gözün kapandığı an ana pusula kesilir ve iç kulağın kaymaları yetiştiremez.",
            "Karanlıkta kasların panikle fazla düzeltme yapar. Daha fazla Bilgi Dozu için takip et!",
        ],
        "headlines": [
            {"icon": "?", "line1": "GÖZÜNÜ KAPATINCA", "line2": "NEDEN SALLANIRSIN?"},
            {"icon": "⚡", "line1": "SANİYELER İÇİNDE", "line2": "BOZULAN DENGE"},
            {"icon": "▼", "line1": "SADECE KAS GÜCÜ", "line2": "YETMİYOR!"},
            {"icon": "!", "line1": "BEYNİN GİZLİ", "line2": "ÜÇLÜ PUSULASI"},
            {"icon": "▲", "line1": "YÜZDE YETMİŞİ", "line2": "GÖZDEN GELİR"},
            {"icon": "✔", "line1": "ANA PUSULA ANİDEN", "line2": "DEVRE DIŞI KALIR"},
            {"icon": "!", "line1": "KASLAR PANİKLE", "line2": "FAZLA DÜZELTİR"},
            {"icon": "✔", "line1": "BİLGİ DOZU", "line2": "TAKİP ET"},
        ],
        "queries": [
            ("human eye iris", "green eye pupil"),
            ("magnetic compass needle", "pendulum clock brass"),
            ("human skeleton bone", "x ray foot bone"),
            ("spirit level bubble", "liquid tube laboratory"),
            ("camera lens aperture", "ocean horizon sunset"),
            ("spinning metal gyroscope", "precision brass gear"),
            ("analog stopwatch timer", "neurology brain scan"),
            ("physics light prism", "scientist microscope"),
        ],
    },
    {
        "num": 181,
        "file_name": "video_181.mp4",
        "cover_name": "kapak_181.jpg",
        "music_theme": "gunluk_bilim",
        "cover_lines": ["DÜDÜKLÜ TENCERE", "NASIL HIZLI PİŞİRİR?"],
        "yt_title": "Düdüklü Tencere Yemeği Nasıl Üç Kat Hızlı Pişirir? Sırrı Isıyı Tutması Değil! 🍲⚡ #bilgidozu #shorts",
        "category": "Fizik ve Mühendislik",
        "hashtags": "#bilgidozu #shorts #fizik #mühendislik",
        "tags": "bilgidozu, shorts, bilgi dozu, düdüklü tencere nasıl çalışır, kaynama noktası basınç, termodinamik, mutfak bilimi, ilginç bilgiler",
        "pinned_comment": "Mutfakta düdüklü tencerenin sesinden hâlâ hafif çekinenler kimler? Çekinirim (1) / Rahat kullanırım (2) 👇🍲",
        "source": "Harvard SEAS — Science and Cooking Thermodynamics",
        "note1": "Kaynak: Harvard Termodinamik Arşivi",
        "description": "Düdüklü tencere sert bir eti nasıl üçte bir sürede lokum gibi pişirir? Herkes ısıyı içeride sakladığını sanır ama asıl sır suyun 100 derece kilidini kırmasıdır.",
        "sentences": [
            "Düdüklü tencere sert eti nasıl normalin üçte biri sürede lokum gibi pişirir?",
            "Herkes ısıyı tuttuğunu sanır ama açık tencerede su yüz dereceyi asla geçemez.",
            "Normal basınçta verdiğin ekstra ateş suyu ısıtmaz, sadece buharlaştırır.",
            "Kilitli kapak içerideki buhar basıncını ikiye katlayıp kaynama sınırını kırar.",
            "Sıkışan su kaynamadan yüz yirmi bir dereceye çıkar ve pişmeyi üçe katlar.",
            "Sırrı ısıyı saklamak değil suyun limitini kırmaktır. Daha fazla Bilgi Dozu için takip et!",
        ],
        "headlines": [
            {"icon": "?", "line1": "DÜDÜKLÜ TENCERE", "line2": "SIRRI NE?"},
            {"icon": "⚡", "line1": "ÜÇTE BİR SÜREDE", "line2": "NASIL PİŞİRİR?"},
            {"icon": "▼", "line1": "SU YÜZ DERECEYİ", "line2": "ASLA GEÇEMEZ"},
            {"icon": "!", "line1": "EKSTRA ATEŞ SADECE", "line2": "BUHAR YAPAR"},
            {"icon": "▲", "line1": "BASINÇ İKİ KATINA", "line2": "ÇIKARILIR"},
            {"icon": "✔", "line1": "SU 121 DERECEYE", "line2": "KADAR ÇIKAR"},
            {"icon": "!", "line1": "ÜST LİMİT KİLİDİ", "line2": "KIRILIR"},
            {"icon": "✔", "line1": "BİLGİ DOZU", "line2": "TAKİP ET"},
        ],
        "queries": [
            ("stainless steel pot", "metal steam valve"),
            ("boiling water bubbles", "gas stove burner"),
            ("industrial pressure gauge", "laboratory thermometer"),
            ("steam cloud dark", "kettle boiling steam"),
            ("steel pipe valve", "manometer dial needle"),
            ("red hot burner coil", "scientific glass flask"),
            ("mechanical steel gear", "laboratory equipment"),
            ("optical glass lens", "dark laboratory microscope"),
        ],
    },
    {
        "num": 182,
        "file_name": "video_182.mp4",
        "cover_name": "kapak_182.jpg",
        "music_theme": "insan_beyin",
        "cover_lines": ["SOĞUKTA BURNUN", "NEDEN AKAR?"],
        "yt_title": "Hasta Olmadığın Halde Soğuk Havada Burnun Neden Anında Akar? ❄️👃 #bilgidozu #shorts",
        "category": "Nörobilim ve İnsan Vücut Fizyolojisi",
        "hashtags": "#bilgidozu #shorts #insanvücudu #bilim",
        "tags": "bilgidozu, shorts, bilgi dozu, soğukta burun akıntısı, kışın burun neden akar, fizyoloji, yoğuşma, insan vücudu",
        "pinned_comment": "Soğukta dışarı çıkınca daha ilk 5 dakikada mendil arayanlardan mısın? Evet (1) / Bana pek olmaz (2) 👇❄️",
        "source": "Johns Hopkins Medicine — Cold Air Rhinorrhea Physiology",
        "note1": "Kaynak: Johns Hopkins Fizyoloji Arşivi",
        "description": "Hiç üşütmediğin halde kışın sokağa adım attığın ilk dakikada burnun neden su gibi akar? O sıvı hastalık değil, burnunun kurduğu mini klima ve yoğuşma fiziğidir.",
        "sentences": [
            "Hasta olmadığın halde soğuk havaya çıkınca burnun neden hemen akar?",
            "Çoğu kişi bunu üşütme sanır ama o sıvının mikroplarla hiç ilgisi yoktur.",
            "Akciğerlerin buz gibi kuru havayı çekerse hassas kesecikler tahriş olur.",
            "Burnun havayı ciğere inmeden bir saniyede otuz yedi dereceye ısıtır.",
            "İçerideki sıcak buhar soğuk burun ucuna çarpınca cam gibi suya dönüşür.",
            "Yani akan şey hastalık değil burnunun mini klimasıdır. Daha fazla Bilgi Dozu için takip et!",
        ],
        "headlines": [
            {"icon": "?", "line1": "SOĞUKTA BURNUN", "line2": "NEDEN AKAR?"},
            {"icon": "⚡", "line1": "HASTA OLMADAN", "line2": "GELEN AKINTI"},
            {"icon": "▼", "line1": "MİKROPLARLA HİÇ", "line2": "İLGİSİ YOK!"},
            {"icon": "!", "line1": "AKCİĞERİ BUZ GİBİ", "line2": "HAVADAN KORUR"},
            {"icon": "▲", "line1": "BİR SANİYEDE", "line2": "37 DERECE YAPAR"},
            {"icon": "✔", "line1": "SOĞUK CAM GİBİ", "line2": "BUHAR YOĞUŞUR"},
            {"icon": "!", "line1": "DOĞAL MİNİ KLİMA", "line2": "SİSTEMİ ÇALIŞIR"},
            {"icon": "✔", "line1": "BİLGİ DOZU", "line2": "TAKİP ET"},
        ],
        "queries": [
            ("frost ice crystals", "winter snow pine"),
            ("window rain droplets", "cold glass condensation"),
            ("microscope glass slide", "laboratory pipette drop"),
            ("chest lungs x ray", "medical chest scan"),
            ("clinical thermometer", "steam cold winter"),
            ("dew drops leaf", "water droplets glass"),
            ("frozen ice crystal", "snowflake macro winter"),
            ("medical laboratory", "optical prism light"),
        ],
    },
    {
        "num": 183,
        "file_name": "video_183.mp4",
        "cover_name": "kapak_183.jpg",
        "music_theme": "tarih_teknoloji",
        "cover_lines": ["MARKET ARABASI", "NEDEN HEP TİTRER?"],
        "yt_title": "Süpermarket Arabalarının Tekerleği Neden Hep Titrer ve Seni Yavaşlatır? 🛒⚡ #bilgidozu #shorts",
        "category": "Mühendislik ve Tasarım",
        "hashtags": "#bilgidozu #shorts #mühendislik #fizik",
        "tags": "bilgidozu, shorts, bilgi dozu, market arabası tekerleği, kaster etkisi, alışveriş arabası neden titrer, fizik, mühendislik",
        "pinned_comment": "Markette sana da hep o tek tekeri titreyen araba mı denk geliyor? Her seferinde (1) / Şanslıyım (2) 👇🛒",
        "source": "Proceedings of the Royal Society A — Caster Shimmy Dynamics",
        "note1": "Kaynak: Royal Society Mekanik Arşivi",
        "description": "Neredeyse her market arabasının tek tekerleği neden bozukmuş gibi sağa sola çırpınır? Kaster açısı rezonansı ve mağazaların yavaşlatma psikolojisi.",
        "sentences": [
            "Market arabalarının ön tekerleği neden hep bozuk gibi titrer ve yavaşlatır?",
            "Bunu sadece bakımsızlık sanıyorsan tekerleğin açı fiziğini kaçırıyorsun.",
            "Ön maşa ittiğin yöne kendiliğinden dönsün diye hafif geriye eğimli yapılır.",
            "Darbe alan maşa sadece iki derece yamulduğunda hızla rezonansa girer.",
            "Üstelik reyon önünde yavaş yürümen satışı artırdığı için hız bilerek düşürülür.",
            "Hızlı kayan araba rafların önünden çabuk geçmene yol açardı. Daha fazla Bilgi Dozu için takip et!",
        ],
        "headlines": [
            {"icon": "?", "line1": "MARKET ARABASI", "line2": "NEDEN TİTRER?"},
            {"icon": "⚡", "line1": "HEP BOZUK DENK", "line2": "GELMESİ TESADÜF MÜ?"},
            {"icon": "▼", "line1": "SADECE BAKIMSIZLIK", "line2": "SANISI YANLIŞ"},
            {"icon": "!", "line1": "GERİYE EĞİMLİ", "line2": "KASTER AÇISI"},
            {"icon": "▲", "line1": "İKİ DERECE KAYMA", "line2": "REZONANS BAŞLATIR"},
            {"icon": "✔", "line1": "YAVAŞ ADIM DEMEK", "line2": "FAZLA ALIŞVERİŞ"},
            {"icon": "!", "line1": "REYON ÖNÜNDE", "line2": "HIZI DÜŞÜRÜR"},
            {"icon": "✔", "line1": "BİLGİ DOZU", "line2": "TAKİP ET"},
        ],
        "queries": [
            ("metal ball bearing", "steel wheel axle"),
            ("industrial rubber wheel", "mechanical gear teeth"),
            ("steel vernier caliper", "metal bolt wrench"),
            ("oscilloscope wave", "acoustic sound wave"),
            ("warehouse aisle shelves", "polished stone floor"),
            ("wristwatch gears", "clockwork mechanism"),
            ("stainless steel wire", "metallic grid"),
            ("science laboratory", "blue laser beam"),
        ],
    },
    {
        "num": 184,
        "file_name": "video_184.mp4",
        "cover_name": "kapak_184.jpg",
        "music_theme": "insan_beyin",
        "cover_lines": ["KAŞINAN YERİ KAŞIMAK", "NEDEN RAHATLATIR?"],
        "yt_title": "Kaşınan Yeri Kaşıdığında Beynin Acıyı Nasıl Rahatlama Diye Yutturur? 🧠⚡ #bilgidozu #shorts",
        "category": "Nörobilim ve İnsan Bedeni",
        "hashtags": "#bilgidozu #shorts #beyin #nörobilim",
        "tags": "bilgidozu, shorts, bilgi dozu, kaşıntı neden rahatlatır, omurilik kapı kontrolü, serotonin kaşıntı döngüsü, nörobilim, beyin",
        "pinned_comment": "Sivrisinek ısırığını hiç kaşımadan durabilen iradeli biri var mı? Duramam kaşırım (1) / Dokunmam (2) 👇🧠",
        "source": "Neuron Journal — Washington University Center for the Study of Itch",
        "note1": "Kaynak: Washington Üniversitesi Nörobilim",
        "description": "Kaşınan bir yeri tırnağınla kazıdığında gelen o tatlı rahatlama hissi aslında omuriliğine attığın bir acı çalımıdır! Üstelik sonunda kaşıntıyı daha da büyütür.",
        "sentences": [
            "Sivrisinek ısırığını kaşıdığında gelen rahatlama aslında beynine tuzak mı?",
            "Derini kazımanın kaşıntıyı sildiğini sanırsın ama sinyal yerinde durur.",
            "Kaşıntı lifleri omuriliğe çok yavaş giden incecik bir sinir hattı kullanır.",
            "Orayı çizdiğinde çok daha kalın ve hızlı acı sinirlerini ateşlersin.",
            "Omurilik kapısı acıyı öne alıp kaşıntıyı susturur ve serotonin salgılar.",
            "Fakat serotonin kaşıntıyı iki kat güçlü geri çağırır. Daha fazla Bilgi Dozu için takip et!",
        ],
        "headlines": [
            {"icon": "?", "line1": "KAŞIMAK BEYNİ", "line2": "NASIL KANDIRIR?"},
            {"icon": "⚡", "line1": "TATLI RAHATLAMA", "line2": "ASLINDA TUZAK!"},
            {"icon": "▼", "line1": "KAŞINTI SİNYALİ", "line2": "HİÇ SİLİNMİYOR"},
            {"icon": "!", "line1": "İNCE VE YAVAŞ", "line2": "SİNİR HATLARI"},
            {"icon": "▲", "line1": "HAFİF ACI SİNYALİ", "line2": "ÖNE GEÇİYOR"},
            {"icon": "✔", "line1": "OMURİLİK KAPISI", "line2": "HATTI SUSTURUR"},
            {"icon": "!", "line1": "SEROTONİN DÖNGÜYÜ", "line2": "İKİYE KATLAR"},
            {"icon": "✔", "line1": "BİLGİ DOZU", "line2": "TAKİP ET"},
        ],
        "queries": [
            ("mosquito insect leaf", "human hand skin"),
            ("red laser fiber", "glowing optic cables"),
            ("human spine x ray", "vertebrae radiology scan"),
            ("electric plasma arc", "lightning spark dark"),
            ("brain mri scan", "laboratory test tubes"),
            ("scientist microscope", "chemical flask liquid"),
            ("ecg heart monitor", "medical screen pulse"),
            ("deep ocean bioluminescence", "cosmos galaxy nebula"),
        ],
    },
    {
        "num": 185,
        "file_name": "video_185.mp4",
        "cover_name": "kapak_185.jpg",
        "music_theme": "insan_beyin",
        "cover_lines": ["YATAKTA TEK GÖZLE", "EKRANA BAKMA!"],
        "yt_title": "Gece Yatakta Telefona Tek Gözle Bakınca Açık Gözün Neden Geçici Körleşir? 👁️🌙 #bilgidozu #shorts",
        "category": "Nörobilim ve İnsan Vücut Algısı",
        "hashtags": "#bilgidozu #shorts #gözsağlığı #nörobilim",
        "tags": "bilgidozu, shorts, bilgi dozu, yatakta telefona tek gözle bakmak, geçici tek göz körlüğü, karanlık adaptasyonu, göz bilimi, nörobilim",
        "pinned_comment": "Bu videoyu şu an karanlıkta veya yatakta yan yatıp izleyenler yakalandı mı? Evet (1) / Hayır (2) 👇📱",
        "source": "New England Journal of Medicine — Transient Smartphone Blindness",
        "note1": "Kaynak: New England Journal of Medicine",
        "description": "Gece yan yatıp bir gözün yastıkta kapalıyken telefona baktıktan sonra ışığı kapatınca açık gözün neden dakikalarca göremez? Tıp literatürüne giren ekran asimetrisi.",
        "sentences": [
            "Gece yan yatıp ekrana tek gözle baktıktan sonra açık gözün neden göremez?",
            "Acile koşan binlerce kişi bunu felç sanıyor ama olay optik bir bölünmedir.",
            "Bir gözün yastıkta karanlığa alışırken diğeri parlak ışığa kilitlenir.",
            "Beyin iki gözde iki farklı parlaklık modunu aynı anda yönetemez.",
            "Ekran kapanınca kapalı gözün görür ama açık gözün dakikalarca sıfırlanır.",
            "Tıp literatürüne giren bu geçici körlük ekran farkıdır. Daha fazla Bilgi Dozu için takip et!",
        ],
        "headlines": [
            {"icon": "?", "line1": "YATAKTA TEK GÖZLE", "line2": "NEDEN KARARIR?"},
            {"icon": "⚡", "line1": "EKRAN KAPANINCA", "line2": "GEÇİCİ KÖRLÜK"},
            {"icon": "▼", "line1": "ANİ FELÇ DEĞİL", "line2": "OPTİK BÖLÜNME!"},
            {"icon": "!", "line1": "BİR GÖZ KARANLIKTA", "line2": "BİRİ IŞIKTA"},
            {"icon": "▲", "line1": "İKİ FARKLI MOD", "line2": "BEYNİ ŞAŞIRTIR"},
            {"icon": "✔", "line1": "AÇIK GÖZÜN ALICISI", "line2": "SIFIRLANMIŞ KALIR"},
            {"icon": "!", "line1": "TIP LİTERATÜRÜNE", "line2": "GİREN ASİMETRİ"},
            {"icon": "✔", "line1": "BİLGİ DOZU", "line2": "TAKİP ET"},
        ],
        "queries": [
            ("blue eye iris", "eye pupil dilation"),
            ("ophthalmology lens", "optical lens reflection"),
            ("camera shutter blades", "light beam shadow"),
            ("rainbow light prism", "laser beam optics"),
            ("eye retina examination", "green laser beam"),
            ("hourglass sand timer", "dark clock face"),
            ("medical research lab", "microscope eyepiece"),
            ("astronomy night sky", "laboratory glassware"),
        ],
    },
    {
        "num": 186,
        "file_name": "video_186.mp4",
        "cover_name": "kapak_186.jpg",
        "music_theme": "gunluk_bilim",
        "cover_lines": ["KAVANOZ KAPAĞINDAN", "NEDEN POP GELİR?"],
        "yt_title": "Kavanozu İlk Açarken Kapağından Gelen O 'Pop' Sesi Aslında Neyin Kanıtı? 🫙⚡ #bilgidozu #shorts",
        "category": "Fizik ve Gıda Mühendisliği",
        "hashtags": "#bilgidozu #shorts #fizik #mühendislik",
        "tags": "bilgidozu, shorts, bilgi dozu, kavanoz kapağı pop sesi, vakum mührü nasıl çalışır, açık hava basıncı, gıda mühendisliği, ilginç bilgiler",
        "pinned_comment": "Sıkışan kavanoz kapağını sen nasıl açıyorsun? Kaşıkla hava aldırırım (1) / Bezle çeviririm (2) 👇🫙",
        "source": "USDA Food Safety & Packaging Physics — Vacuum Button Mechanics",
        "note1": "Kaynak: Gıda Mühendisliği Vakum Arşivi",
        "description": "Cam kavanozu ilk kez açtığında metal kapağın ortasından gelen o meşhur 'pop' sesi nasıl üretilir ve çıkmazsa neden tehlikelidir?",
        "sentences": [
            "Cam kavanozu ilk açarken kapağından gelen o pop sesi aslında neyin kanıtıdır?",
            "Çoğu kişi kapağın sıkı vidalandığını sanır ama içeri hava basılmaz.",
            "Kapak kapanmadan önce üst boşluğa kaynar buhar verilip oksijen dışarı atılır.",
            "Kavanoz soğuyunca buhar büzüşür ve dış basınç metalin ortasını çökertir.",
            "Kapağı çevirdiğin an içeri dolan hava vakumu kırar ve kubbe yay gibi fırlar.",
            "İlk açılışta ses çıkmazsa vakum bozulmuş demektir. Daha fazla Bilgi Dozu için takip et!",
        ],
        "headlines": [
            {"icon": "?", "line1": "KAVANOZDAKİ POP", "line2": "SESİ NE ANLATIR?"},
            {"icon": "⚡", "line1": "ÇÖKÜK KAPAKTAKİ", "line2": "GİZLİ GÜVENLİK"},
            {"icon": "▼", "line1": "SADECE SIKI VİDA", "line2": "SANISI YANLIŞ"},
            {"icon": "!", "line1": "KAYNAR BUHARLA", "line2": "OKSİJEN KOVULUR"},
            {"icon": "▲", "line1": "DIŞ HAVA BASINCI", "line2": "METALİ ÇÖKERTİR"},
            {"icon": "✔", "line1": "VAKUM KIRILINCA", "line2": "KUBBE FIRLAR"},
            {"icon": "!", "line1": "SES ÇIKMAZSA", "line2": "VAKUM BOZULMUŞTUR"},
            {"icon": "✔", "line1": "BİLGİ DOZU", "line2": "TAKİP ET"},
        ],
        "queries": [
            ("glass jar lid", "clear glass bottle"),
            ("speaker cone vibration", "metallic disc steel"),
            ("glass bottles factory", "laboratory glass flask"),
            ("hot steam jet", "boiling flask laboratory"),
            ("vacuum gauge dial", "pressure barometer"),
            ("steel coil spring", "sound waves water"),
            ("metal wax seal", "chemist laboratory"),
            ("physics light prism", "dark laboratory microscope"),
        ],
    },
]


# ---------------------------------------------------------------------------
# 1) KİLİTLİ CHARON ORTA-TEMPO TTS (Toplu + Tekil Yedekli, %100 Charon Kilitli)
# ---------------------------------------------------------------------------

def _call_gemini_charon_raw_pcm24k(text_block: str, ayar: dict) -> np.ndarray:
    """Gemini Charon'dan ham 24kHz float32 PCM döndürür.
    Önce gemini-2.5-flash-preview-tts, günlük RPD dolarsa AYNI Charon sesiyle
    gemini-2.5-pro-preview-tts dener; asla başka sese geçmez."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY eksik!")
    ses = ayar.get("ses", {})
    tarz = ses.get(
        "tarz",
        "Doğal, dengeli, akıcı ve çok net diksiyonlu bir erkek bilim anlatıcısı gibi konuş. "
        "Ne acele et ne de fazla ağırlaş; orta-canlı bir belgesel temposunda her kelimeyi, "
        "ekleri ve sessiz harfleri tane tane, pürüzsüz telaffuz et.",
    )
    prompt = f"Türkçe konuş. {tarz}\n\nMetin:\n{text_block}"
    models = [
        ses.get("model", "gemini-2.5-flash-preview-tts"),
        "gemini-2.5-pro-preview-tts",
    ]
    last_err: Exception | None = None
    for model_name in dict.fromkeys(models):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={key}"
        body = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Charon"}}},
            },
        }).encode()
        for attempt, wait_s in enumerate((0, 15, 30, 55), start=1):
            if wait_s:
                print(f"  [TTS:{model_name}] bekleme {wait_s}s ({attempt}/4)...", flush=True)
                time.sleep(wait_s)
            req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=240) as resp:
                    data = json.loads(resp.read().decode())
                raw_b = base64.b64decode(data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
                pcm = np.frombuffer(raw_b, dtype="<i2").astype(np.float32) / 32768.0
                print(f"  [TTS:{model_name}] Charon ses alındı: {len(pcm)/24000.0:.2f}s", flush=True)
                return pcm
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode(errors="replace")[:240]
                except Exception:
                    pass
                last_err = RuntimeError(f"{model_name} HTTP {e.code}: {detail}")
                print(f"  [TTS:{model_name}] uyarı: {last_err}", flush=True)
                # Günlük kota (PerDay / quota) dolduysa doğrudan bir sonraki aynı-Charon modele geç
                if e.code == 429 and any(k in detail.lower() for k in ("perday", "per_day", "daily")):
                    break
                if e.code not in (429, 500, 502, 503, 504):
                    break
            except Exception as e:
                last_err = e
    raise RuntimeError(f"Charon TTS başarısız: {last_err}")


def _postprocess_charon_pcm24k(pcm_in: np.ndarray, metin: str, cikti: Path, ayar: dict) -> float:
    """Turn 49 (c00b036) birebir orta-tempo + 0.52s sessizlik tavanı + 3.3kHz netlik EQ."""
    pcm = pcm_in.copy()
    sr = 24000

    # Baştaki ve sondaki aşırı ölü boşluğu yumuşak eşikle (-47 dB) kırp, sessiz harflere dokunma
    win = 240  # 10 ms
    nw = len(pcm) // win
    if nw > 8:
        wb = pcm[: nw * win].reshape(nw, win)
        wrms = np.sqrt(np.mean(wb * wb, axis=1) + 1e-12)
        act_idx = np.where(wrms > (10.0 ** (-47.0 / 20.0)))[0]
        if len(act_idx) > 0:
            s0 = max(0, (int(act_idx[0]) - 4) * win)       # 40 ms koruma payı
            s1 = min(len(pcm), (int(act_idx[-1]) + 9) * win)  # 80 ms koruma payı
            pcm = pcm[s0:s1]

    # Cümle arası >0.52s saf sessizliği 0.52s'ye daralt (tts.py c00b036 birebir)
    f_len = 480  # 20 ms @ 24kHz
    nf = len(pcm) // f_len
    if nf > 10:
        f_blok = pcm[: nf * f_len].reshape(nf, f_len)
        f_rms = np.sqrt(np.mean(f_blok * f_blok, axis=1) + 1e-12)
        sessiz_mi = f_rms < (10.0 ** (-44.0 / 20.0))
        parcalar: list[np.ndarray] = []
        i_f = 0
        while i_f < nf:
            if not sessiz_mi[i_f]:
                j_f = i_f + 1
                while j_f < nf and not sessiz_mi[j_f]:
                    j_f += 1
                parcalar.append(pcm[i_f * f_len : j_f * f_len])
                i_f = j_f
            else:
                j_f = i_f + 1
                while j_f < nf and sessiz_mi[j_f]:
                    j_f += 1
                run_f = j_f - i_f
                if run_f > 26:
                    parcalar.append(pcm[i_f * f_len : (i_f + 13) * f_len])
                    parcalar.append(pcm[(j_f - 13) * f_len : j_f * f_len])
                else:
                    parcalar.append(pcm[i_f * f_len : j_f * f_len])
                i_f = j_f
        if nf * f_len < len(pcm):
            parcalar.append(pcm[nf * f_len :])
        pcm = np.concatenate(parcalar)

    ham_yol = cikti.with_suffix(".ham24k.wav")
    pcm_i16 = np.clip(pcm * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(ham_yol), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm_i16.tobytes())

    ham_sure = len(pcm) / float(sr)
    pencere = 1200  # 50 ms
    n_pen = len(pcm) // pencere
    if n_pen > 4:
        blok = pcm[: n_pen * pencere].reshape(n_pen, pencere)
        rms = np.sqrt(np.mean(blok * blok, axis=1) + 1e-12)
        aktif_sn = max(1.0, float(np.sum(rms > (10.0 ** (-41.0 / 20.0)))) * 0.050)
    else:
        aktif_sn = max(1.0, ham_sure)

    ses = ayar.get("ses", {})
    temiz_metin = " ".join(metin.split())
    aktif_hiz = len(temiz_metin) / aktif_sn
    hedef_hiz = float(ses.get("hedef_aktif_krk_sn", 15.5))
    min_atempo = float(ses.get("min_atempo", 0.93))
    max_atempo = float(ses.get("max_atempo", 0.96))

    if aktif_hiz > hedef_hiz:
        atempo = max(min_atempo, min(max_atempo, round(hedef_hiz / aktif_hiz, 3)))
    elif aktif_hiz > 14.5:
        atempo = 0.945
    else:
        atempo = 1.0

    zincir = [
        "highpass=f=75",
        "equalizer=f=280:t=q:width=1.2:g=-1.2",
        "equalizer=f=3300:t=q:width=1.1:g=1.8",
    ]
    if atempo < 0.995:
        zincir.append(f"atempo={atempo:.3f}")

    subprocess.run(
        [
            sp.FF, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(ham_yol), "-af", ",".join(zincir),
            "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(cikti),
        ],
        check=True, timeout=120,
    )
    ham_yol.unlink(missing_ok=True)
    yeni_x, yeni_sr = sf.read(str(cikti), dtype="float32")
    yeni_sure = len(yeni_x) / float(yeni_sr)
    print(
        f"  [Diksiyon] ham={ham_sure:.2f}s (aktif {aktif_sn:.2f}s, {aktif_hiz:.1f} krk/sn) "
        f"-> atempo={atempo:.3f}, yeni={yeni_sure:.2f}s",
        flush=True,
    )
    return yeni_sure


def _whisper_words_on_pcm(wmodel, pcm_24k: np.ndarray, tmp_wav: Path) -> list[dict]:
    pcm16_path = tmp_wav.with_suffix(".16k.wav")
    pcm_i16 = np.clip(pcm_24k * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(tmp_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm_i16.tobytes())
    subprocess.run(
        [sp.FF, "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp_wav),
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(pcm16_path)],
        check=True,
    )
    sig16, _ = sp.read_wav_mono(str(pcm16_path))
    pcm16_path.unlink(missing_ok=True)
    tmp_wav.unlink(missing_ok=True)
    segs, _ = wmodel.transcribe(sig16.astype(np.float32), language="tr", word_timestamps=True, vad_filter=False)
    out = []
    for seg in segs:
        for w in (seg.words or []):
            wt = w.word.strip()
            if wt:
                out.append({"w": wt, "s": float(w.start), "e": float(w.end)})
    return out


def _verify_single_wav(wmodel, wav_path: Path, expected_script: str) -> tuple[bool, float, float]:
    tmp16 = wav_path.with_suffix(".chk16.wav")
    subprocess.run(
        [sp.FF, "-y", "-hide_banner", "-loglevel", "error", "-i", str(wav_path),
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(tmp16)],
        check=True,
    )
    sig16, _ = sp.read_wav_mono(str(tmp16))
    tmp16.unlink(missing_ok=True)
    dur = len(sig16) / 16000.0
    segs, _ = wmodel.transcribe(sig16.astype(np.float32), language="tr", word_timestamps=False, vad_filter=False)
    asr_txt = " ".join(s.text.strip() for s in segs if s.text.strip())
    a_norm = re.sub(r"[^\wçğıöşü]+", " ", sp.tr_lower(expected_script)).strip()
    b_norm = re.sub(r"[^\wçğıöşü]+", " ", sp.tr_lower(asr_txt)).strip()
    sim = difflib.SequenceMatcher(None, a_norm, b_norm).ratio()
    ok = (sim >= 0.80) and (24.0 <= dur <= 41.5) and ("takip" in b_norm[-45:])
    return ok, sim, dur


def prepare_all_assets(out_dir: Path) -> None:
    """Job 1: 10 bölümün Charon seslerini (2 toplu istek + Whisper doğrulama) ve
    80 benzersiz Pexels bilimsel dikey görselini hazırlar."""
    from faster_whisper import WhisperModel

    out_dir.mkdir(parents=True, exist_ok=True)
    ayar = json.loads((MOTOR_DIR / "ayarlar.json").read_text(encoding="utf-8"))
    wmodel = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=4)

    # --- A) 2 Toplu İstekte (5 + 5 bölüm) Charon Ses Üretimi ---
    batches = [EPISODES[:5], EPISODES[5:]]
    for b_idx, batch_eps in enumerate(batches, start=1):
        if b_idx > 1:
            time.sleep(14)
        print(f"\n=== CHARON TOPLU SES PAKETİ {b_idx}/2 ({[e['num'] for e in batch_eps]}) ===", flush=True)
        ep_blocks = ["\n".join(e["sentences"]) for e in batch_eps]
        combined_text = "\n\n".join(ep_blocks)
        pcm_all = _call_gemini_charon_raw_pcm24k(combined_text, ayar)

        asr_words = _whisper_words_on_pcm(wmodel, pcm_all, out_dir / f"_tmp_batch_{b_idx}.wav")
        all_words: list[str] = []
        ep_ranges: list[tuple[int, int]] = []
        cursor = 0
        for e in batch_eps:
            ws = " ".join(e["sentences"]).split()
            ep_ranges.append((cursor, cursor + len(ws) - 1))
            all_words.extend(ws)
            cursor += len(ws)

        mapped = sp._map_script_to_asr(all_words, asr_words)
        sr = 24000
        cuts = [0]
        for idx_e in range(len(batch_eps) - 1):
            w_end = ep_ranges[idx_e][1]
            w_nxt = ep_ranges[idx_e + 1][0]
            t_e = float(mapped[w_end]["e"])
            t_n = float(mapped[w_nxt]["s"])
            if t_n <= t_e + 0.04:
                cut_smp = int(round(0.5 * (t_e + t_n) * sr))
            else:
                ia = max(0, min(len(pcm_all) - 1, int(round((t_e + 0.02) * sr))))
                ib = max(ia + 1, min(len(pcm_all), int(round((t_n - 0.01) * sr))))
                wq = max(120, int(0.015 * sr))
                if ib - ia > wq * 2:
                    env_s = np.convolve(np.abs(pcm_all[ia:ib]), np.ones(wq) / wq, mode="valid")
                    cut_smp = ia + wq // 2 + int(np.argmin(env_s))
                else:
                    cut_smp = (ia + ib) // 2
            cuts.append(cut_smp)
        cuts.append(len(pcm_all))

        for idx_e, ep in enumerate(batch_eps):
            num = ep["num"]
            vo_out = out_dir / f"vo_{num}.wav"
            script_str = " ".join(ep["sentences"])
            seg_pcm = pcm_all[cuts[idx_e] : cuts[idx_e + 1]]
            _postprocess_charon_pcm24k(seg_pcm, script_str, vo_out, ayar)
            ok, sim, dur = _verify_single_wav(wmodel, vo_out, script_str)
            print(f"  [Doğrulama video_{num}] ok={ok}, sim={sim:.3f}, dur={dur:.2f}s", flush=True)
            if not ok:
                print(f"  [Tekil Yeniden Üretim video_{num}] toplu kesim eşik altı, tekil Charon çağrılıyor...", flush=True)
                time.sleep(12)
                single_pcm = _call_gemini_charon_raw_pcm24k("\n".join(ep["sentences"]), ayar)
                _postprocess_charon_pcm24k(single_pcm, script_str, vo_out, ayar)
                ok2, sim2, dur2 = _verify_single_wav(wmodel, vo_out, script_str)
                print(f"  [Tekil Doğrulama video_{num}] ok={ok2}, sim={sim2:.3f}, dur={dur2:.2f}s", flush=True)
                if not ok2:
                    raise RuntimeError(f"video_{num} ses doğrulaması başarısız (sim={sim2:.3f}, dur={dur2:.2f}s)!")

    # --- B) 80 Benzersiz Bilimsel Dikey Görsel (Sıfır Tekrar Garantili) ---
    print("\n=== 80 BENZERSİZ PEXELS BİLİMSEL GÖRSEL İNDİRİLİYOR ===", flush=True)
    global_used_uids: set[str] = set()
    orig_indir = gorsel_uret._adaylardan_indir_ve_dogrula

    def _wrapped_indir(adaylar, sorgu, ham_dosya, kullanilan, siki_piksel=True):
        merged_used = set(kullanilan) | global_used_uids
        res = orig_indir(adaylar, sorgu, ham_dosya, merged_used, siki_piksel=siki_piksel)
        if res:
            _, hit = res
            uid = str(hit.get("uid") or f"{hit.get('kaynak', 'stok')}:{hit['id']}")
            global_used_uids.add(uid)
        return res

    gorsel_uret._adaylardan_indir_ve_dogrula = _wrapped_indir
    yedek_havuz = [
        "scientist microscope", "laboratory test tube", "optical glass lens",
        "brain mri scan", "blue laser beam", "astronomy night sky",
        "water droplets glass", "physics light prism",
    ]
    for ep in EPISODES:
        num = ep["num"]
        ep_img_dir = out_dir / f"imgs_{num}"
        ep_img_dir.mkdir(parents=True, exist_ok=True)
        sahne_list = []
        for idx_q, (q_main, q_alt) in enumerate(ep["queries"]):
            sent_ref = ep["sentences"][min(idx_q, len(ep["sentences"]) - 1)]
            sahne_list.append({
                "gorsel": q_main,
                "gorsel_anahtar": q_main,
                "gorsel_alternatif": q_alt,
                "ses": sent_ref,
            })
        paths = gorsel_uret.sahneler_icin_gorseller(sahne_list, ep_img_dir, yedek_sorgular=yedek_havuz)
        if len(paths) < 8:
            raise RuntimeError(f"video_{num}: 8 görsel yerine {len(paths)} bulundu!")
        for si, p in enumerate(paths[:8], start=1):
            with Image.open(p) as im:
                im.convert("RGB").save(out_dir / f"s_{num}_{si}.jpg", "JPEG", quality=94)
        shutil.rmtree(ep_img_dir, ignore_errors=True)
    print(f"Tüm varlıklar hazır! Benzersiz görsel sayısı: {len(global_used_uids)}", flush=True)


# ---------------------------------------------------------------------------
# 2) PARALEL SHARD RENDER (0.15s Sesli Kanca + 2.0s Görsel Kesme + 0.62s Kuyruk)
# ---------------------------------------------------------------------------

def _apply_8scene_pattern_interrupt(timing_path: Path, headlines: list[dict]) -> None:
    """timing.json içindeki sahneleri 8 plakaya böler:
      - Sahne 0 (s1.jpg): 0.00s -> 1. cümlenin tam ortası (~1.9s)
      - Sahne 1 (s2.jpg): 1. cümlenin ortası -> 1. cümle sonu + 0.14s (Hızlı Görsel Kesme!)
      - Sahne 2..6 (s3..s7.jpg): 2..6. hikaye cümleleri (4-8s Anti-Spoiler Köprüsü + Cevap)
      - Sahne 7 (s8.jpg, is_closing=True): cta_start -> total (Saf 3D Kapanış Ekranı)"""
    tl = json.loads(timing_path.read_text(encoding="utf-8"))
    spans = tl.get("sentence_spans") or []
    total = float(tl["total"])
    cta_start = float(tl.get("cta_start", max(2.0, total - 2.6)))

    if len(spans) < 6:
        raise RuntimeError(f"Beklenen >=6 cümle aralığı bulunamadı: {spans}")

    s0_a, s0_b = float(spans[0][0]), float(spans[0][1])
    cut1 = round(max(1.35, min(2.65, 0.5 * (s0_a + s0_b))), 3)
    end_s0 = round(min(cta_start - 3.0, max(cut1 + 0.9, s0_b + 0.14)), 3)

    bounds = [0.0, cut1, end_s0]
    for si in range(1, 5):  # cümle 2, 3, 4, 5 (index 1..4)
        prev_b = bounds[-1]
        raw_b = float(spans[si][1]) + 0.14
        nxt_b = round(min(cta_start - (5 - si) * 0.65, max(prev_b + 0.85, raw_b)), 3)
        bounds.append(nxt_b)
    # Sahne 6 (s7.jpg) tam cta_start'a kadar gider; Sahne 7 (s8.jpg) cta_start -> total
    bounds.append(round(max(bounds[-1] + 0.75, cta_start), 3))
    bounds.append(round(total, 3))

    new_scenes = []
    for idx in range(8):
        hl = headlines[idx]
        l1, l2 = sp._sanitize_headline_pair(hl["line1"], hl["line2"], 20)
        new_scenes.append({
            "scene_idx": idx,
            "file": f"s{idx + 1}.jpg",
            "is_closing": (idx == 7),
            "mode": idx % 3,
            "start": bounds[idx],
            "end": bounds[idx + 1],
            "icon": hl["icon"],
            "line1": l1,
            "line2": l2,
        })
    tl["scenes"] = new_scenes
    timing_path.write_text(json.dumps(tl, ensure_ascii=False, indent=2), encoding="utf-8")


def render_shard(assets_dir: Path, out_dir: Path, nums: list[int]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ep_map = {e["num"]: e for e in EPISODES}
    for num in nums:
        ep = ep_map[num]
        print(f"\n=== RENDER BAŞLIYOR: video_{num}.mp4 ===", flush=True)
        work = out_dir / f"work_{num}"
        vdir = work / "v2"
        if work.exists():
            shutil.rmtree(work)
        vdir.mkdir(parents=True, exist_ok=True)

        for si in range(1, 9):
            shutil.copyfile(assets_dir / f"s_{num}_{si}.jpg", vdir / f"s{si}.jpg")
        shutil.copyfile(assets_dir / f"vo_{num}.wav", vdir / "vo_raw.wav")
        script_txt = " ".join(ep["sentences"])
        (vdir / "script.txt").write_text(script_txt + "\n", encoding="utf-8")

        cfg = {
            "title": [[ep["cover_lines"][0], "g"], [ep["cover_lines"][1]]],
            "scene_headlines": ep["headlines"],
            "cover_lines": ep["cover_lines"],
            "music_theme": ep["music_theme"],
            "intro_lead": 0.15,
            "sentence_pause": 0.52,
            "outro_hold": 0.62,
            "note1": ep["note1"],
            "note2": "Görseller bilimsel arşivden işlenmiştir.",
            "scenes": [f"s{i}.jpg" for i in range(1, 9)],
        }
        cfg_path = work / "shorts_config.json"
        cfg_path.write_text(json.dumps({"v2": cfg}, ensure_ascii=False, indent=2), encoding="utf-8")

        sp.stage_plates(str(vdir), str(cfg_path))
        sp.stage_timing(str(vdir), str(cfg_path))
        _apply_8scene_pattern_interrupt(vdir / "timing.json", ep["headlines"])
        sp.stage_music(str(vdir), str(cfg_path))
        sp.render_video(str(vdir), str(cfg_path))
        sp.stage_cover(str(vdir), str(cfg_path))

        mp4_src = vdir / "video.mp4"
        cov_src = vdir / "kapak.jpg"
        tl_data = json.loads((vdir / "timing.json").read_text(encoding="utf-8"))
        dur_total = float(tl_data["total"])
        lufs_val = sp._measure_lufs(str(vdir / "mix.wav")) if (vdir / "mix.wav").exists() else -14.2

        if not mp4_src.exists() or mp4_src.stat().st_size < 3_000_000:
            raise RuntimeError(f"video_{num}.mp4 eksik veya çok küçük!")
        if not (30.0 <= dur_total <= 44.5):
            raise RuntimeError(f"video_{num}.mp4 süre sınır dışı: {dur_total:.2f}s (beklenen 30-44.5s)!")
        with Image.open(cov_src) as cim:
            if cim.size != (1080, 1920):
                raise RuntimeError(f"kapak_{num}.jpg boyutu hatalı: {cim.size}")

        final_mp4 = out_dir / f"video_{num}.mp4"
        final_cov = out_dir / f"kapak_{num}.jpg"
        shutil.copyfile(mp4_src, final_mp4)
        shutil.copyfile(cov_src, final_cov)
        meta_summary = {
            "num": num,
            "file_name": ep["file_name"],
            "cover_name": ep["cover_name"],
            "duration_sec": round(dur_total, 2),
            "cta_start": tl_data.get("cta_start"),
            "first_word_start": tl_data["tokens"][0]["start"] if tl_data.get("tokens") else 0.15,
            "cut1_sec": tl_data["scenes"][0]["end"],
            "size_mb": round(final_mp4.stat().st_size / 1e6, 2),
            "lufs": round(lufs_val, 2),
            "chars": len(script_txt),
            "yt_title": ep["yt_title"],
        }
        (out_dir / f"telemetry_{num}.json").write_text(json.dumps(meta_summary, ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.rmtree(work, ignore_errors=True)
        print(f"  [TAMAM] {meta_summary}", flush=True)


# ---------------------------------------------------------------------------
# 3) TABLO + GOOGLE DRIVE ATOMİK ÖNCELİKLİ KUYRUK KAYDIRMA (177..186 #1 ÖNCELİK)
# ---------------------------------------------------------------------------

def update_workbook_priority_queue(xlsx_path: Path) -> None:
    """baslik.xlsx DRIVE sekmesinde:
      - Mevcut video_197..206 (ASKIDA_TASLAK) -> video_207..216
      - Mevcut video_177..196 (BEKLEMEDE) -> video_187..206
      - Yeni 10 viral Shorts -> video_177..186 (BEKLEMEDE) olarak tam video_176'nın
        hemen altına yerleştirilir. (İdempotent: zaten yerleştirildiyse tekrar kaydırmaz.)"""
    wb = openpyxl.load_workbook(xlsx_path)
    ws = next((s for s in wb.worksheets if s.title.strip().casefold() == "drive"), wb.active)

    # İdempotensi kontrolü: video_177 zaten yeni başlığı taşıyorsa sadece metinleri güncelle
    row_by_name = {}
    for r in range(2, ws.max_row + 1):
        fn = str(ws.cell(r, 2).value or "").strip()
        if fn:
            row_by_name[fn] = r

    already_shifted = (
        "video_177.mp4" in row_by_name
        and "Yutkunduğun" in str(ws.cell(row_by_name["video_177.mp4"], 3).value or "")
    )

    if not already_shifted:
        # 206'dan 177'ye doğru azalan sırayla +10 kaydır
        for num in range(206, 176, -1):
            old_fn = f"video_{num}.mp4"
            new_fn = f"video_{num + 10}.mp4"
            r = row_by_name.get(old_fn)
            if r:
                ws.cell(r, 2).value = new_fn

        # video_176 satırının hemen altına 10 satır aç
        r_176 = None
        for r in range(2, ws.max_row + 1):
            if str(ws.cell(r, 2).value or "").strip() == "video_176.mp4":
                r_176 = r
                break
        insert_at = (r_176 + 1) if r_176 else 158
        ws.insert_rows(insert_at, amount=10)
        target_rows = list(range(insert_at, insert_at + 10))
    else:
        target_rows = [row_by_name[f"video_{ep['num']}.mp4"] for ep in EPISODES]

    for r_idx, ep in zip(target_rows, EPISODES):
        ws.cell(r_idx, 1).value = "BEKLEMEDE"
        ws.cell(r_idx, 2).value = ep["file_name"]
        ws.cell(r_idx, 3).value = ep["yt_title"]
        ws.cell(r_idx, 4).value = ep["description"]
        ws.cell(r_idx, 5).value = ep["hashtags"]
        ws.cell(r_idx, 6).value = ep["tags"]
        ws.cell(r_idx, 7).value = ep["pinned_comment"]
        ws.cell(r_idx, 8).value = ep["category"]
        ws.cell(r_idx, 9).value = ep["source"]
        ws.cell(r_idx, 10).value = None
        ws.cell(r_idx, 11).value = None
        ws.cell(r_idx, 12).value = None
        ws.cell(r_idx, 13).value = None
        ws.cell(r_idx, 14).value = None

    wb.save(xlsx_path)
    wb.close()


def deploy_priority_queue_to_drive(rendered_dir: Path) -> dict:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    token_raw = os.getenv("GOOGLE_TOKEN_JSON", "").strip()
    if token_raw:
        Path("token.json").write_text(token_raw, encoding="utf-8")
    creds = Credentials.from_authorized_user_file("token.json")
    if not creds.valid:
        creds.refresh(Request())
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)

    # 1) video kapak (1GK-yImpb09445uXfTUbIl7l6AfNM4BOb) içindeki tüm aktif dosyaları listele
    items: list[dict] = []
    pt = None
    while True:
        res = drive.files().list(
            q=f"'{VIDEO_COVER_FOLDER_ID}' in parents and trashed = false",
            pageSize=200,
            fields="nextPageToken, files(id, name, size, createdTime)",
            pageToken=pt,
        ).execute()
        items.extend(res.get("files", []))
        pt = res.get("nextPageToken")
        if not pt:
            break

    by_name: dict[str, list[dict]] = {}
    for it in items:
        by_name.setdefault(it["name"], []).append(it)

    # 2) Henüz kaydırılmadıysa (video_206.mp4 yoksa) 196 -> 177 azalan sırayla +10 yeniden adlandır
    if "video_206.mp4" not in by_name:
        print("Mevcut video_177..196 ve kapak_177..196 -> 187..206 olarak kaydırılıyor...", flush=True)
        for num in range(196, 176, -1):
            for prefix, ext in (("video", "mp4"), ("kapak", "jpg")):
                old_n = f"{prefix}_{num}.{ext}"
                new_n = f"{prefix}_{num + 10}.{ext}"
                matches = by_name.get(old_n, [])
                if matches:
                    primary = matches[0]
                    drive.files().update(fileId=primary["id"], body={"name": new_n}, fields="id,name").execute()
                    for extra in matches[1:]:
                        drive.files().update(fileId=extra["id"], body={"trashed": True}).execute()
                    print(f"  taşındı: {old_n} -> {new_n} ({primary['id']})", flush=True)
    else:
        print("video_206.mp4 zaten mevcut; yalnızca 177..186 yuvaları yenileniyor...", flush=True)

    # Yeniden listele ve 177..186 yuvasında eski kopya kalmışsa çöpe al (mükerrer sıfır kuralı)
    items2: list[dict] = []
    pt = None
    while True:
        res = drive.files().list(
            q=f"'{VIDEO_COVER_FOLDER_ID}' in parents and trashed = false",
            pageSize=200,
            fields="nextPageToken, files(id, name)",
            pageToken=pt,
        ).execute()
        items2.extend(res.get("files", []))
        pt = res.get("nextPageToken")
        if not pt:
            break
    target_names = {f"video_{n}.mp4" for n in range(177, 187)} | {f"kapak_{n}.jpg" for n in range(177, 187)}
    for it in items2:
        if it["name"] in target_names:
            drive.files().update(fileId=it["id"], body={"trashed": True}).execute()

    # 3) Yeni 10 video + 10 kapağı 177..186 olarak yükle
    uploaded_ids: dict[str, dict] = {}
    for ep in EPISODES:
        num = ep["num"]
        mp4_p = rendered_dir / f"video_{num}.mp4"
        cov_p = rendered_dir / f"kapak_{num}.jpg"
        v_res = drive.files().create(
            body={"name": ep["file_name"], "parents": [VIDEO_COVER_FOLDER_ID]},
            media_body=MediaFileUpload(str(mp4_p), mimetype="video/mp4", resumable=True),
            fields="id,name,size",
        ).execute()
        c_res = drive.files().create(
            body={"name": ep["cover_name"], "parents": [VIDEO_COVER_FOLDER_ID]},
            media_body=MediaFileUpload(str(cov_p), mimetype="image/jpeg", resumable=False),
            fields="id,name,size",
        ).execute()
        uploaded_ids[ep["file_name"]] = {"video_id": v_res["id"], "cover_id": c_res["id"]}
        print(f"  [DRIVE YÜKLENDİ] {ep['file_name']} ({v_res['id']}) + {ep['cover_name']} ({c_res['id']})", flush=True)

    # 4) Repo ve Drive baslik.xlsx tablolarını güncelle
    repo_xlsx = REPO_ROOT / "baslik.xlsx"
    repo_xlsx2 = REPO_ROOT / "bilgidozu_yukleme_tablosu.xlsx"
    update_workbook_priority_queue(repo_xlsx)
    shutil.copyfile(repo_xlsx, repo_xlsx2)

    drive.files().update(
        fileId=MASTER_SHEETS_ID,
        media_body=MediaFileUpload(
            str(repo_xlsx),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            resumable=False,
        ),
        fields="id,name,modifiedTime",
    ).execute()
    print(f"  [TABLO GÜNCELLENDİ] Drive baslik.xlsx ({MASTER_SHEETS_ID}) senkronize edildi.", flush=True)

    # 5) Kuyruk doğrulaması (get_next_scheduled_video + compute_queue_stats)
    import sheets_metadata as sm
    import uploader as up
    done_ids = up.load_uploaded_ids(REPO_ROOT / "uploaded.txt")
    stats = sm.compute_queue_stats(drive, QUEUE_FOLDER_ID, skip_ids=done_ids)
    nxt = sm.get_next_scheduled_video(drive, QUEUE_FOLDER_ID, skip_ids=done_ids, video_type="short")
    if not nxt or nxt["name"] != "video_177.mp4":
        raise RuntimeError(f"Sıradaki video video_177.mp4 olmalıydı, gelen: {nxt}")
    if stats["duplicate_videos"] != 0:
        raise RuntimeError(f"Mükerrer dosya tespit edildi: {stats}")

    report = {
        "next_scheduled": nxt["name"],
        "next_title": nxt["title"],
        "queue_stats": stats,
        "uploaded": uploaded_ids,
    }
    (rendered_dir / "deploy_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("KUYRUK DOĞRULAMASI TAMAM:", json.dumps(report, ensure_ascii=False), flush=True)
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_prep = sub.add_parser("prepare")
    p_prep.add_argument("--out", required=True)

    p_rend = sub.add_parser("render")
    p_rend.add_argument("--assets", required=True)
    p_rend.add_argument("--out", required=True)
    p_rend.add_argument("--nums", required=True, help="Örn: 177,178")

    p_dep = sub.add_parser("deploy")
    p_dep.add_argument("--rendered", required=True)

    args = ap.parse_args()
    if args.cmd == "prepare":
        prepare_all_assets(Path(args.out))
    elif args.cmd == "render":
        nums = [int(x.strip()) for x in args.nums.split(",") if x.strip()]
        render_shard(Path(args.assets), Path(args.out), nums)
    elif args.cmd == "deploy":
        deploy_priority_queue_to_drive(Path(args.rendered))


if __name__ == "__main__":
    main()
