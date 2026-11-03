#!/usr/bin/env python3
"""Altyazı gruplama — sahnedeki metni ekrana sığan parçalara böler.

Kural: satır başına en fazla 5 kelime (1080 px genişlikte taşma yapmaz),
son parça 2 kelimeden kısa kalırsa önceki gruba eklenir.
"""
from __future__ import annotations

AZAMI_KELIME = 5


def grupla(metin: str, azami: int = AZAMI_KELIME) -> list[tuple[str, list[str]]]:
    kelimeler = metin.split()
    if not kelimeler:
        return []
    gruplar: list[list[str]] = [kelimeler[i:i + azami] for i in range(0, len(kelimeler), azami)]
    if len(gruplar) > 1 and len(gruplar[-1]) < 2:
        gruplar[-2].extend(gruplar.pop())
    return [(" ".join(g), []) for g in gruplar]


if __name__ == "__main__":
    for parca in grupla("Hiçbir derdin yokken otururken göğsünün neden her beş dakikada bir iç çektiğini biliyor musun"):
        print(parca[0])
