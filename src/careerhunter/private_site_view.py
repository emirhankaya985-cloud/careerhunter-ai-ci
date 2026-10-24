"""Accessible, responsive HTML templates for the owner-only dashboard."""
from __future__ import annotations

from jinja2 import Environment, select_autoescape
from urllib.parse import urlsplit


def safe_external_href(value: object) -> str:
    """Only permit absolute HTTP(S) links from untrusted ATS/contact sources."""
    if value is None:
        return "#"
    # Pydantic HttpUrl objects are not subclasses of str; normalize them too.
    candidate = str(value).strip()
    if not candidate or len(candidate) > 2048:
        return "#"
    try:
        url = urlsplit(candidate)
        if (url.scheme.lower() not in {"http", "https"}
                or not url.hostname or url.username is not None
                or url.password is not None):
            return "#"
        # Reject whitespace and control characters to avoid browser URL ambiguity.
        if any(ord(c) <= 32 or ord(c) == 127 for c in candidate):
            return "#"
    except ValueError:
        return "#"
    return candidate


_ENV = Environment(autoescape=select_autoescape(default=True))
_ENV.filters["safe_href"] = safe_external_href

LOGIN_HTML = _ENV.from_string("""
<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Giriş · CareerHunter</title><style>
:root{color-scheme:dark;font:16px system-ui,Segoe UI,sans-serif}
*{box-sizing:border-box}body{min-height:100dvh;margin:0;background:#090f1c;color:#eaf1fb;display:grid;place-items:center;padding:22px}
.panel{width:min(420px,100%);padding:36px;background:#121e30;border:1px solid #30405a;border-radius:20px;box-shadow:0 20px 80px #0008}
.logo{display:inline-flex;align-items:center;gap:10px;color:#8dd9c6;font-size:14px;font-weight:800;letter-spacing:1.4px}
h1{font-size:31px;letter-spacing:-1px;line-height:1.13;margin:25px 0 12px}
p{color:#a5b6cb;line-height:1.6;margin-bottom:27px}
label{display:block;color:#c3d4e9;font-weight:600;margin-bottom:9px}
input{width:100%;font:inherit;border:1px solid #50617b;background:#080f1e;color:#fff;padding:15px;border-radius:10px;outline-offset:2px}
button{width:100%;margin-top:18px;background:#6de3bc;border:0;border-radius:10px;padding:14px;font:inherit;font-weight:800;color:#08281f;cursor:pointer}
.error{color:#ffc4c4;background:#542b36;padding:12px;border-radius:9px;margin-bottom:17px}
.small{font-size:12px;color:#899bb4;margin-top:24px;text-align:center}
</style></head><body><main class="panel">
<div class="logo">✦ CAREERHUNTER AI <span style="color:#637c9d">/ PRIVATE</span></div>
<h1>Kariyer merkezine<br>hoş geldin.</h1>
<p>İş fırsatları, kişiler ve mesaj taslakları yalnızca sana özel.</p>
{% if error %}<div class="error" role="alert">{{ error }}</div>{% endif %}
<form action="/login" method="post" autocomplete="on">
<label for="password">Özel erişim şifren</label>
<input id="password" name="password" type="password" minlength="16" maxlength="256"
 autocomplete="current-password" placeholder="Şifreni gir" required autofocus>
<button type="submit">Kontrol merkezini aç →</button>
</form><div class="small">Güvenli oturum · Bilgiler herkese açık paylaşılmaz</div>
</main></body></html>
""")

