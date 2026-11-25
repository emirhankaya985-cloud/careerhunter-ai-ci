# CareerHunter AI — Kullanıcı İşlemleri

Güncelleme: 26 Kasım 2026 (Europe/Istanbul)

## Gerekli kullanıcı işlemleri

CV yükleme iptal edildi; eklenti izinlerini açman gerekmiyor. CV'siz otomatik e-posta ve dil kuralları onaylandı, CI sonrası GitHub Actions'ta etkinleştirildi. Şu an doğrulanmış işveren e-posta adresi bulunmadığı için mesaj gönderilmedi.

İsteğe bağlı: NTFY bildirimi istiyorsan GitHub Actions deposuna `NTFY_TOPIC` sırrını ekle. Değeri sohbet veya loglarda paylaşma.


## Tamamlananlar

- Render `CAREERHUNTER_GMAIL_SEND_DATABASE_URL` yeni Neon mail rolüne geçirildi; deploy Live.
- GitHub Gmail ön kontrolü başarıyla tamamlandı; otomatik gönderim yalnızca onaylı kurallar ve kayıtlı alıcı sınırlarıyla açık.

## Senden gerekmeyenler

- GitHub `DATABASE_URL` yeni Neon'a geçirildi ve gerçek tarama doğrulandı.
- Render `CAREERHUNTER_CRM_DATABASE_URL` yeni Neon'daki sınırlı `careerhunter_cv_writer` rolüne geçirildi; Render CV kasası `ready` döndü.
- Özel GitHub Actions beceri profili CV’deki açık bilgilerle güncellendi; üretim taraması başarılı. CV dosyaları yerelde kaldı, kasaya yüklenmedi.
- İşverenlere otomatik başvuru ve gerçek e-posta gönderimi kapalı. CV yüklemesi bu iş akışının ön koşulu değil.

## Doğrulama bağlantıları

- [Render servis ortam değişkenleri](https://dashboard.render.com/web/srv-dbe3l1l9fdbs73975hog/env)
- [GitHub Actions çalıştırmaları](https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/actions)
