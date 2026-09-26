# WebSiteCrawler — Site Sağlık Denetçisi

Bir web sitesini baştan sona tarayıp **kırık linkleri** ve **temel SEO sorunlarını** bulan,
sonuçları tek dosyalık bir **HTML raporu** (isteğe bağlı JSON) olarak veren komut satırı aracı.

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

## Geliştirme

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
```

Testler `tests/site/` içindeki küçük sahte siteyi yerel bir HTTP sunucusunda ayağa kaldırıp tarar.
