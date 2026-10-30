# CareerHunter — Windows'ta sifir ucretle Render → Neon gecisi

Bu adimlar ozel PostgreSQL verisini **yerel bilgisayarda** yedekler, hedefin bos oldugunu kontrol eder, sonra istenirse Neon'a tek seferlik kopyalar. **Render canli baglantisini degistirmez.**

## Hazirlik (yalnizca senin bilgisayarinda)

1. Repo'nun guncel surumunu al ve Python 3.11+ ile `python -m pip install -e .` calistir. Ucretsiz PostgreSQL 16 veya daha yeni istemci araclari `pg_dump` ve `pg_restore` PATH icinde olmali.
2. Render Dashboard > careerhunter-ai-db > Networking uzerinden **sadece bilgisayarinin mevcut genel IP adresine /32** ile gecici izin ver. `0.0.0.0/0` gibi herkese erisim verme. Render hosted connector icin IP izni kaldirilmis durumda; mevcut kapali ayari kalici degistirme.
3. Render'daki **External Database URL**'yi ve Neon Free konsolundaki PostgreSQL URL'yi alip **sadece yerel gizli giris alanlarina** gir. Bunlari ChatGPT, GitHub, Telegram veya terminal gecmisine yapistirma.
4. Kisisel CV ve tum uygulama kayitlari icin yedegi saklayacagin yerin sifrelenmis ve guvenli oldugunu kontrol et. Varsayilan dizin `~/CareerHunterBackups`tir, GitHub deposu degildir.

## Once yedek ve preflight

```powershell
python -m pip install -e .
.\scripts\migrate_render_to_neon_windows.ps1 -PreflightOnly
```

Script sirasiyla `pg_dump -Fc` olusturur, `pg_restore --list` ile arsiv dizinini okur, SHA-256 hesaplar ve kaynak/hedef satir sayilariyla hedefin boslugunu dogrular. Arsiv okumak **gercek restore testi degildir**; mumkunse guvenli, izole bir PostgreSQL veritabanina `pg_restore` yapip dogrula.

## Gercek kopyalama (yalnizca dogrulanmis yedekten sonra)

Normal 09:17 TRT taramasinin tamamlandigini ve sonraki toplama ile cakismayacagini kontrol et. Gerekirse GitHub zamanlayicisini bakim boyunca gecici kapat; tamamlandiginda yeniden etkinlestir. Yedegi geri yuklemeyi dogrulamadan baslama.

```powershell
.\scripts\migrate_render_to_neon_windows.ps1
```

`MIGRATE` yazilana kadar hedef veritabanina veri kopyalanmaz. Script kaynakta SQL SELECT-only calisir ve Neon tablo icerigi varsa uzerine yazmaz. Kaynak ve hedef tablo parmak izleri ile satir sayilari ayni degilse kopyayi basarisiz sayar. **Calisan Render uygulamasinin URL'sini degistirmez.**

## Sonraki zorunlu kabul

1. Her tablonun kayit sayisini ve ornek kayitlari karsilastir. Veritabani saklama sinirlari ve gizli veri erisim yetkilerini kontrol et.
2. Render'in `DASHBOARD_DATABASE_URL` baglantisini degistirmeden once yeni Neon'da yetkileri ve yazma-okuma testlerini yap. Uygulama semasini veritabaninda dogrula.
3. Yetkili bir bakim adiminda Render baglantisini Neon'a tasi; `/readyz`, giris korumasi, bir tam ilan toplama, Telegram raporu ve duplike ilan kontroluyle dogrula.
4. Tam kabulden ve ayrica geri donus planindan once Render kaynagini silme. Gecici `/32` IP iznini kaldir.

**Render Free veritabani bitis tarihi: 23 Kasim 2026. Neon Free, kaynak/compute/transfer limitleri icinde 0 TL'dir; limit asimi halinde uygulama durabilir.**
