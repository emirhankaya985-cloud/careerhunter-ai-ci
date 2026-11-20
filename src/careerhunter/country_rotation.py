"""Hourly country focus and bounded discovery on verified public ATS boards.

A focus country is a search target, never evidence of actual source coverage.
Full board snapshots must be persisted before any country report filtering.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Practical research targets, not salary promises or a country quality ranking.
COUNTRIES = {
    'US': ('United States', 'USA', 'San Francisco', 'New York', 'Seattle', 'Austin', 'Boston'),
    'DE': ('Germany', 'Deutschland', 'Berlin', 'Munich', 'München', 'Hamburg'),
    'GB': ('United Kingdom', 'UK', 'London', 'Manchester'),
    'CA': ('Canada', 'Toronto', 'Vancouver', 'Montreal'),
    'CH': ('Switzerland', 'Zurich', 'Zürich', 'Geneva'),
    'NL': ('Netherlands', 'Amsterdam', 'Rotterdam'),
    'AU': ('Australia', 'Sydney', 'Melbourne'),
    'SE': ('Sweden', 'Stockholm', 'Gothenburg'),
    'DK': ('Denmark', 'Copenhagen'),
    'NO': ('Norway', 'Oslo'),
    'FI': ('Finland', 'Helsinki'),
    'IE': ('Ireland', 'Dublin'),
    'FR': ('France', 'Paris', 'Lyon'),
    'AT': ('Austria', 'Vienna', 'Wien'),
    'BE': ('Belgium', 'Brussels'),
    'LU': ('Luxembourg',),
    'SG': ('Singapore',),
    'JP': ('Japan', 'Tokyo', 'Osaka'),
    'KR': ('South Korea', 'Republic of Korea', 'Seoul'),
    'NZ': ('New Zealand', 'Auckland', 'Wellington'),
    'AE': ('United Arab Emirates', 'UAE', 'Dubai', 'Abu Dhabi'),
    'IL': ('Israel', 'Tel Aviv'),
    'TW': ('Taiwan', 'Taipei'),
    'CZ': ('Czech Republic', 'Czechia', 'Prague'),
    'PL': ('Poland', 'Warsaw', 'Krakow'),
    'EE': ('Estonia', 'Tallinn'),
    'LT': ('Lithuania', 'Vilnius'),
    'LV': ('Latvia', 'Riga'),
    'ES': ('Spain', 'Madrid', 'Barcelona'),
    'PT': ('Portugal', 'Lisbon', 'Porto'),
    'IT': ('Italy', 'Milan', 'Rome'),
    'IS': ('Iceland', 'Reykjavik'),
    'SI': ('Slovenia', 'Ljubljana'),
    'SA': ('Saudi Arabia', 'Riyadh'),
    'QA': ('Qatar', 'Doha'),
    'TR': ('Türkiye', 'Turkey', 'Istanbul', 'İstanbul', 'Ankara'),
}
FIXED = ('US', 'DE')
# All seven endpoints returned nonempty valid JSON on 2026-11-20.
# They are global boards; no country coverage is inferred from employer identity.
DISCOVERY_BOARDS = (
    ('Canonical', 'canonical'), ('Datadog', 'datadog'),
    ('Cloudflare', 'cloudflare'), ('Elastic', 'elastic'),
    ('MongoDB', 'mongodb'), ('Grafana Labs', 'grafanalabs'), ('Adyen', 'adyen'),
)


def hour_index(at: datetime) -> int:
    if at.tzinfo is None:
        raise ValueError('country rotation requires a timezone-aware datetime')
    return int(at.astimezone(timezone.utc).timestamp()) // 3600


def country_batch(at: datetime) -> tuple[str, ...]:
    rotating = tuple(code for code in COUNTRIES if code not in FIXED)
    start = hour_index(at) * 4 % len(rotating)
    return FIXED + tuple(rotating[(start + i) % len(rotating)] for i in range(4))


def discovery_companies(at: datetime) -> list[dict]:
    # Bound extra work to two boards/hour; every board is revisited within 4h.
    start = hour_index(at) * 2 % len(DISCOVERY_BOARDS)
    return [dict(name=DISCOVERY_BOARDS[(start+i) % len(DISCOVERY_BOARDS)][0],
                 greenhouse=DISCOVERY_BOARDS[(start+i) % len(DISCOVERY_BOARDS)][1])
            for i in range(2)]


def location_countries(location: str) -> set[str]:
    text = location.casefold().replace('i\u0307', 'i')
    return {code for code, aliases in COUNTRIES.items() if any(
        re.search(r'(?<!\w)' + re.escape(alias.casefold()) + r'(?!\w)', text)
        for alias in aliases)}


def rotation_report(jobs, at: datetime) -> str:
    batch = country_batch(at)
    stamp = at.astimezone(ZoneInfo('Europe/Istanbul')).strftime('%Y-%m-%d %H:%M')
    lines = [f'\n## Ülke odağı — {stamp} TRT',
             '\nABD ve Almanya sabit; diğer 34 ülke dörderli döner.',
             '36 hedefin tamamı en geç 9 saatlik kesintisiz döngüde yer alır.',
             'Saatler hedef zamandır; GitHub Actions gecikebilir.',
             '\n| Ülke | Konumu eşleşen ilan | Profil puanı ≥65, kıdemli değil |',
             '|---|---:|---:|']
    for code in batch:
        found = [j for j in jobs if code in location_countries(j.location)]
        relevant = [j for j in found if (j.match_score or 0) >= 65
                    and j.experience_level != 'senior']
        lines.append(f'| {COUNTRIES[code][0]} | {len(found)} | {len(relevant)} |')
    lines += ['\nSıfır sonuç: bu koşumdaki kaynaklarda doğrulanmış ülke konumu yok; '
              'ülkenin iş piyasası tamamen tarandı anlamına gelmez.',
              'Remote/EMEA gibi belirsiz konumlar ülkelere dağıtılmaz. '
              'Profil puanı; vize, sponsorluk, ücret veya başvuru uygunluğu kanıtı değildir.']
    return '\n'.join(lines) + '\n'
