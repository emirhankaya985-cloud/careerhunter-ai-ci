# CareerHunter AI — Kullanıcı İşlemleri

Güncelleme: 26 Kasım 2026 (Europe/Istanbul)

## Gerekli kullanıcı işlemleri

Şu anda zorunlu kullanıcı işlemi yok. CV yükleme iptal edildi; eklenti izinlerini açman gerekmiyor.

İsteğe bağlı: NTFY bildirimi istiyorsan GitHub Actions deposuna `NTFY_TOPIC` sırrını ekle. Değeri sohbet veya loglarda paylaşma.


## Tamamlananlar

- Render `CAREERHUNTER_GMAIL_SEND_DATABASE_URL` yeni Neon mail rolüne geçirildi; deploy Live.
- GitHub Gmail ön kontrolü ve boş Telegram mail worker başarıyla tamamlandı; gönderim kapalı, 0 mesaj gönderildi.

## Senden gerekmeyenler

- GitHub `DATABASE_URL` yeni Neon'a geçirildi ve gerçek tarama doğrulandı.
- Render `CAREERHUNTER_CRM_DATABASE_URL` yeni Neon'daki sınırlı `careerhunter_cv_writer` rolüne geçirildi; Render CV kasası `ready` döndü.
- Özel GitHub Actions beceri profili CV’deki açık bilgilerle güncellendi; üretim taraması başarılı. CV dosyaları yerelde kaldı, kasaya yüklenmedi.
- İşverenlere otomatik başvuru ve gerçek e-posta gönderimi kapalı. CV yüklemesi bu iş akışının ön koşulu değil.

## Doğrulama bağlantıları

- [Render servis ortam değişkenleri](https://dashboard.render.com/web/srv-dbe3l1l9fdbs73975hog/env)
- [GitHub Actions çalıştırmaları](https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/actions)
