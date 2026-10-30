# CareerHunter AI v2.0 — Codex master prompt

**Hedef:** Mevcut projeyi sıfırdan kurmadan, gerçek ilan kaynakları ve insan onaylı başvuru yönetimiyle 0 TL çalışan iş arama asistanına dönüştür.

## Depolar ve gerçek başlangıç noktası

- Ana public/sanitized CI deposu: `emirhankaya985-cloud/careerhunter-ai-ci`.
- Private kaynak referansı: `emirhankaya-AFK/careerhunter-ai`. İzinleri ve gizliliği bozma.
- Yeni geliştirme dalı: `feat/careerhunter-v2-safe-cv-20261030`.
- İlk gerçek geliştirme bu dalda mevcut: `src/careerhunter/cv_tailor.py` ve `tests/test_cv_tailor.py`. Önce bunları denetle, test et ve geliştir; aynısını yeniden yazma.
- Python 3.11+, Pydantic, SQLAlchemy, HTTPX, Ruff, pytest, Greenhouse/Lever/Ashby adaptörleri, CRM, kişi araştırması, kalite filtresi, owner-only panel ve Telegram altyapısı zaten var.
- Günlük 09:17 Europe/Istanbul GitHub OIDC -> Render taraması korunmalı. Production kodunun yayımlanması, CI başarısından ayrıdır.
- `config/profile.yaml` sadece PUBLIC SAMPLE'dır. Gerçek profil gizli `CAREERHUNTER_PROFILE_JSON` veya eşdeğer özel depoda tutulmalı.
- README'de Render Free PostgreSQL için 23.11.2026 son tarihi var. Neon Free geçiş taslağı PR #1 AÇIK ve henüz üretime taşınmış sayılmıyor.

## Kırmızı çizgiler

1. **0 TL:** ücretli API, kredi kartı, plan yükseltme yok. Bedava kotaları ayrı ayrı doğrula; servis süre sonu ve uyuma risklerini raporla. LLM yoksa deterministic fallback çalışmalı.
2. **Gerçeklik:** CV'ye kullanıcının doğrulamadığı beceri, iş, unvan, proje, üniversite, tarih, sonuç veya deneyim yazma. ATS uyumlu biçim, ATS'yi geçme garantisi değildir.
3. **Kaynak:** ATS'de bulunan ilanı “şirket kariyer sayfasından ikinci kaynakla doğrulandı” diye işaretleme. Gerçek resmi kaynak URL'si, job_id, observed_at ve HTTP sonucu ayrı tutulmalı; network hatası “sahte ilan” demek değildir.
4. **Yetki:** LinkedIn bağlantı, mesaj, Gmail gönderimi, iş başvurusu, CV yükleme ve dış sistemde yazma kullanıcı onayı olmadan gerçekleşmeyecek. CAPTCHA/rate-limit aşma veya gizli veri scraping yok.
5. **Gizlilik:** kişisel CV, profil, gönderilen mesajlar, iletişim bilgileri, tokenlar, Gmail/LinkedIn oturumları, üretim verisi ve secrets public repoya asla yazılmaz. Mock/test verileri kurgusal olmalı.
6. **Kanıt:** unit test PASS, GitHub CI PASS, deploy PASS, canlı DB PASS, gerçek schedule PASS ve Telegram kabul/teslimi ayrı sonuçlardır; eksik bilgi “UNKNOWN” olarak raporlanır.

## Faz A — HEMEN BAŞLA (ilk PR)

