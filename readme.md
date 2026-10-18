# AITF Crawler Engine & Scrapper Dataset Generator

Repository ini berisi kumpulan modul dan engine untuk melakukan web crawling, ekstraksi artikel, pengumpulan URL, serta pembuatan dataset teks bersih untuk kebutuhan pelatihan model AI/LLM (**Continual Pre-Training / CPT**).

---

## Struktur Direktori Utama

- **[`Scrapper/`](file:///d:/intern/crawler-engine/Scrapper/)**: Engine Python modern berbasis Playwright, Selenium, dan Trafilatura. Didesain khusus untuk mengekstrak artikel web ke format Markdown murni bebas iklan dan noise untuk dataset CPT Sekolah Rakyat & Pendidikan.
- **`Windows/`**: CLI binary dan installer ChromeDriver untuk Windows.
- **`Linux/`**: CLI binary dan installer untuk Linux (Ubuntu/Debian).
- **`MacOS/`**: CLI binary dan installer untuk macOS.

---

## 🚀 Scrapper (Python Engine - CPT Dataset Generator)

Direktori [`Scrapper/`](file:///d:/intern/crawler-engine/Scrapper/) memuat toolchain scraping web generasi terbaru yang mengintegrasikan Google News RSS Dorking, Playwright headless browser, engine ekstraksi heuristik **Trafilatura**, serta pipeline pembersih teks bahasa Indonesia.

### 1. Instalasi Dependencies Scrapper
Pastikan berada di root direktori proyek, lalu jalankan:
```bash
# 1. Install library Python
pip install -r Scrapper/requirements.txt

# 2. Install browser driver Playwright
python -m playwright install
```
*Dependencies utama:* `trafilatura`, `playwright`, `selenium`, `markdownify`, `html2text`, `beautifulsoup4`.

---

### 2. Cara Menjalankan Scrapper

#### A. Batch Scraping 30+ Target Sekaligus (Rekomendasi Utama)
Membaca daftar keyword dari file [`Scrapper/keyword_text.txt`](file:///d:/intern/crawler-engine/Scrapper/keyword_text.txt) dan mencarinya secara paralel ke 30 website berita dan materi edukasi non-berita yang terdaftar di [`Scrapper/css_paths.csv`](file:///d:/intern/crawler-engine/Scrapper/css_paths.csv):

```bash
python Scrapper/scraper.py --keywords-file=Scrapper/keyword_text.txt --limit-per-target=2 --output=Scrapper/output/hasil_batch/ --output-mode=each
```
*Hasil:* 
- Setiap artikel disimpan terpisah dalam file Markdown bersih (`scraped_001_....md`, `scraped_002_....md`, dst.).
- Laporan status eksekusi lengkap dicatat di file log [`Scrapper/output/hasil_batch/scraper.log`](file:///d:/intern/crawler-engine/Scrapper/output/hasil_batch/scraper.log).

---

#### B. Scraping Langsung via Query Dorking Tunggal
Mengambil artikel dari pencarian Google News RSS secara langsung:
```bash
python Scrapper/scraper.py --rss-query="site:kompas.com 'Sekolah Rakyat' when:10d" --limit=3 --output=Scrapper/output/hasil/ --output-mode=each
```
*(Catatan: Sistem otomatis menormalisasi tanda petik satu menjadi petik ganda agar kompatibel dengan mesin pencari Google).*

---

#### C. Scraping dari File Daftar URL
Jika Anda telah memiliki daftar link URL artikel sendiri (1 baris 1 URL):
```bash
python Scrapper/scraper.py --urls=Scrapper/sample_urls.txt --output=Scrapper/output/hasil/ --output-mode=each
```

---

### 3. Fitur Unggulan Engine Scrapper

1. **Trafilatura Heuristic Engine (Default Converter)**:
   - Standar industri untuk ekstraksi artikel NLP/LLM.
   - Menggunakan rasio densitas teks (*text-to-tag ratio*) untuk memotong menu, footer, sidebar, komentar, dan iklan secara otomatis tanpa ketergantungan selector yang kaku.
2. **CPT Cleaning Pipeline (`clean_cpt_markdown`)**:
   - Menghapus blok *"Baca juga:"*, *"Simak video:"*, penanda iklan `ADVERTISEMENT`, widget Chatbot AI (KARIN), paywall langganan, dan kampanye donasi.
   - Menghapus polusi token URL: Mengubah format `[Teks](url)` menjadi teks murni `Teks`.
3. **Anti-Duplikasi Parent-Child di Browser DOM**:
   - Memfilter elemen agar tidak mengekstrak kontainer anak yang sudah tercakup di kontainer induknya.
4. **Unified Configuration 30 Target (`Scrapper/css_paths.csv`)**:
   - Satu file pemetaan tunggal untuk 30 website pendidikan (berita dan non-berita seperti Ruangguru, Zenius, Quipper, Historia, Kemdikbud) beserta filter waktu (`when:10d`, `when:30d`, atau evergreen).
5. **Pencatatan Log Lengkap (`scraper.log`)**:
   - Selalu mencatat rekapitulasi URL yang diproses, jumlah berhasil, jumlah gagal, serta rincian setiap URL lengkap dengan link redirect aslinya (*Redirected URL*) dan status eksekusinya (`SUCCESS` / error).

> Dokumentasi teknis parameter dan opsi lengkap Scrapper dapat dibaca di: **[`Scrapper/README.md`](file:///d:/intern/crawler-engine/Scrapper/README.md)**.

---

## 🛠️ Panduan Penggunaan AITF Crawler Engine (Legacy Binary)

Bagian ini memuat dokumentasi penggunaan binary crawler bawaan (`aitf-engine`) untuk platform Linux, macOS, dan Windows.

### 1. Instalasi (Dependencies)

#### Windows 10/11 (PowerShell)
```powershell
# Pergi ke direktori Windows
cd Windows

# Install Chrome + ChromeDriver
.\windows-installer.ps1

# Aktifkan profile di shell baru
. $PROFILE
```

#### Linux (Ubuntu/Debian)
```bash
cd Linux

chmod +x linux-installer.sh
./linux-installer.sh
source ~/.bashrc
```

#### macOS
```bash
cd MacOS

chmod +x macos-installer.sh
./macos-installer.sh
source ~/.zshrc
```

---

### 2. Menjalankan AITF Engine
Masuk ke salah satu folder platform (Linux/MacOS/Windows):
```bash
# Untuk Linux
cd Linux

# Untuk MacOS
cd MacOS
```

Cek perintah bantuan:
```bash
./aitf-engine --help
```

---

### 3. Crawling Google Search
```bash
./aitf-engine crawl -k "Rumah Layak Huni" --keyword-type=keywords --token={YOUR_TOKEN}
```

Contoh dengan keyword dari file `daftar_keyword.txt` (default `--keyword-type=keywords_file`):
```bash
./aitf-engine crawl --token={YOUR_TOKEN}
```

Mode Crawling Gambar:
```bash
./aitf-engine crawl --search-image-mode=True --token={YOUR_TOKEN}
```

---

### 4. Extract Text
```bash
./aitf-engine extract-text --token={YOUR_TOKEN}
```

Jika file daftar input URL berbeda:
```bash
./aitf-engine extract-text -f output/crawler_url.txt --token={YOUR_TOKEN}
```

---

### 5. Extract / Download Gambar
```bash
./aitf-engine extract-image --token={YOUR_TOKEN}
```

Output gambar disimpan di folder:
```
output/extracted_image_{timestamp}
```

---

### 6. Autentikasi Program AITF
Binary `aitf-engine` membutuhkan token untuk aktivasi.

Gunakan flag `--token`:
```bash
aitf-engine crawl --token={YOUR_TOKEN}
```

Atau set sebagai environment variable OS:
```bash
export CRAWLER_ENGINE_TOKEN=PASTE_TOKEN
./aitf-engine crawl
```
