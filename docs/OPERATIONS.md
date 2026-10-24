# Operasyon

Plan `Europe/Istanbul` saat diliminde günlük 09:00, 10:00, 17:00 ve pazar 18:00'dır. GitHub yoğunluk nedeniyle planlı işleri geciktirebilir. `careerhunter status` son çalışma kaydını, `careerhunter report --latest` son raporu gösterir.

SQLite runner'dan kaybolmasın diye günlük workflow küçük DB ve raporları aynı depoya commit eder; `concurrency` paralel yazmayı engeller. Uzun vadede DB büyüdüğünde repository arayüzünün object storage/managed SQL uygulamasına geçirilmesi gerekir. Düzenli squash/backup politikası eklenmelidir.

