# CareerHunter — Sahibe Özel Web Paneli

Bu panel **halka açık bir iş ilanı sitesi değildir**. Uygulamaya giriş için uzun bir şifre gerekir; Supabase/PG verileri yalnızca sunucuda sorgulanır ve istemciye oturum açmadan gönderilmez. Sadece okuma işlevi sunar; hiçbir kişiye otomatik mesaj göndermez.

## Ekranlar

- **Genel Bakış:** Tüm veritabanındaki ilanlar, son 24 saatlik yeniler, kişi/taslak sayıları, dört ülke özeti, son işlem durumu.
- **İlanlar:** SQL ile sayfalı (40 ilan) ve şirket/başlık/lokasyon aramalı liste.
- **Kişiler ve Taslaklar:** Kaynak linkleri, varsa doğrulanmış e-posta/LinkedIn ve İngilizce/Türkçe mesaj taslakları. Bu kayıtlar **gönderilmiş mesaj değildir**.
- **Telefon ve PC:** Mobil uyumlu tasarım. GitHub otomasyonu aynı şekilde bağımsız devam eder.

## Önerilen: Render üzerine kurulum

1. [Render](https://dashboard.render.com/) hesabını aç. GitHub bağlantısına **özel `emirhankaya-AFK/careerhunter-ai` repository'si için** izin ver. Repo'yu public yapma.
2. Render > **New > Blueprint** üzerinden bu projeyi seç. Repo kökündeki `render.yaml` otomatik tanınır. Servis `careerhunter-private-dashboard` olarak ücretsiz planda oluşturulur.
3. İlk kurulumda aşağıdaki iki **secret** değerini Render paneline kendin gir (sohbete yazma):
   - `DASHBOARD_PASSWORD`: başka hesaplarında kullanmadığın **16 karakterden uzun** güçlü bir şifre. Tercihen parola yöneticisiyle oluştur.
   - `DASHBOARD_DATABASE_URL`: Supabase'e erişen PostgreSQL bağlantısı. **Önerilen: sadece SELECT yetkili kullanıcı**, aşağıdaki yetki notuna bak.
4. `DASHBOARD_SESSION_SECRET` 256-bit rastgele Render secret olarak otomatik üretilir. `DASHBOARD_SECURE_COOKIE=true` hazırdır.
5. Dağıtım başarılı olunca Render'ın verdiği `https://...onrender.com` adresini aç, şifreyle gir. **Bu URL'yi şu an henüz oluşturmadık; Render hesabında servis başlatılması gerekir.**
6. GitHub'ın 09.00 ilan toplama ve 09.15 raporlama akışları değişmez; panel aynı PostgreSQL verilerini okur. Sonradan kayıtlar otomatik görünür.

Render Free web hizmetleri 15 dakika boşta kalınca uyuyabilir ve ilk istek yavaş açılabilir. Ücretsiz kullanım sınırlarına tabidir. Render'ın ücretsiz PostgreSQL'ini kurmayın: **var olan Supabase verisini koruyun.**

## Veritabanı yetkisi (önerilen)

Panel yalnızca `public.jobs`, `public.contacts` ve `public.runs` tablolarını okur. `DASHBOARD_DATABASE_URL` zorunludur, ana botun `DATABASE_URL` değişkenine geri dönüş yoktur. Supabase tarafında, ayrı bir rol kullanabiliyorsan, yöneticinin güvenli SQL arayüzünde şu yetkileri tanımlayabilirsin. Gerçek parolayı SQL dosyasına veya sohbete kopyalama:

```sql
-- A dedicated login role (use a strong generated password, not the placeholder)
CREATE ROLE careerhunter_viewer LOGIN PASSWORD '<UNIQUE-STRONG-PASSWORD>';
GRANT CONNECT ON DATABASE postgres TO careerhunter_viewer;
GRANT USAGE ON SCHEMA public TO careerhunter_viewer;
GRANT SELECT ON TABLE public.jobs, public.contacts, public.runs TO careerhunter_viewer;
```

İşlem öncesinde Supabase proje adını, bağlantı/SSL ayarlarını ve RLS kurallarını kontrol et. Bu rolün **INSERT, UPDATE, DELETE, CREATE, DROP** gibi hakları olmamalı. Yönetilen Supabase pooler ile uyumlu doğru bağlantı URI'sini kullan. Var olan toplama botunun `DATABASE_URL` anahtarını değiştirme. Bu paneldeki `DASHBOARD_DATABASE_URL` **Render tarafında ayrı** saklanmalıdır.

## Bilgisayarda yerel geliştirme

```powershell
pip install -e ".[web,dev]"
$env:DASHBOARD_DATABASE_URL="postgresql+psycopg://..."
$env:DASHBOARD_PASSWORD="<strong-password>"
$env:DASHBOARD_SESSION_SECRET="<random-32-plus-chars>"
$env:DASHBOARD_SECURE_COOKIE="false"
uvicorn careerhunter.private_site:app --host 127.0.0.1 --port 8765
```

Tarayıcı: `http://127.0.0.1:8765/`. Yerelde HTTP yalnızca `127.0.0.1` adresine bağlanmalı. İnternete açılan sürümde `DASHBOARD_SECURE_COOKIE=true` zorunludur.

## Güvenlik özellikleri ve sınırlamalar

- Sunucu **kullanıcı adı/şifre veya oturum sırrı olmadan başlatılamaz**, örnek varsayılan şifre yoktur.
- 12 saatlik imzalı, HttpOnly, Secure, SameSite=Strict oturum çerezi; erişim olmayan istekler yönlendirilir. Şifre veya oturum sırrı değişince önceki oturum geçersizleşir.
- Kişiler ve taslaklar HTML-escaped (XSS önlemi), `no-store` önbellek başlığı, CSP, robots engeli.
- Şifre denemelerine tek süreçte IP başına sınırlama vardır. Render yeniden başlatılırsa sayaç sıfırlanır; **bu tam bir DDoS veya dağıtık brute-force koruması değildir**. Üretimde Cloudflare Access/MFA gibi ek kimlik doğrulama katmanı önerilir.
- Mesajları görüntüleme dışında dışarı mesaj gönderme ve kişi durumlarını değiştirme özelliği yoktur.
- Tasarım raporları veritabanından her sayfada okur. Büyük ileriki veri hacminde caching ve kişi sayfalaması eklemek gerekir.
- Web panelinin site kodu GitHub'a yüklense bile **gerçek Render dağıtımı, giriş denemesi ve cihaz testi ayrıca doğrulanmalıdır**. Secretlar bu GitHub deposuna yazılmaz.

## Son kurulum kontrolü (20 Ekim 2026)

- Render web servisi henüz oluşturulup canlı URL doğrulanmadıysa bu repo yayında sayılmaz. GitHub'da private repo olarak kalmalıdır.
- Render > New Web Service: careerhunter-ai, main, Free, Frankfurt. Build `pip install -e '.[web]'`; Start `uvicorn careerhunter.private_site:app --host 0.0.0.0 --port $PORT`.
- Render Env: `DASHBOARD_DATABASE_URL` (yalnızca SELECT yetkili PostgreSQL rolü), `DASHBOARD_PASSWORD` (16+ güçlü karakter), `DASHBOARD_SESSION_SECRET` (32+ rastgele karakter), `DASHBOARD_SECURE_COOKIE=true`. Değerleri sohbete veya GitHub'a yazma.
- `postgres://` ve `postgresql://` URL'leri psycopg3 ile açılacak şekilde normalize edilir. Panel, ana botun yazma yetkili `DATABASE_URL` bağlantısına düşmez.
- SQLite ancak açıkça `DASHBOARD_ALLOW_SQLITE_TEST=true` ile testte kullanılabilir. Render'da etkinleştirilmemelidir.
- Render sağlık kontrolü `/readyz`: PostgreSQL'in jobs, contacts ve runs tablolarını okuyamazsa 503 döner. `/healthz` yalnızca işlem canlılığını ölçer.
- 200 `/readyz`, girişsiz panellerin kapalı olması, şifreli login, ilan/kişi verilerinin görünmesi ve Render deploy başarısı ayrı ayrı doğrulanmalıdır.
- Render hesabında repo görünse dahi API üzerinden `invalid or unfetchable` uyarısı çıkabilir. Proje manuel oluşturulduğunda yeni service ID, deploy ID ve URL ile doğrulanmalıdır.
- Mevcut GitHub günlük ilan toplama otomasyonunu Render'da tekrar başlatmayın; Render sadece okuma panelidir.