1. README, docs/MATCHING_QUALITY.md, docs/ROADMAP.md, modeller, mevcut testler, workflows ve DB yapısını incele. En son commit SHA'sını ve kapsamı raporla.
2. Bu daldaki offline CV modülünü koru. Her ilanın title/description verisini kullanarak yalnızca özel profilde gerçekten mevcut becerileri önceliklendir; deneyim/proje/eğitim alanlarını kaynak olgular olarak aktar, uydurma ekleme.
3. Yerel JSON profil + ilan JSON girişinden tek sütunlu, gerçek metin içeren Markdown taslağı üret. Özel profil için gerçek içerikli fixture oluşturma. Yanlış JSON, eksik alanlar, keyword sınırları, çoklu dil, açık dosya yolu ve dosya adı hatalarını düzgün ele al.
4. Her ilan için eşleşen beceriler, eksik kanıtlar ve taslak durumunu owner-only panelde veya CLI'de göster. Kullanıcı denetimi olmadan CV göndermeyi yasakla.
5. PDF/DOCX dışa aktarma ancak gerçekten test edilmişse etkinleştir. Ayrı düzenlenebilir CV şablonlarını ileriki PR'ye bırakabilirsin.
6. Yerelde `python -m pip install -e '.[dev]'`, `ruff check .`, `pytest -q` çalıştır. Hata varsa gider, CI kanıtı olmadan merge etme. Farklı risk düzeyindeki değişiklikler için ayrı küçük PR aç.

## Faz B — İlanın gerçekliği

- Her ilan için `(source, source_job_id, company, title, official_feed_url, job_url, observed_at, retrieval_status)` kanıtı tut.
- Statüler: `ATS_LISTED`, `EMPLOYER_CONFIRMED`, `REVIEW_REQUIRED`, `NOT_FOUND_AT_LAST_CHECK`, `SOURCE_ERROR`, `CLOSED_CONFIRMED`. Son ikisini yanlış eşleştirme: timeout/403/429 = `SOURCE_ERROR`.
- Güvenilir şirket kariyer URL'si varsa ikinci kaynak doğrulaması yap; aynı ilanın aggregator kopyası ikinci bağımsız kanıt değildir. İlanlar kapanırsa tarihle ve kaynağıyla güncelle.
- Ülke/çalışma izni bilinmiyorsa `needs_review`, global remote ≠ Türkiye'den yasal çalışma izni.
- 0 yeni ilan ama başarılı kaynak okuma ayrı; tüm kaynaklar hata verdiyse FAIL.

## Faz C — Doğrulanabilir kişi araştırması

- Kamuya açık ve izinli kaynaklardan işe alım bağlantılarını araştır, link/tarih/kanıt tut.
- “company_employee” bilgisinden işe alım yöneticisi sonucunu çıkarma; açık kanıt yoksa `unknown`.
- TR/EN kısa, gerçek bağlama dayalı mesaj taslağı üret, otomatik göndermeyi kapalı tut.

## Faz D — Başvuru CRM + yanıt takibi

- İlan, şirket, CV sürümü, kaynak, başvuru tarihi, durum, yanıt, mülakat ve follow-up kayıtlarını idempotent işle.
- Gmail yalnızca açık bağlantı ve en az yetkiyle; tercihen ayrı başvuru posta kutusu. Sınıflandırma insan kontrolünde. Otomatik mail yollama kapalı.
- Mülakat/ret/dönüş gelişmelerini yalnızca kanıta dayalı olarak Telegram'da raporla; tekrar mesaj önleme ve gizli veriyi loglarda maskeleme.
- LinkedIn ve Workday form yardımı yalnızca kullanıcı kontrollü tarayıcı oturumunda; gönderim kanıtı yoksa “başvuruldu” yazma.

## Faz E — 0 TL işletim ve doğrulama

- Var olan owner dashboard'a resmi kaynak kanıtı, uygunluk belirsizliği, CV taslakları, takip tarihleri, bildirim/daily run sağlığı ekle.
- Ayrı açık Neon migration PR'sını çakıştırma. Önce yedek/geri yükleme, TLS, tablo şeması, ücretsiz limit, rollback testleri. Üretim DB değişikliği için kullanıcı onayı al.
- Güvenlik ve test regresyonlarını çalıştır; yeni bağımlılıkları asgari tut.

## Kabul ve çıktı formatı

İlk PR için: kod + testler + kullanım kılavuzu + local test sonuçları + gerçek CI run bağlantısı. Her faz için: değişen dosyalar, commit SHA, PR, test sayısı, kaynağın gerçekliği, production deploy kanıtı ve blokajlar. Kontrol edilmeyen adımları başarı gibi gösterme.

**Hemen Faz A'da kodlamaya devam et. Rutin kararları kendin çöz; ana dala merge, üretim DB taşınması ve dışarı mesaj/başvuru gönderimini kullanıcı onayına bırak.**
