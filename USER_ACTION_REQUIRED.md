# CareerHunter AI — Kullanıcı İşlemleri

Güncelleme: 26 Kasım 2026 (Europe/Istanbul)

## Gerekli kullanıcı işlemleri

1. **Brave dosya erişimini etkinleştir.** CV yüklemesi panelde oturum açtı, ancak Codex uzantısı yerel dosyayı seçemedi. Brave'de `brave://extensions` aç → ChatGPT/Codex uzantısında **Details** → **Allow access to file URLs** anahtarını aç. Codex paneline dönüp “hazır” yaz; PDF'ler zaten Downloads klasöründe, tekrar gönderme.

2. **Render mail worker bağlantısını yeni Neon'a geçir.** Render [Environment](https://dashboard.render.com/web/srv-dbe3l1l9fdbs73975hog/env) sayfasındaki `CAREERHUNTER_GMAIL_SEND_DATABASE_URL` yeni Neon projesindeki `careerhunter_live` ve `careerhunter_mail_sender` rolünü kullanmalı. GitHub Actions worker sırrı bu hedefte ve worker testi başarılı. Neon Connect rol menüsünde `careerhunter_mail_sender` görünmedi; bu yüzden doğru bağlantı değerini oradan doğrulayamıyorum. Rol/parola değerini tahmin etme veya buraya gönderme; Neon rol bağlantısı erişilebilir olduğunda Render'a ekleyip deploy et.

3. **NTFY topic'ini belirle (bildirim istiyorsan).** GitHub Actions deposunda `NTFY_TOPIC` sırrı yok. NTFY raporu isteniyorsa kendi topic değerini şu [GitHub Actions secrets](https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/settings/secrets/actions) sayfasına kendin ekle; değeri sohbet veya loglarda paylaşma.

## Senden gerekmeyenler

- GitHub `DATABASE_URL` yeni Neon'a geçirildi ve gerçek tarama doğrulandı.
- Render `CAREERHUNTER_CRM_DATABASE_URL` yeni Neon'daki sınırlı `careerhunter_cv_writer` rolüne geçirildi; Render CV kasası `ready` döndü.
- CV dosyalarını tekrar göndermen gerekmiyor. İngilizce ve Türkçe CV'ler yerelde mevcut.
- İşverenlere otomatik başvuru ve gerçek e-posta gönderimi kapalı. Test e-postası CV yüklemesi ve şifreli geri okuma sonrası ayrıca doğrulanacak.

## Doğrulama bağlantıları

- [Render servis ortam değişkenleri](https://dashboard.render.com/web/srv-dbe3l1l9fdbs73975hog/env)
- [CareerHunter CV kasası](https://careerhunter-private-dashboard.onrender.com/internal/owner/cv/manage)
- [GitHub Actions çalıştırmaları](https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/actions)
