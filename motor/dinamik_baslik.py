"""Bilgi Dozu Shorts: konuşmanın bölümlerine bağlı iki satırlık üst başlıklar.

Bu dosya video, ses, altyazı, görsel veya yayın üretmez. Var olan bir renderer,
kelime-ses hizalamasını doğruladıktan sonra bu modülü çağırabilir. Başlık
metinleri editöryal olarak gerçek anlatımdan hazırlanır; zamanları karakter
sayısına göre tahmin edilmez. Eksik/uyuşmayan veride sessizce geri dönülmez.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
import unicodedata
from typing import Any, Callable, Mapping, Sequence


class BaslikHatasi(ValueError):
    """Başlık planı, gerçek ses hizalaması veya düzen güvenli değil."""


def turkce_buyut(metin: str) -> str:
    return metin.replace("i", "İ").replace("ı", "I").upper()


def _karsilastirma(metin: str) -> str:
    # İ/i ve I/ı farkı konuşma eşleştirmesinde normalize edilir; görünen metin değişmez.
    s = unicodedata.normalize("NFKD", metin.casefold().replace("ı", "i"))
    return "".join(c for c in s if c.isalnum() and unicodedata.category(c) != "Mn")


def _sayi(deger: Any, ad: str) -> float:
    if isinstance(deger, bool):
        raise BaslikHatasi(f"{ad} sayısal olmalı")
    try:
        sonuc = float(deger)
    except (TypeError, ValueError) as exc:
        raise BaslikHatasi(f"{ad} sayısal olmalı") from exc
    if not isfinite(sonuc):
        raise BaslikHatasi(f"{ad} sonlu olmalı")
    return sonuc


def _satir(deger: Any, ad: str) -> str:
    if not isinstance(deger, str) or not deger.strip():
        raise BaslikHatasi(f"{ad} boş bırakılamaz")
    if "\n" in deger or "\r" in deger or "~" in deger:
        raise BaslikHatasi(f"{ad} tek bir düz metin satırı olmalı")
    metin = " ".join(deger.split())
    if len(metin) > 60:
        raise BaslikHatasi(f"{ad} çok uzun; başlığı kısalt")
    return turkce_buyut(metin)


def _kontrol_boyutu(line1: str, line2: str, font_path: str | Path,
                     width: int, min_font_size: int) -> None:
    """Gerçek fontla minimum okunabilir puntoya sığmayı kontrol eder."""
    try:
        from PIL import ImageFont
        font = ImageFont.truetype(str(font_path), min_font_size)
    except Exception as exc:
        raise BaslikHatasi("Başlık fontu okunamadı; font olmadan üretime geçilmez") from exc
    # Onaylı Shorts yerleşimindeki emoji + kenar payı; mevcut renderer'la eşleşir.
    available_1, available_2 = width - 140 - (56 + 18), width - 140
    for text, space, label in ((line1, available_1, "Üst satır"),
                               (line2, available_2, "Alt satır")):
        bbox = font.getbbox(text)
        if bbox[2] - bbox[0] > space:
            raise BaslikHatasi(f"{label} güvenli genişliğe sığmıyor; metni kısalt")


@dataclass(frozen=True)
class Baslik:
    baslangic: float
    bitis: float
    satir1: str
    satir2: str
    emoji: str
    tetik_sozu: str
    sahne_index: int
    kelime_index: int


@dataclass(frozen=True)
class BaslikAkisi:
    basliklar: tuple[Baslik, ...]
    sure: float
    gecis: float = 0.25

    def durum(self, zaman: float) -> tuple[int, Baslik, float] | None:
        """Zamana karşılık etkin başlık ve opaklık. Ses/altyazı ile ilgilenmez."""
        t = _sayi(zaman, "Kare zamanı")
        if t < 0 or t >= self.sure:
            return None
        idx = bisect_right([b.baslangic for b in self.basliklar], t) - 1
        if idx < 0:
            return None
        event = self.basliklar[idx]
        if not (event.baslangic <= t < event.bitis):
            return None
        alpha = min(1.0, max(0.0, (t - event.baslangic) / self.gecis),
                    max(0.0, (event.bitis - t) / self.gecis))
        return idx, event, alpha


def olustur(
    sahne_zamanlari: Sequence[Mapping[str, Any]],
    sahneler: Sequence[Mapping[str, Any]],
    hizalamalar: Sequence[Mapping[str, Any]],
    toplam_sure: float,
    *,
    hizalamayi_dogrula: Callable[..., Any],
    font_yolu: str | Path,
    genislik: int = 1080,
    en_kisa_baslik_suresi: float = 1.2,
    gecis: float = 0.25,
) -> BaslikAkisi:
    """Sesin doğrulanmış kelime başlangıçlarından başlık zaman çizelgesi kur.

    Her sahne sıfır veya daha fazla ``ust_basliklar`` taşır. İlk sahnenin ilk
    başlığı, ilk kelimeye (kelime_index=0) bağlanır ve video başında görünmeye
    başlar. Sonrakiler tam olarak işaretlenmiş kelimenin ses başlangıcına
    bağlanır; görsel sahne değişiminden bağımsızdır. Önceki başlık, sonraki
    konuşma işaretine kadar korunur.

    Bir plan öğesi: ``{"kelime_index": 3, "tetik_sozu": "Yüzey molekülleri",
    "satir1": "YÜZEYDE NE VAR?", "satir2": "HAREKETLİ MOLEKÜLLER", "emoji": "🧊"}``
    Tetik sözü aynı index'teki hizalanmış sözcüklerle birebir eşleşmelidir.
    """
    if not callable(hizalamayi_dogrula):
        raise BaslikHatasi("Gerçek sesi doğrulayan hizalama denetimi zorunlu")
    if not isinstance(genislik, int) or genislik != 1080:
        raise BaslikHatasi("Bu modül yalnız 1080 px genişliğindeki Shorts içindir")
    sure = _sayi(toplam_sure, "Toplam süre")
    min_sure = _sayi(en_kisa_baslik_suresi, "En kısa başlık süresi")
    fade = _sayi(gecis, "Geçiş süresi")
    if sure <= 0 or min_sure <= 0 or fade <= 0 or min_sure < 2 * fade:
        raise BaslikHatasi("Süre veya geçiş değerleri geçersiz")
    if not sahneler or len(sahne_zamanlari) != len(sahneler) or len(hizalamalar) != len(sahneler):
        raise BaslikHatasi("Her sahnenin zamanı ve ses hizalaması zorunlu")

    adaylar: list[dict[str, Any]] = []
    onceki_bitis = 0.0
    for si, (sm, sahne, alignment) in enumerate(zip(sahne_zamanlari, sahneler, hizalamalar)):
        try:
            sahne_s = _sayi(sm["scene_start"], "Sahne başlangıcı")
            sahne_e = _sayi(sm["scene_end"], "Sahne bitişi")
            ses_s = _sayi(sm["vo_start"], "Ses başlangıcı")
            ses_e = _sayi(sm["vo_end"], "Ses bitişi")
            ses_suresi = _sayi(sm["vo_dur"], "Ses süresi")
            ses_dosyasi = sm["vo_file"]
            subs = sahne["subs"]
            kelimeler = alignment["words"]
        except (KeyError, TypeError) as exc:
            raise BaslikHatasi(f"{si + 1}. sahnede ses veya hizalama bilgisi eksik") from exc
        if (not (sahne_s <= ses_s < ses_e <= sahne_e) or
                abs((ses_e - ses_s) - ses_suresi) > 0.011 or
                abs(sahne_s - onceki_bitis) > 0.021):
            raise BaslikHatasi(f"{si + 1}. sahnenin zamanları tutarlı değil")
        if not isinstance(ses_dosyasi, (str, Path)) or not Path(ses_dosyasi).is_file():
            raise BaslikHatasi(f"{si + 1}. sahnenin gerçek ses dosyası yok")
        # Bu denetim, konuşma metnini ve sesin SHA-256 özetini de doğrular.
        try:
            hizalamayi_dogrula(subs, alignment, ses_suresi, ses_dosyasi)
        except Exception as exc:
            raise BaslikHatasi(f"{si + 1}. sahnenin ses/kelime hizalaması doğrulanamadı: {exc}") from exc
        if not isinstance(kelimeler, list) or not kelimeler:
            raise BaslikHatasi(f"{si + 1}. sahnede hizalı sözcük yok")
        plan = sahne.get("ust_basliklar", [])
        if not isinstance(plan, list):
            raise BaslikHatasi(f"{si + 1}. sahnenin üst başlık planı liste olmalı")
        if si == 0 and not plan:
            raise BaslikHatasi("İlk sahnenin ilk kelimesine bağlı bir üst başlık zorunlu")
        prev_index = -1
        for item in plan:
            if not isinstance(item, Mapping):
                raise BaslikHatasi("Başlık planındaki her kayıt nesne olmalı")
            ix = item.get("kelime_index")
            if isinstance(ix, bool) or not isinstance(ix, int) or not 0 <= ix < len(kelimeler) or ix <= prev_index:
                raise BaslikHatasi("Başlık kelime index'leri sahnede geçerli ve artan olmalı")
            prev_index = ix
            trigger = item.get("tetik_sozu")
            if not isinstance(trigger, str) or not trigger.strip():
                raise BaslikHatasi("Hangi gerçek sözde değişeceği (tetik_sozu) zorunlu")
            trigger_words = trigger.strip().split()
            aligned = kelimeler[ix:ix + len(trigger_words)]
            if (len(aligned) != len(trigger_words) or
                any(_karsilastirma(a.get("word", "")) != _karsilastirma(b)
                    for a, b in zip(aligned, trigger_words))):
                raise BaslikHatasi(f"Tetik sözü, hizalanmış konuşma ile uyuşmuyor: {trigger}")
            l1 = _satir(item.get("satir1"), "Üst satır")
            l2 = _satir(item.get("satir2"), "Alt satır")
            if any(cagri in _karsilastirma(l1 + " " + l2) for cagri in ("takipet", "aboneol")):
                raise BaslikHatasi("Eski takip/abone çağrısı üst başlığa geri eklenemez")
            icon = item.get("emoji")
            if not isinstance(icon, str) or not icon.strip() or len(icon) > 12 or any(c.isspace() for c in icon):
                raise BaslikHatasi("Konuya uygun tek bir emoji zorunlu")
            _kontrol_boyutu(l1, l2, font_yolu, genislik, min_font_size=42)
            k_start = _sayi(kelimeler[ix].get("start"), "Hizalı kelime başlangıcı")
            if k_start < 0 or k_start > ses_suresi:
                raise BaslikHatasi("Tetik kelimesinin zamanı ses süresi dışında")
            if si == 0 and not adaylar:
                if ix != 0:
                    raise BaslikHatasi("İlk başlık ilk sözcüğe bağlı olmalı")
                event_s = sahne_s
            else:
                event_s = ses_s + k_start
            adaylar.append(dict(baslangic=event_s, satir1=l1, satir2=l2, emoji=icon,
                                tetik_sozu=trigger.strip(), sahne_index=si, kelime_index=ix))
        onceki_bitis = sahne_e
    if abs(onceki_bitis - sure) > 0.021:
        raise BaslikHatasi("Toplam süre ile son sahne bitişi farklı")
    if len(adaylar) < 2 or len({(a["satir1"], a["satir2"]) for a in adaylar}) < 2:
        raise BaslikHatasi("Yeni Shorts için en az iki farklı, konuşmaya bağlı üst başlık gerekli")
    basliklar = []
    for i, a in enumerate(adaylar):
        end = adaylar[i + 1]["baslangic"] if i + 1 < len(adaylar) else sure
        if end - a["baslangic"] < min_sure:
            raise BaslikHatasi("Başlıklar çok sık değişiyor veya ters sıralı; okunabilir süre bırak")
        basliklar.append(Baslik(bitis=end, **a))
    return BaslikAkisi(tuple(basliklar), sure, fade)


@dataclass(frozen=True)
class HazirBaslikKatmani:
    akis: BaslikAkisi
    paketler: tuple[Any, ...]


def katmanlari_hazirla(akis: BaslikAkisi, *,
                       baslik_bandi: Callable[..., Any],
                       paketle: Callable[..., Any],
                       genislik: int = 1080) -> HazirBaslikKatmani:
    """Renderer'ın var olan şeffaf başlık katmanlarını bir kez oluşturur."""
    if genislik != 1080:
        raise BaslikHatasi("Yalnız Shorts başlık yerleşimi desteklenir")
    layers = tuple(paketle(baslik_bandi(genislik, b.emoji, b.satir1, b.satir2, is_wide=False))
                   for b in akis.basliklar)
    return HazirBaslikKatmani(akis, layers)


def kareye_uygula(kare: Any, zaman: float, katman: HazirBaslikKatmani, *,
                  karistir: Callable[..., Any], y: int = 155) -> bool:
    """Yalnız üst başlık katmanını çizer; ses, sahne ve altyazıya dokunmaz."""
    state = katman.akis.durum(zaman)
    if state is None:
        return False
    index, _, opacity = state
    if opacity > 0:
        karistir(kare, y, katman.paketler[index], opacity)
    return True
