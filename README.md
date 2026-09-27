# WebSiteCrawler — Site Sağlık Denetçisi

Bir web sitesini baştan sona tarayıp **kırık linkleri** ve **temel SEO sorunlarını** bulan,
sonuçları tek dosyalık bir **HTML raporu** (isteğe bağlı JSON) olarak veren araç.
İki şekilde kullanılabilir: **komut satırından** veya giriş gerektiren bir **web panelinden**.

## Kurulum

```bash
pip install -r requirements.txt
```

## Kullanım

```bash
python main.py https://example.com
# veya
python -m sitecrawler https://example.com --max-pages 500 --check-external --json report.json
```

Tarama bitince `report.html` dosyasını tarayıcıda açın.

| Seçenek | Açıklama | Varsayılan |
|---|---|---|
| `--max-pages` | En fazla taranacak sayfa | 200 |
| `--max-depth` | Başlangıç sayfasından en fazla link derinliği | 5 |
| `--delay` | İstekler arası bekleme (sn), sunucuyu yormamak için | 0.2 |
| `--timeout` | İstek zaman aşımı (sn) | 10 |
| `--slow-ms` | Bu süreyi aşan sayfalar "yavaş" sayılır | 1500 |
| `--check-external` | Dış linklerin çalışıp çalışmadığını da kontrol et | kapalı |
| `--ignore-robots` | `robots.txt` kurallarını yok say | kapalı |
| `--html` / `--json` | Rapor dosyaları | `report.html` / yok |
| `--fail-on-error` | Hata varsa çıkış kodu 1 (CI'da kullanmak için) | kapalı |
| `-q` | Taranan sayfaları tek tek yazdırma | kapalı |

## Neleri kontrol eder?

| Seviye | Kontrol |
|---|---|
| Hata | Kırık sayfa (4xx/5xx, bağlantı hatası), kırık dış link, eksik `<title>` |
| Uyarı | Tekrar eden başlık / meta açıklama, eksik meta açıklama, eksik H1, yavaş sayfa |
| Bilgi | Çok uzun başlık (>60) / açıklama (>160), birden fazla H1, az içerik (<100 kelime), yönlendirme |

Her sorun için o sayfaya **hangi sayfaların link verdiği** de raporlanır, böylece kırık linki
nereden düzelteceğinizi hemen görürsünüz. Rapor ayrıca 0–100 arası bir **sağlık puanı** içerir.

## Tarayıcı nasıl davranır?

- Kuyruk tabanlı (BFS) tarama; özyineleme sınırına takılmaz.
- Sadece başlangıç adresiyle aynı alan adındaki sayfaları tarar (`www.` farkı yok sayılır).
- `#bölüm` parçalarını atar; `mailto:`, `tel:`, `javascript:` ve `rel="nofollow"` linklerini atlar.
- HTML olmayan içeriği (PDF, resim…) kaydeder ama içinde link aramaz.
- Sunucu `charset` bildirmese bile Türkçe karakterleri doğru çözer.
- Varsayılan olarak `robots.txt` kurallarına uyar.

## Web paneli

Kullanıcılar giriş yapıp tarayıcıdan tarama başlatır, geçmiş taramalarını ve raporlarını görür.
Her kullanıcı yalnızca kendi taramalarını görebilir.

```bash
flask --app webapp create-user eyup      # parola gizli olarak sorulur
flask --app webapp run                   # http://127.0.0.1:5000
```

Canlı ortamda Flask'ın geliştirme sunucusu yerine bir WSGI sunucusu (ör. `gunicorn "webapp:create_app()"`)
ve önünde HTTPS sağlayan bir ters vekil sunucu (nginx, Caddy…) kullanın.

### Ayarlar (ortam değişkenleri)

| Değişken | Açıklama | Varsayılan |
|---|---|---|
| `SITECRAWLER_SECRET_KEY` | Oturum imzalama anahtarı. Verilmezse `instance/secret_key` dosyasında rastgele üretilir | otomatik |
| `SITECRAWLER_DATABASE` | SQLite veritabanı yolu | `instance/sitecrawler.db` |
| `SITECRAWLER_COOKIE_SECURE` | Çerezleri yalnızca HTTPS üzerinden gönder + HSTS. **Canlıda açın** | kapalı |
| `SITECRAWLER_ALLOW_SIGNUP` | Herkesin kayıt olmasına izin ver | kapalı |
| `SITECRAWLER_TRUST_PROXY` | Tek bir ters vekil sunucunun arkasındaysa istemci IP'sini `X-Forwarded-For`'dan al | kapalı |
| `SITECRAWLER_ALLOW_PRIVATE_TARGETS` | Yalnızca yerel geliştirme için: localhost / iç ağ taranabilsin | kapalı |

### Güvenlik önlemleri

**Giriş ve oturum**
- Parolalar düz metin değil, `scrypt` ile tuzlanıp hash'lenerek saklanır. En az 10 karakter,
  yaygın parolalar ve kullanıcı adını içeren parolalar reddedilir.
- Kaba kuvvet koruması: aynı kullanıcı adına 15 dakikada 5, aynı IP'den 20 başarısız denemeden sonra giriş geçici olarak kilitlenir.
- "Kullanıcı yok" ve "parola yanlış" durumları aynı mesajı verir ve aynı sürede yanıtlanır (kullanıcı adı tahmini engellenir).
- Oturum çerezi `HttpOnly`, `SameSite=Lax`, isteğe bağlı `Secure`; 8 saat sonra düşer. Girişte oturum yenilenir (session fixation koruması).
- Parola değiştirmek veya "tüm cihazlardan çıkış" diğer bütün oturumları geçersiz kılar.
- Kayıt varsayılan olarak kapalıdır; kullanıcılar `create-user` komutuyla oluşturulur.

**İstekler**
- Tüm POST formlarında CSRF anahtarı zorunludur.
- Girişten sonra yalnızca site içi adreslere yönlendirilir (open redirect yok).
- Sıkı güvenlik başlıkları: `Content-Security-Policy`, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, HSTS.
- Başka bir kullanıcının taramasına erişmeye çalışmak 404 döner; tarama kimlikleri tahmin edilemez rastgele değerlerdir.

**Tarayıcı (SSRF koruması)**
- Panel, `localhost`, `127.0.0.0/8`, `10.0.0.0/8`, `192.168.0.0/16`, `169.254.169.254` (bulut metadata) gibi
  iç/özel adresleri, 80/443 dışındaki portları ve `http(s)` dışındaki şemaları taramayı reddeder.
- Yönlendirmeler tek tek takip edilir; her adım yeniden kontrol edilir, böylece dışarıdan zararsız görünen
  bir sayfa tarayıcıyı iç ağa yönlendiremez.
- Yanıt boyutu 5 MB ile sınırlıdır; HTML olmayan içerik hiç indirilmez.
- Kullanıcı başına aynı anda 1 tarama, günde 20 tarama ve tarama başına en fazla 500 sayfa.

**Raporlar**
- Taranan sitelerden gelen tüm metinler HTML'e kaçışlanarak (escape) yazılır.
- Rapor sayfası `sandbox` CSP'si ile ayrı bir kaynakta çalışır; yalnızca raporun kendi stil ve betiği
  (SHA-256 hash'leriyle) çalıştırılabilir, oturum çerezine erişemez.

**Bilinen sınırlama:** Adres kontrolü ile bağlantı arasındaki kısa sürede DNS yanıtı değiştirilirse
(DNS rebinding) koruma aşılabilir. Paneli internete açacaksanız sunucuyu ayrıca iç ağa erişimi
kısıtlanmış bir ağda / güvenlik duvarı arkasında çalıştırın.

## Geliştirme

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
```

Testler `tests/site/` içindeki küçük sahte siteyi yerel bir HTTP sunucusunda ayağa kaldırıp tarar.
