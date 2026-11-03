"""Bilgi Dozu: 1 Kasım 2026 kullanıcı onaylı sinematik AI sahne dili.

Bu modül tek başına görsel veya video üretmez. Sonraki batch yalnız kullanıcı
"video üret" dediğinde, konular ve kaynaklar kontrol edilerek başlatılabilir.
Sahneye sonradan uygulanan başlık/altyazı katmanlarını bu prompt belirlemez.
"""
from __future__ import annotations

REFERENCE_IMAGES = (
    "/home/user/uploads/bg_b84_dudak.jpg",
    "/home/user/uploads/bg_b70_sivrisinek.jpg",
    "/home/user/uploads/bg_b61_foto.jpg",
    "/home/user/uploads/bg_b60_ucak.jpg",
)


def build_scene_prompt(scene_description: str, *, aspect: str = "9:16") -> str:
    """Konuya özel betimleme ile yazısız, fotogerçekçi AI sahne promptu hazırlar.

    Gerçekçi insan/deri gösterimi gerektiğinde serbesttir. Stok içerik kullanılmaz;
    bilimsel doğruluk ve gerçek kişi benzerlikleri üretim kontrolünde ayrıca incelenir.
    """
    subject = str(scene_description).strip()
    if not subject:
        raise ValueError("Sahne konusu boş olamaz.")
    if aspect not in {"9:16", "16:9"}:
        raise ValueError("En-boy oranı 9:16 veya 16:9 olmalı.")
    framing = "vertical 9:16" if aspect == "9:16" else "horizontal 16:9 widescreen"
    return (
        f"{subject}. "
        "Cinematic photorealistic AI-generated scene, natural and plausible subject detail, "
        "realistic skin and people when relevant, strong clear subject, realistic textures, "
        "controlled shallow depth of field where appropriate, low-key cinematic lighting, "
        "subtle deep teal shadows and warm amber highlights, natural contrast, "
        f"{framing}, no text, no letters, no watermark, no logo, no collage or split screen. "
        "Do not reproduce an identifiable real person without permission. "
        "Avoid excessive neon, translucent holograms, cartoon styling and stock imagery."
    )
