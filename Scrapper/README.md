# Web Content Scraper & Dataset Generator (CPT Ready)

Engine Python untuk melakukan crawling, scraping, dan ekstraksi artikel web (portal berita maupun non-berita seperti blog, UGC, edukasi, kurikulum, dan esai) menjadi file Markdown terstruktur yang bersih, siap digunakan secara langsung sebagai **dataset Continual Pre-Training (CPT) model AI/LLM** (khususnya untuk modul proyek Sekolah Rakyat & Pendidikan Indonesia).

---

## Fitur Utama

- **Trafilatura Heuristic Extraction (Default Converter)**: Menggunakan library standar industri **`trafilatura`** dengan algoritma *text-to-tag density ratio* dan analisis pohon DOM. Secara cerdas mengisolasi teks narasi artikel utama dan membuang navigasi, menu, footer, komentar, paywall, dan blok iklan tanpa bergantung pada selector yang rapuh.
- **CPT Cleaning Pipeline (`clean_cpt_markdown`)**: Filter pembersihan post-processing khusus berita & konten Indonesia untuk menjamin kemurnian korpus CPT:
  - Membersihkan editorial cross-links: `Baca juga:`, `Simak juga / Tonton video:`.
  - Membersihkan penanda iklan: `ADVERTISEMENT`, `SCROLL TO CONTINUE WITH CONTENT`.
  - Membersihkan widget AI chatbot & paywall: KARIN AI (Kompas), langganan Kompas+, modal umpan balik.
  - Membersihkan banner kampanye donasi: *"Bayangkan seorang anak Indonesia... donasi lewat tautan..."*.
  - Membersihkan link gambar kosong dan clickbait: `[![]()](#)`, `![]()`.
  - Menghapus polusi token URL: Mengonversi `[Teks](url)` menjadi `Teks` murni agar distribusi token tokenizer LLM tetap alami.
