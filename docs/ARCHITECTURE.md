# Mimari

Akış: yapılandırılmış şirket listesi → Greenhouse/Lever/Ashby adaptörleri → Pydantic doğrulama → kural tabanlı ön eleme ve açıklanabilir puan → SQLite repository → Markdown raporu.

`source + job_id` birincil anahtardır; aynı kaynaktaki URL de benzersizdir. Bir board eksiksiz çekildikten sonra artık dönmeyen kayıtlar silinmek yerine `closed` olur. HTTP 429/5xx istekleri sınırlı exponential backoff ile yeniden denenir. Web metni komut değil güvenilmeyen veri kabul edilir.

Mantıksal agent modülleri sade Python bileşenleridir; pahalı agent framework'ü yoktur. Phase 1 yalnızca Job Hunter ve Job Matcher'ı uçtan uca etkinleştirir.

