# Yerel dashboard ve dışa aktarma

Dashboard, mevcut SQLite/PostgreSQL verisini **salt-okunur** biçimde gösteren
hafif bir veri katmanıdır. Demo kayıt üretmez ve CRM kayıtlarını değiştirmez.

```powershell
python -m careerhunter.dashboard --format json --output reports/dashboard.json
python -m careerhunter.dashboard --country usa --remote remote --format csv --output reports/us-remote.csv
```

Filtreler: `--country`, `--company`, `--role`, `--eligibility`, `--remote`,
`--sponsorship` ve `--crm-status`. Ülke/uygunluk sınıflandırması ilan metnindeki
kanıta dayalı alanlardan türetilir; belirsiz sonuçlar otomatik olarak uygun kabul
edilmez. `DATABASE_URL` tanımlıysa aynı komut Supabase/PostgreSQL'i okur,
aksi halde `data/careerhunter.db` kullanılır.

CSV yalnızca ilan listesini içerir; JSON iş ilanları, kişiler, fırsatlar,
takipler ve son çalıştırma durumunu birlikte içerir. Kişisel iletişim bilgileri
loglanmaz ve dışarı gönderilmez.