- **Anti-Nesting & Parent-Child Filtering di DOM**: Engine browser secara otomatis menyaring elemen anak yang induknya sudah terpilih (`querySelectorAll`), mencegah duplikasi teks artikel pada website dengan struktur DOM desktop vs mobile atau nested containers.
- **Default CSS Path `"body"`**: Default selector menggunakan `"body"` (menggantikan `"body p"`), sehingga elemen non-paragraf di dalam kontainer utama tidak terpotong.
- **Dukungan 30 Target Pendidikan & Sekolah Rakyat**: Pemetaan selector dan kondisi filter waktu terpusat pada file [`Scrapper/css_paths.csv`](file:///d:/intern/crawler-engine/Scrapper/css_paths.csv).
- **Google News RSS & Google Dorking Batch Collector**: Pengumpul URL otomatis via RSS feed dengan query Dorking (`site:`, boolean, topik pendidikan), multi-kondisi waktu (`when:10d`, `when:30d`, atau evergreen), serta parameter lokasi/bahasa Indonesia (`hl=id&gl=ID&ceid=ID:id`).
- **Auto-Resolve Google Redirect**: Mengikuti redirect otomatis dari URL Google News (`news.google.com/rss/articles/...`) ke domain target dan mencocokkan CSS selector yang tepat berdasarkan domain akhir.
- **Multi Engine**: Mendukung browser headless Playwright (default) dan Selenium.
- **Fleksibilitas Format Output**: Mendukung mode `each` (1 file `.md` per artikel) dan `merge` (seluruh artikel digabung menjadi 1 file dengan pemisah horizontal rule).
- **Log Pelaporan Kegagalan**: URL yang gagal atau kosong dicatat terpisah ke file `scraper.log` tanpa mengotori dataset training.

---

## Instalasi Dependencies

1. Install package Python yang diperlukan:
   ```bash
   pip install -r Scrapper/requirements.txt
   ```
   *Dependencies meliputi:* `trafilatura`, `playwright`, `selenium`, `markdownify`, `html2text`, `beautifulsoup4`.

2. Install browser driver Playwright:
   ```bash
   python -m playwright install
   ```

---

## Parameter CLI

| Parameter | Alias | Deskripsi | Default |
|---|---|---|---|
| `--keywords-file` | `-kf` | Path ke file daftar keyword (1 per baris) untuk mencari ke 30+ website target sekaligus | `None` |
| `--targets-file` | `-tf` | Path file target website CSV untuk batch mode | `Scrapper/css_paths.csv` |
| `--limit-per-target` | - | Batas artikel per target website saat menggunakan `--keywords-file` | `2` |
| `--urls` | `-u` | Path ke file daftar URL (misal: `Scrapper/sample_urls.txt`) | *Opsional* |
| `--rss-query` | `-q` | Query Google News RSS dorking langsung | *Opsional* |
| `--output` | `-o` | Path file atau folder output Markdown | *Wajib* |
| `--output-mode` | - | Mode penyimpanan: `each` (1 file per artikel) atau `merge` (gabung semua) | `merge` |
| `--converter` | - | Library konversi HTML ke Markdown: `trafilatura`, `markdownify`, atau `html2text` | `trafilatura` |
| `--keep-links` | - | Pertahankan link URL markdown mentah `[teks](url)`. Default: dibersihkan jadi teks murni untuk CPT | `False` |
| `--keep-images` | - | Pertahankan format gambar markdown `![alt](url)`. Default: dibersihkan untuk CPT | `False` |
| `--css-path` | - | Default CSS Path jika domain tidak ada di mapping | `"body"` |
| `--css-paths` | - | Path file CSV mapping domain ke CSS Path | `Scrapper/css_paths.csv` |
| `--raw-html` | - | Simpan raw `innerHTML` tanpa konversi Markdown | `False` |
| `--engine` | - | Browser engine: `playwright` atau `selenium` | `playwright` |
| `--no-headless` | - | Jalankan browser visual (non-headless) | `False` |
| `--timeout` | - | Timeout loading halaman (detik) | `30` |
| `--limit` | - | Batas jumlah URL yang diambil saat menggunakan `--rss-query` | `10` |

---

## Engine Konversi HTML ke Markdown

Dalam pipeline ini disediakan 3 engine konverter:

1. **`trafilatura` (Rekomendasi Default untuk Dataset CPT)**:
   - Standar emas komunitas NLP/LLM untuk ekstraksi artikel web dan pembuatan korpus pre-training.
   - Otomatis mendeteksi teks utama dan membuang menu, sidebar, iklan, dan widget tanpa perlu CSS selector manual yang rumit.
   - Dilengkapi opsi presisi CPT: `favor_precision=True`, `deduplicate=True`, `include_comments=False`.
2. **`markdownify` (Fallback Parser)**:
   - Mengonversi elemen semantik HTML (`<h1>`-`<h6>`, `<p>`, `<blockquote>`, `<ul>`, `<ol>`, `<table>`, `<code>`) ke format Markdown ATX (`#`, `##`).
   - Digunakan sebagai cadangan otomatis apabila trafilatura menerima fragmen HTML non-standar yang sangat pendek.
3. **`html2text` (Alternatif)**:
   - Parser layout HTML berbasis teks klasik via flag `--converter html2text`.

---

## Google News RSS & Google Dorking

### 1. Struktur URL Feed RSS
```
https://news.google.com/rss/search?q={query}&hl=id&gl=ID&ceid=ID:id
```
- `hl=id`: Bahasa antarmuka Bahasa Indonesia.
- `gl=ID`: Lokasi geografis Indonesia.
- `ceid=ID:id`: Country Edition Identifier (Indonesia - Bahasa Indonesia).

### 2. Multi-Condition Waktu (`when:`)
- **`when:10d`**: Mengambil artikel dalam 10 hari terakhir (portal berita berkala tinggi: Kompas, Detik, Tribunnews, CNBC, dll.).
- **`when:30d`**: Mengambil artikel dalam 30 hari terakhir (portal analisis: Tempo, Tirto, Bisnis.com, Kompasiana).
- **`when` Dihapus (Evergreen / Tanpa Filter Waktu)**: Sangat penting untuk **website materi pelajaran & non-berita** (Kemdikbud, Ruangguru, Zenius, Quipper, Historia, IndoPROGRESS, Mojok, Wikipedia). Menghindari hasil 0 artikel akibat jadwal rilis materi yang berjarak bulanan/tahunan.

### 3. Mengambil URL Mandiri dengan `rss_crawler.py`
```bash
python Scrapper/rss_crawler.py -q "site:kompas.com 'Sekolah Rakyat' when:10d" -l 20 -o Scrapper/sample_urls.txt
```

---

## Pemetaan 30 Target Pendidikan & Sekolah Rakyat (`css_paths.csv`)

Seluruh target website pendidikan disatukan dalam **satu file konfigurasi tunggal**: [`Scrapper/css_paths.csv`](file:///d:/intern/crawler-engine/Scrapper/css_paths.csv) dengan format `url;css_path;when`:

| No | Target / Domain | Kategori | CSS Path (innerHTML) | Filter Waktu (`when`) |
|:---:|---|---|---|:---:|
| 1 | `kemdikbud.go.id` | Pemerintah & Kurikulum | `div.content-detail, div.entry-content, article` | *Tanpa Filter (Evergreen)* |
| 2 | `kemenag.go.id` | Pemerintah & Kurikulum | `div.detail-content, div.content-detail, article` | `when:30d` |
| 3 | `ruangguru.com` | Materi Pelajaran (SD/SMP/SMA) | `div.entry-content, div.blog-post, article` | *Tanpa Filter (Evergreen)* |
| 4 | `zenius.net` | Materi Pelajaran (Sains & Eksakta) | `div.entry-content, div.content-post, article` | *Tanpa Filter (Evergreen)* |
| 5 | `quipper.com` | Materi Belajar & Rumus | `div.entry-content, article.post, article` | *Tanpa Filter (Evergreen)* |
| 6 | `historia.id` | Sejarah Pendidikan & Tokoh | `div.article-content, div.entry-content, article` | *Tanpa Filter (Evergreen)* |
| 7 | `indoprogress.com` | Pedagogi Kritis & Sekolah Rakyat | `div.entry-content, article` | *Tanpa Filter (Evergreen)* |
| 8 | `mojok.co` | Esai & Refleksi Pendidikan | `article, div.entry-content` | *Tanpa Filter (Evergreen)* |
| 9 | `kompasiana.com` | Opini Guru & Pengajaran | `div.read__content, div.article-content` | `when:30d` |
| 10 | `goodnewsfromindonesia.id` | Sekolah Alam & Pelosok | `div.content-detail, div.entry-content` | `when:30d` |
| 11 | `id.wikipedia.org` | Ensiklopedia Sains & Sosial | `div#mw-content-text div.mw-parser-output` | *Tanpa Filter (Evergreen)* |
| 12 | `nu.or.id` | Pendidikan Karakter & Pesantren | `div.post-content, div.detail__content, article` | `when:30d` |
| 13 | `rri.co.id` | Pendidikan & Sekolah 3T | `div.detail-content, div.content-detail, article` | `when:10d` |
| 14 | `kompas.com` | Media Berita Edukasi | `div.read__content, div.read__article` | `when:10d` |
| 15 | `detik.com` | Media Berita Edukasi | `div.detail__body-text` | `when:10d` |
| 16 | `tempo.co` | Media Berita Edukasi | `div.detail-konten, div.read__article` | `when:30d` |
| 17 | `tirto.id` | Media Riset & Analisis | `div.content-text-editor` | `when:30d` |
| 18 | `antaranews.com` | Media Berita Edukasi | `div.post-content, div.article-body` | `when:10d` |
| 19 | `sindonews.com` | Media Berita Edukasi | `div.article-content` | `when:30d` |
| 20 | `republika.co.id` | Media Berita Edukasi | `div.article-content, div.tafakur-content` | `when:30d` |
| 21 | `jawapos.com` | Media Berita Edukasi | `div.entry-content, div.content` | `when:30d` |
| 22 | `liputan6.com` | Media Berita Edukasi | `div.article-content-body__item-content, div.article-content-body` | `when:30d` |
| 23 | `tribunnews.com` | Media Berita Edukasi | `div.txt-article` | `when:10d` |
| 24 | `kumparan.com` | Media Berita Edukasi | `div[data-qa-id='story-body'], div.story-body` | `when:10d` |
| 25 | `suara.com` | Media Berita Edukasi | `div.content-article` | `when:10d` |
| 26 | `mediaindonesia.com` | Media Berita Edukasi | `div.article-content, div.news-detail` | `when:30d` |
| 27 | `suaramerdeka.com` | Media Berita Edukasi | `div.read__article, div.entry-content` | `when:30d` |
| 28 | `cnnindonesia.com` | Media Berita Edukasi | `div.detail-text, div.detail__body-text` | `when:30d` |
| 29 | `inews.id` | Media Berita Edukasi | `div.article-content, div.content-detail` | `when:30d` |
| 30 | `idntimes.com` | Media Berita Edukasi | `div.article-content` | `when:30d` |

---

## Contoh Penggunaan Lengkap

### 1. Batch Scraping Dataset CPT (1 File per Artikel)
Cukup tuliskan daftar topik pendidikan pada file [`Scrapper/keyword_text.txt`](file:///d:/intern/crawler-engine/Scrapper/keyword_text.txt):
```text
Sekolah Rakyat
kurikulum merdeka pendidikan
materi pembelajaran sekolah
pendidikan karakter anak
pelatihan vokasi keterampilan siswa
```

Jalankan perintah batch scraping ke seluruh 30 website target sekaligus:
```bash
python Scrapper/scraper.py --keywords-file=Scrapper/keyword_text.txt --limit-per-target=2 --output=Scrapper/output/hasil_batch/ --output-mode=each
```
*Program otomatis mencari setiap keyword ke seluruh 30 target via Google News RSS, memfilter tanggal dengan aturan `when` masing-masing, mengekstrak artikel murni menggunakan `trafilatura`, dan memproduksi file `.md` bersih di folder output.*

---

### 2. Scraping Langsung via Query Dorking Tunggal
```bash
python Scrapper/scraper.py --rss-query="site:kompas.com 'Sekolah Rakyat' when:10d" --limit=3 --output=Scrapper/output/hasil/ --output-mode=each
```

### 3. Scraping Artikel Non-Berita (Materi / Esai Pendidikan)
```bash
python Scrapper/scraper.py --rss-query='site:mojok.co "pendidikan"' --limit=3 --output=Scrapper/output/hasil/ --output-mode=each
```

### 4. Scraping dari File Daftar URL
```bash
python Scrapper/scraper.py --urls=Scrapper/sample_urls.txt --output=Scrapper/output/hasil/ --output-mode=each
```

### 5. Mempertahankan Hyperlink Asli (Jika Tidak untuk CPT Teks Murni)
Jika Anda membutuhkan link URL markdown mentah `[anchor](https://...)` untuk keperluan selain pre-training model, tambahkan argumen `--keep-links`:
```bash
python Scrapper/scraper.py --urls=Scrapper/sample_urls.txt --output=Scrapper/output/hasil/ --keep-links
```
