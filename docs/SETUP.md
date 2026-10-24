# Kurulum

Python 3.11+ ile `python -m pip install -e ".[dev]"` çalıştır. `config/companies.yaml` içindeki örnek slug'ları resmi kariyer sayfalarından doğrula. Kural tabanlı kullanım için secret gerekmez.

GitHub'da depo oluşturup dosyaları push et. Actions sekmesinden `Tests`, sonra `Daily Career Intelligence` workflow'unu `jobs` seçerek manuel çalıştır. Yazma korumalı ana dal varsa state commit adımı yerine ayrı bir state branch/artifact/storage backend gerekir.

Network hafızasına yalnızca kendi doğruladığın, izinli kaynaklı kişileri ekle: `python -m careerhunter contact import --file data/examples/contacts.json`. Durum kaydı için: `python -m careerhunter contact update --id KISI_ID --status contacted_manually`. `python -m careerhunter run --slot network` yalnızca yeterli kaynak bağlamı olan kişiler için taslak hazırlar; LinkedIn'e erişmez veya bir şey göndermez.

Opsiyonel secret'lar: `LLM_API_KEY`, `NVIDIA_SUPER_API_KEY`, `NVIDIA_ULTRA_API_KEY`, `GROQ_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. LLM için `LLM_PROVIDER=nvidia`, `groq`, `gemini`, `ollama` veya `openai_compatible` seçilebilir. NVIDIA modunda Super birincil, Ultra ise hata durumunda fallback'tir. API anahtarı yoksa sistem yalnızca kural tabanlı moda geçer.

