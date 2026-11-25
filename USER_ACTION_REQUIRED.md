# CareerHunter AI — Kullanıcı İşlemleri

Güncelleme: 26 Kasım 2026 (Europe/Istanbul)

## Gerekli kullanıcı işlemleri

1. **Brave dosya erişimini etkinleştir.** CV yüklemesi panelde oturum açtı, ancak Codex uzantısı yerel dosyayı seçemedi. Brave'de `brave://extensions` aç → ChatGPT/Codex uzantısında **Details** → **Allow access to file URLs** anahtarını aç. Codex paneline dönüp “hazır” yaz; PDF'ler zaten Downloads klasöründe, tekrar gönderme.

2. **NTFY bildirimini isteğe bağlı etkinleştir.** Bildirim isteniyorsa GitHub Actions deposuna `NTFY_TOPIC` sırrını kendi topic değerinle ekle. Değeri sohbet veya loglarda paylaşma.


## Tamamlananlar

- Render `CAREERHUNTER_GMAIL_SEND_DATABASE_URL` yeni Neon mail rolüne geçirildi; deploy Live.
- GitHub Gmail ön kontrolü ve boş Telegram mail worker başarıyla tamamlandı; gönderim kapalı, 0 mesaj gönderildi.

## Senden gerekmeyenler

- GitHub `DATABASE_URL` yeni Neon'a geçirildi ve gerçek tarama doğrulandı.
- Render `CAREERHUNTER_CRM_DATABASE_URL` yeni Neon'daki sınırlı `careerhunter_cv_writer` rolüne geçirildi; Render CV kasası `ready` döndü.
- CV dosyalarını tekrar göndermen gerekmiyor. İngilizce ve Türkçe CV'ler yerelde mevcut.
- İşverenlere otomatik başvuru ve gerçek e-posta gönderimi kapalı. Test e-postası CV yüklemesi ve şifreli geri okuma sonrası ayrıca doğrulanacak.

## Doğrulama bağlantıları

- [Render servis ortam değişkenleri](https://dashboard.render.com/web/srv-dbe3l1l9fdbs73975hog/env)
- [CareerHunter CV kasası](https://careerhunter-private-dashboard.onrender.com/internal/owner/cv/manage)
- [GitHub Actions çalıştırmaları](https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/actions)
