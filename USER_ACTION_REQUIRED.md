# CareerHunter AI — Kullanıcı İşlemleri

Güncelleme: 26 Kasım 2026 (Europe/Istanbul)

## Gerekli kullanıcı işlemleri

1. **Render'daki mail worker bağlantısını yeni Neon'a geçir.** Render ortam değişkenlerinde `CAREERHUNTER_GMAIL_SEND_DATABASE_URL` alanını yeni Neon `careerhunter_live` veritabanının `careerhunter_mail_sender` rolüne ait bağlantı ile güncelle. GitHub Actions sırrı bu role güncellendi ve gerekli tablolar hazır; Render bu değişikliği almadan panelden oluşturulan onaylar eski veritabanına gidebilir. Neon [Connect](https://console.neon.tech/app/projects/hidden-fog-42701810/branches/br-autumn-cell-bb1fk9d1) ekranında Database=`careerhunter_live`, Role=`careerhunter_mail_sender` seç; bağlantı değerini gizli tut. Render [Environment](https://dashboard.render.com/web/srv-dbe3l1l9fdbs73975hog/env) sayfasında yalnızca bu değişkeni değiştir ve deploy tamamlanınca haber ver.

2. **CV yüklemesini tamamlamak için tarayıcı kontrolünü geri aç.** CV kasası artık hazır; iki PDF yerel `Downloads` klasöründe ve yeniden göndermen gerekmiyor. Brave kontrol bağlantısı bu oturumda kesildi. Codex'in Brave tarayıcı kontrolünü yeniden bağlayıp “hazır” yaz; ben [CV kasasına](https://careerhunter-private-dashboard.onrender.com/internal/owner/cv/manage) iki dosyayı yükleyip şifreli geri okumayı doğrulayacağım.

3. **NTFY topic'ini belirle.** GitHub Actions deposunda `NTFY_TOPIC` sırrı yok. NTFY raporu isteniyorsa kendi topic değerini şu [GitHub Actions secrets](https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/settings/secrets/actions) sayfasına kendin ekle; değeri sohbet veya loglarda paylaşma.

## Senden gerekmeyenler

- GitHub `DATABASE_URL` yeni Neon'a geçirildi ve gerçek tarama doğrulandı.
- Render `CAREERHUNTER_CRM_DATABASE_URL` yeni Neon'daki sınırlı `careerhunter_cv_writer` rolüne geçirildi; Render CV kasası `ready` döndü.
- CV dosyalarını tekrar göndermen gerekmiyor.
- İşverenlere otomatik başvuru ve gerçek e-posta gönderimi kapalı. Test e-postası CV yüklemesi ve şifreli geri okuma sonrası ayrıca doğrulanacak.

## Doğrulama bağlantıları

- [Render servis ortam değişkenleri](https://dashboard.render.com/web/srv-dbe3l1l9fdbs73975hog/env)
- [CareerHunter CV kasası](https://careerhunter-private-dashboard.onrender.com/internal/owner/cv/manage)
- [GitHub Actions çalıştırmaları](https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/actions)
