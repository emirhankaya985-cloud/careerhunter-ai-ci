# CareerHunter AI v2 — güvenli işletim kılavuzu

Bu dalda çalışan ilk v2 özellikleri: ATS kaynak kanıtı, özel CV taslağı, kullanıcı onaylı
manuel başvuru kaydı ve 7 günlük takip. Bunlar **otomatik başvuru** değildir.
Özel Render panelinde başvuru/takip ekranı ve ilan kanıt durumu **salt okunur** sunulur.

## Kurulum ve güvenlik

- Python 3.11+, `python -m pip install -e '.[dev]'`.
- Yerel SQLite dosyası **mevcut** olmalı. Test için `careerhunter run --slot jobs`
  ancak gerçek ATS ve doğru profili kullanarak oluşturur; yanlış profille tarama yapma.
- Prod PostgreSQL verisi otomatik dışa aktarılmaz; yetkili bir export gerekiyorsa
  güvenli, şifreli özel yedek üzerinden ilerle.
- Aşağıdaki `--profile`, `--output`, `--cv-file` dosyaları **public deponun
  dışında**, özel yerel klasörde tutulmalıdır. Gerçek ad, iletişim veya CV
  bilgilerini GitHub'a commit etme.
- Profil JSON yalnızca doğrulanmış beceriler, eğitim, proje ve deneyim alanlarından
  oluşmalı. `config/profile.yaml` demo verisidir.

### 1. İlanı tekrar kontrol et

```powershell
python -m careerhunter.v2_workflow --db "C:\private\careerhunter.db" verify --source ashby --job-id "GERCEK_JOB_ID"
```

Çıktı JSON kanıtı ve kaydedilen durum: `ATS_LISTED`,
`NOT_FOUND_AT_LAST_CHECK`, `SOURCE_ERROR` ya da `REVIEW_REQUIRED`.
`ATS_LISTED` = yapılandırılan *aynı* ATS kaynağında job_id yeniden görüldü.
**İşveren kariyer sitesinde bağımsız doğrulama değildir.** Son kontrolde
bulunmayan ilan veya zaman aşımı “sahte ilan” anlamına gelmez.
Veritabanı içindeki `verification_observed_at` ve URL kanıtını kontrol et.
Program `ATS_LISTED` dışındaki durumlarda sıfırdan farklı çıkış kodu verir.

İşverenin yapılandırılmış kariyer sayfasında aynı ATS ilanına doğrudan
link bulunup bulunmadığını ayrıca kontrol etmek için isteğe bağlı:

```powershell
python -m careerhunter.v2_workflow --db "C:\\private\\careerhunter.db" verify --source ashby --job-id "GERCEK_JOB_ID" --employer-check
```

Bu ikinci kontrol yalnızca GitHub'da önceden yapılandırılmış `team_url`
sayfasından en fazla 500 KB HTML okur; JS çalıştırmaz veya redirect takip etmez.
İlanda birebir aynı URL'ye doğrudan `<a href>` bağlantısı bulunursa
`EMPLOYER_CONFIRMED` kaydı tutulur. JS tabanlı sayfa, olmayan link veya ağ
hatası sahte ilan kanıtı sayılmaz; `ATS_LISTED` korunur.
Günlük otomatik tarama henüz bu isteğe bağlı işlemi yapmaz.

### 2. Her ilana gerçek bilgilere dayalı taslak

Özel JSON dosyasında `name`, `skills` listesi; tercihen `experience`,
`projects`, `education`, `languages` alanları bulunur. Örnek isimler
ve deneyimler yalnızca testlerde kullanılmalı.

```powershell
python -m careerhunter.v2_workflow --db "C:\private\careerhunter.db" cv --source ashby --job-id "GERCEK_JOB_ID" --profile "C:\private\profile.json" --output "C:\private\cv-job42.md"
```

CV tek sütunlu Markdown olarak oluşturulur; gerçek PDF/DOCX aktarımı bu aşamada
yok. Kod, ilan açıklamasındaki eksik becerileri kullanıcıya eklemez.
Bir ATS'nin belgeyi kabul edeceği garanti değildir.

### 3. Gerçekte yaptığın başvuruyu kaydet

Sadece *inceledim* için:

```powershell
python -m careerhunter.v2_workflow --db "C:\private\careerhunter.db" track --source ashby --job-id "GERCEK_JOB_ID" --status reviewed
```

İlgili işverenin sisteminde başvuruyu **gerçekten gönderdiysen**:

```powershell
python -m careerhunter.v2_workflow --db "C:\private\careerhunter.db" track --source ashby --job-id "GERCEK_JOB_ID" --status applied --confirm-manual-event --cv-file "C:\private\cv-job42.md"
```

Bu işlem kimseye CV veya mesaj göndermez. CV içeriği değil SHA-256 özeti,
manuel başvuru tarihi ve 7 günlük takip saklanır. Aynı işlem tekrarlandığında
tarih / takip kaydı çoğaltılmaz. Diğer olaylar `interview`, `offer`,
`rejected`, `closed` için de `--confirm-manual-event` gerekir.
`--proof-url` kamuya açık olmayan hassas link içerebilir; gerektiğinde boş bırak.

Kayıtları yerelde gör:

```powershell
python -m careerhunter.v2_workflow --db "C:\private\careerhunter.db" list
```

## Canlı üretim kabul ölçütleri

1. `ruff check .`, `pytest -q`, disposable PostgreSQL CI job'u: PASS.
2. Önce backup/restore, bağlantı izinleri, free-tier süre ve quota denetimi;
   açık Neon migration PR #1'i bağımsız değerlendir.
3. Merge sonrası Render gerçekten aynı commit'i dağıtmış olmalı. Yalnızca
   GitHub CI PASS olması deployment değildir.
4. `/readyz` canlı DB tablolarını sorgulayabilmeli; güvenli login sonrası
   `/?view=jobs` kaynak kanıtı ve `/?view=applications` CRM durumlarını göstermeli.
5. Günlük 09:17 TRT tarama gerçek ATS kayıtları işlemeli. Telegram test mesajı
   kabulü ile sahibin telefonu üzerinde teslim ayrı kanıtlandırılmalı.
6. Gmail ve LinkedIn bağlantısı bu PR kapsamında **yoktur**. Gerçek mesaj
   veya otomatik başvuru gönderme bu projede kapalıdır.

**Önemli:** Dashboard read-only PostgreSQL bağlantısı CRM'e yazamaz. Yukarıdaki
`v2_workflow` CLI mevcut aşamada yalnızca yerel SQLite üzerindeki kayıtları
yönetir. Canlı CRM yazma yetkisi için kimlik doğrulamalı, CSRF korumalı, düşük
yetkili özel API ayrı güvenlik incelemesi ve kullanıcı onayı gerektirir.
