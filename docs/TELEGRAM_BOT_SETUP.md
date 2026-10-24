# CareerHunter AI — Telegram bot kurulumu (0 TL)

**Botun görünen adı:** CareerHunter AI | Kariyer Alarmı

**Önerilen kullanıcı adı:** `CareerHunterEmirhanBot`
(BotFather dolu derse: `CareerHunterEmirhan_AI_Bot` veya `CareerHunterKariyerEmirBot`.)

**BotFather About:** 🎯 Python, yapay zekâ ve remote iş ilanları için kişisel kariyer bildirimleri.

**BotFather Description:**
🎯 CareerHunter AI, kariyer hedefine göre iş ilanlarını puanlar.
🐍 Python, AI/ML, Backend, Automation ve junior fırsatlar.
🌍 Türkiye, ABD, İngiltere, Avustralya.
🔔 Yalnızca yeni ve güçlü eşleşmeler; tek günlük özet, en fazla 3 ilan.
🔐 İş başvurusu göndermez. Çalışma izni ve sponsorluk mutlaka doğrulanmalıdır.

## Bağlantı adımları

1. Resmi [@BotFather](https://t.me/BotFather) hesabını aç. `/newbot` komutunu çalıştır,
   görünen ad ve kullanıcı adını yukarıdaki gibi gir. Ad uygun değilse alternatif seç.
2. BotFather sana yeni bir **token** verir. Sohbete veya GitHub'a gönderme.
   [Render servisinin Environment ekranında](https://dashboard.render.com/web/srv-dbe3l1l9fdbs73975hog)
   Edit -> `TELEGRAM_BOT_TOKEN` değişkenine tokenı yapıştırıp kaydet.
3. Telegram'da kendi botunu aç (`https://t.me/<BOT_USERNAME>`) ve **Start** / `/start` gönder.
   Bot ilk aşamada yanıt vermeyebilir; bu beklenen davranıştır.
4. Kariyer paneline giriş yapıp [özel Telegram eşleştirme sayfasını](https://careerhunter-private-dashboard.onrender.com/telegram/setup)
   aç. Kendi /start sohbetindeki numeric ID'yi kopyala (yalnızca sahibin oturumuna görünür).
   Render Environment'da `TELEGRAM_CHAT_ID` olarak kaydet.
5. Her iki değişkeni kaydettikten sonra [Telegram Connection Smoke](https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/actions/workflows/telegram-smoke.yml)
   üzerinden `Run workflow` çalıştır. **PASS** ancak Bot API pozitif `message_id`
   döndürdüğünde oluşur. Kullanıcı telefonunda bildirimi aldı diye ayrıca varsayılmaz.

**Telegram için yalnızca 2 gizli ayar:** `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`. Puan eşiği isteğe bağlı `TELEGRAM_MIN_SCORE=75` (varsayılan 75).

## Davranış ve güvenlik

- Günlük tarama sonrası **tek mesaj**: en fazla 3 yüksek puanlı (>=75) yeni ilan.
- Başvuru bağlantılarına ve şifreli ilan paneline açılan URL butonları.
- Senior, ülke kısıtından dolayı uygun olmayan veya önceden görülmüş ilanlar
  otomatik bildirilmez. Hiç uygun yeni ilan yoksa Telegram mesajı gönderilmez.
- Tarama hataları için tek kısa hata bildirimi. Raw exception, DB URL, token,
  özgeçmiş, iş açıklaması veya aday profilinin tamamı gönderilmez.
- Telegram'da butonlar yalnızca URL açar; henüz butonlarla iş başvurusu, CRM
  güncellemesi veya webhook/callback söz konusu değildir.
- Bot API ücretsiz standart gönderim yöntemi kullanılır, paid broadcast kapalıdır.
- Bot tokenı public GitHub'a veya Telegram mesaj metnine asla eklenmez.