DASHBOARD_HTML = _ENV.from_string("""
<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ heading }} · CareerHunter AI</title><style>
:root{color-scheme:dark;font:15px/1.45 system-ui,Segoe UI,sans-serif}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#080e1b;color:#eaf1fb}
a{color:inherit;text-decoration:none}.shell{display:grid;grid-template-columns:247px minmax(0,1fr);min-height:100dvh}
nav.sidebar{background:#101b2c;border-right:1px solid #29384c;padding:26px 17px;display:flex;flex-direction:column;gap:28px}
.logo{font-size:17px;font-weight:900;letter-spacing:-.4px;padding:0 10px}
.logo span{color:#75e4bc}.tiny{color:#8196b3;font-size:11px;letter-spacing:1.4px;text-transform:uppercase;padding:0 12px}
nav .links{display:grid;gap:6px}nav a.navlink{display:block;border-radius:9px;color:#a4b5ce;padding:11px 13px;font-weight:620}
nav a.navlink:hover,nav a.selected{background:#213a49;color:#8df8cf}
.sidebarbottom{margin-top:auto;padding:16px 12px;border-top:1px solid #26364b;color:#99aec8;font-size:12px}
button.logout{margin-top:12px;background:transparent;border:1px solid #4d617c;color:#b8cce7;border-radius:9px;padding:9px 15px;cursor:pointer}
main{min-width:0;max-width:1500px;width:100%;padding:32px clamp(18px,4vw,60px);margin:auto}
.eyebrow{color:#74daba;font-weight:800;letter-spacing:1.4px;text-transform:uppercase;font-size:11px}
h1{font-size:clamp(29px,3.5vw,43px);line-height:1.08;letter-spacing:-1.6px;margin:10px 0 10px}
h2{font-size:20px;letter-spacing:-.4px;margin:0}p.sub{color:#93a8c3;margin:0 0 30px}
.row{display:flex;gap:14px;align-items:center;flex-wrap:wrap}.space{justify-content:space-between}
.pill{display:inline-flex;border:1px solid #284a48;border-radius:999px;background:#143c33;color:#9be6c9;padding:7px 11px;font-size:12px;font-weight:700}
.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin:24px 0}
.tile,.panel{background:#111d2f;border:1px solid #28394e;border-radius:15px}
.tile{padding:22px}.tile b{display:block;font-size:30px;letter-spacing:-1px;margin:7px 0}
.muted{color:#8ca1bd}.small{font-size:12px}.panel{padding:23px;margin:18px 0}.statlabel{font-size:12px;color:#9fb3cf;font-weight:700}
.columns{display:grid;grid-template-columns:1.1fr .9fr;gap:17px}
.country{display:grid;grid-template-columns:1fr auto auto;gap:12px;align-items:center;border-top:1px solid #27364b;padding:15px 0}
.country:first-child{margin-top:16px}.country b{text-align:right;font-size:18px}.country small{color:#71d6b6}
.steps{display:grid;gap:13px;margin-top:20px}.step{display:flex;align-items:center;gap:12px;color:#ced9e9}
.dot{color:#7fe5bd}.hint{color:#9badc7;background:#192a3e;padding:15px;border-radius:10px;line-height:1.7}
table{width:100%;border-collapse:collapse}th{text-align:left;color:#8da0bb;font-size:12px;letter-spacing:.4px}th,td{padding:14px 12px;border-bottom:1px solid #29384c;vertical-align:top}tr:hover td{background:#16273a}
.link{color:#85e5c4;font-weight:700}.tag{font-size:11px;border-radius:6px;padding:4px 8px;border:1px solid #3c536b;color:#bccee7}
form.search{display:flex;gap:8px;flex-wrap:wrap;margin:24px 0}input.searchinput{background:#111d2f;border:1px solid #41536b;border-radius:9px;padding:12px 14px;color:#eaf1fb;min-width:220px;flex:1;font:inherit}
.action{border:0;background:#74e3bb;color:#0b2e22;border-radius:9px;padding:12px 17px;font:inherit;font-weight:800;cursor:pointer}
.cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin:22px 0}
.person{padding:22px;background:#111d2f;border:1px solid #293c53;border-radius:15px}
.person h3{margin:0;font-size:19px}.person .role{color:#a2b5ce;margin:7px 0 16px;font-size:13px}
.details{margin-top:16px;border-top:1px solid #293b50;padding-top:15px}
details summary{cursor:pointer;color:#8fe7cb;font-weight:700}
.draft{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6;background:#0b1525;border:1px solid #263c52;padding:14px;border-radius:10px;margin-top:14px}
.empty{color:#b4c3d8;padding:30px 0;text-align:center}.pagination{display:flex;justify-content:flex-end;gap:10px;margin:18px 0}
.pagebtn{border:1px solid #48637a;border-radius:9px;padding:9px 14px;color:#c9dbed}
footer{margin-top:40px;color:#627997;font-size:12px}.tablewrap{overflow-x:auto}
@media(max-width:960px){.shell{grid-template-columns:1fr}.sidebar{position:static!important;padding:14px 18px!important;gap:12px!important}
nav .links{display:flex;flex-wrap:wrap}.sidebarbottom,.tiny{display:none}main{padding:23px 18px}
.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.columns,.cards{grid-template-columns:1fr}}
@media(max-width:480px){.metrics{gap:10px}.tile{padding:15px}.tile b{font-size:25px}.panel,.person{padding:15px}
.country{grid-template-columns:1fr auto auto;gap:7px}.country b{font-size:15px}}
</style></head><body>
<div class="shell"><nav class="sidebar" aria-label="Ana menü">
<div class="logo">✦ Career<span>Hunter</span> <span style="font-size:10px;color:#7891a9">AI</span></div>
<div><div class="tiny">SANA ÖZEL PANEL</div>
<div class="links">
<a class="navlink {% if view=='overview' %}selected{% endif %}" href="/">◈ &nbsp; Genel Bakış</a>
<a class="navlink {% if view=='jobs' %}selected{% endif %}" href="/?view=jobs">⌕ &nbsp; İş İlanları</a>
<a class="navlink {% if view=='people' %}selected{% endif %}" href="/?view=people">♧ &nbsp; Kişiler ve Taslaklar</a>
</div></div>
<div class="sidebarbottom">◉ Özel oturum açık
<form method="post" action="/logout"><button class="logout" type="submit">Güvenli çıkış ↗</button></form>
</div></nav>
<main>
<div class="row space"><div class="eyebrow">CAREER INTELLIGENCE / PRIVATE ACCESS</div>
<span class="pill">● Giriş korumalı veri paneli</span></div>
<h1>{{ heading }}</h1><p class="sub">{{ subtitle }}</p>
{% if view=='overview' %}
<div class="metrics">
<div class="tile"><div class="statlabel">TOPLAM İLAN</div><b>{{ "{:,}".format(metrics.total).replace(",",".") }}</b><div class="muted small">Veritabanındaki bütün ilanlar</div></div>
<div class="tile"><div class="statlabel">SON 24 SAAT YENİ</div><b>{{ metrics.new }}</b><div class="muted small">Yeni görülen ilanlar</div></div>
<div class="tile"><div class="statlabel">KAYITLI KİŞİ</div><b>{{ metrics.people }}</b><div class="muted small">Kaynaklara bağlı kayıtlar</div></div>
<div class="tile"><div class="statlabel">HAZIR TASLAK</div><b>{{ metrics.drafts }}</b><div class="muted small">Gönderim otomatik değil</div></div>
</div>
<div class="columns">
<section class="panel"><div class="row space"><h2>🌍 Dört ülke takipçisi</h2><span class="muted small">İlan konumu</span></div>
{% for c in countries %}
<div class="country"><div><strong>{{ c.flag }} {{ c.name }}</strong></div><b>{{ c.total }}</b><small>+{{ c.new }} yeni</small></div>
{% endfor %}
<p class="small muted">Çoklu ülkeli ilanlar birden fazla ülkede sayılabilir. Bu sayılar çalışma izni anlamına gelmez.</p>
</section>
<section class="panel"><h2>⚡ Sistem durumu</h2>
<div class="steps"><div class="step"><span class="dot">●</span> Veritabanı sorgusu başarılı</div>
<div class="step"><span class="dot">●</span> Son kayıtlar okunabiliyor</div>
<div class="step"><span class="dot">●</span> Mesajlar yalnızca inceleme amaçlı</div></div>
<p class="hint">Son veritabanı çalışması:
<strong>{{ latest.slot if latest else 'Henüz kayıt yok' }}</strong> ·
{{ latest.status if latest else 'Bilinmiyor' }}
{% if latest and latest.started_at %}<br>{{ latest.started_at }} (UTC){% endif %}</p>
<a class="link" href="https://github.com/emirhankaya-AFK/careerhunter-ai/actions" target="_blank" rel="noopener noreferrer">GitHub otomasyonlarını görüntüle ↗</a>
</section></div>
<section class="panel"><div class="row space"><h2>📌 Son ilanlar</h2><a class="link" href="/?view=jobs">Tüm ilanlara bak →</a></div>
<div class="tablewrap"><table><thead><tr><th>POZİSYON</th><th>ŞİRKET</th><th>LOKASYON</th><th>KAYNAK</th></tr></thead><tbody>
{% for j in job_rows %}<tr><td><strong>{{ j.title }}</strong></td><td>{{ j.company }}</td><td>{{ j.location }}</td>
<td><a href="{{ j.job_url|safe_href }}" class="link" target="_blank" rel="noopener noreferrer">İlana git ↗</a></td></tr>{% endfor %}
</tbody></table></div>
</section>
{% elif view=='jobs' %}
<form class="search" method="get" action="/"><input type="hidden" name="view" value="jobs">
<input class="searchinput" type="search" name="q" maxlength="80" placeholder="İlan, şirket veya lokasyon ara" value="{{ query }}">
<button class="action" type="submit">Ara</button></form>
<section class="panel"><div class="row space"><h2>🔎 İş fırsatları</h2><span class="muted small">Sayfa başı 40 ilan · {{ page }}. sayfa</span></div>
<div class="tablewrap"><table><thead><tr><th>POZİSYON</th><th>ŞİRKET</th><th>KONUM</th><th>KAYNAK</th></tr></thead><tbody>
{% for j in job_rows %}<tr><td><strong>{{ j.title }}</strong><div class="small muted">{{ j.source }} · {{ j.job_id }}</div></td><td>{{ j.company }}</td><td>{{ j.location }}</td>
<td><a class="link" href="{{ j.job_url|safe_href }}" target="_blank" rel="noopener noreferrer">İlana git ↗</a></td></tr>{% else %}<tr><td colspan="4" class="empty">Bu aramada sonuç bulunamadı.</td></tr>{% endfor %}
</tbody></table></div>
<div class="pagination">
{% if page>1 %}<a class="pagebtn" href="/?view=jobs&q={{ query|urlencode }}&page={{ page-1 }}">← Önceki</a>{% endif %}
{% if has_next %}<a class="pagebtn" href="/?view=jobs&q={{ query|urlencode }}&page={{ page+1 }}">Sonraki →</a>{% endif %}
</div></section>
{% elif view=='people' %}
<div class="panel"><h2>👥 Kişi kayıtları ve kişisel mesajlar</h2>
<p class="muted">Her kartta bulunan kaynak ve hazırlanmış mesajı inceleyebilirsin.
İletişim adresi doğrulanmamış kişiler otomatik olarak gönderilebilir kabul edilmez.</p></div>
<div class="cards">{% for c in people %}
<article class="person"><div class="row space"><h3>{{ c.name }}</h3><span class="tag">{{ c.status }}</span></div>
<div class="role">{{ c.role }} · {{ c.company }}</div>
{% if c.email_public %}<div class="small">✉ {{ c.email_public }}</div>{% else %}<div class="small muted">✉ Doğrulanmış e-posta bulunamadı</div>{% endif %}
{% if c.linkedin_url %}<a class="link small" href="{{ c.linkedin_url|safe_href }}" target="_blank" rel="noopener noreferrer">LinkedIn profilini aç ↗</a>{% endif %}
{% if c.primary_source_url %}<div><a class="link small" href="{{ c.primary_source_url|safe_href }}" target="_blank" rel="noopener noreferrer">Kaynak kanıtını aç ↗</a></div>{% endif %}
<div class="details"><details><summary>Hazır mesajı görüntüle</summary>
{% if c.message_variant_a %}<div class="small muted" style="margin-top:12px">İngilizce taslak</div><div class="draft">{{ c.message_variant_a }}</div>{% endif %}
{% if c.message_variant_a_tr %}<div class="small muted" style="margin-top:12px">Türkçe taslak</div><div class="draft">{{ c.message_variant_a_tr }}</div>{% endif %}
{% if not c.message_variant_a and not c.message_variant_a_tr %}<p class="muted">Bu kişi için henüz taslak yok.</p>{% endif %}
</details></div>
</article>{% else %}<p class="empty">Henüz kayıtlı kişi bulunmuyor.</p>{% endfor %}</div>
{% endif %}
<footer>🔐 Bu ekran yalnızca giriş yapan sahibine açıktır · İletişim gönderimi yoktur · © CareerHunter AI</footer>
</main></div></body></html>
""")

def render_login(error: str | None = None) -> str:
    return LOGIN_HTML.render(error=error)


def render_dashboard(**kwargs: object) -> str:
    return DASHBOARD_HTML.render(**kwargs)
