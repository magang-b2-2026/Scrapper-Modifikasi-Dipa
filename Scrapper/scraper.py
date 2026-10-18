#!/usr/bin/env python3
"""
Web Content Scraper CLI Script
Supporting Playwright & Selenium with custom CSS selectors, Google News RSS / Dorking,
innerHTML extraction, and HTML-to-Markdown conversion (markdownify / html2text).
"""

import argparse
import csv
import os
import re
import sys
import time
from urllib.parse import urlparse
from typing import Dict, List, Tuple, Optional


def normalize_url_key(url_str: str) -> str:
    """Normalize URL/domain for matching dictionary key."""
    url_str = url_str.strip()
    # Remove protocol if present
    url_no_proto = re.sub(r'^https?://', '', url_str, flags=re.IGNORECASE)
    # Remove trailing slash
    return url_no_proto.rstrip('/').lower()


def load_css_paths(csv_file_path: str) -> Dict[str, str]:
    """
    Load mapping of URL/Domain to css_path from CSV file.
    Supports ';' or ',' as delimiter.
    """
    mapping: Dict[str, str] = {}
    if not os.path.isfile(csv_file_path):
        print(f"[Error] File css-paths '{csv_file_path}' tidak ditemukan.")
        sys.exit(1)

    with open(csv_file_path, mode='r', encoding='utf-8-sig') as f:
        # Sample to determine delimiter
        first_line = f.readline()
        f.seek(0)
        delimiter = ';' if ';' in first_line else ','
        
        reader = csv.DictReader(f, delimiter=delimiter)
        # Normalize column names
        field_map = {}
        if reader.fieldnames:
            for field in reader.fieldnames:
                clean_field = field.strip().lower()
                if clean_field in ['url', 'urls', 'domain']:
                    field_map['url'] = field
                elif clean_field in ['css_path', 'csspath', 'css', 'selector']:
                    field_map['css_path'] = field

        if 'url' not in field_map or 'css_path' not in field_map:
            # Fallback for headerless or custom headers: first col = url, second = css_path
            f.seek(0)
            raw_reader = csv.reader(f, delimiter=delimiter)
            for row in raw_reader:
                if len(row) >= 2:
                    u_key = normalize_url_key(row[0])
                    mapping[u_key] = row[1].strip()
        else:
            for row in reader:
                url_val = row.get(field_map['url'], '').strip()
                css_val = row.get(field_map['css_path'], '').strip()
                if url_val and css_val:
                    u_key = normalize_url_key(url_val)
                    mapping[u_key] = css_val

    return mapping


def get_css_selector_for_url(
    url: str,
    css_paths_map: Optional[Dict[str, str]],
    default_css_path: str = "body",
    silent: bool = False
) -> Tuple[str, bool]:
    """
    Returns (css_path, is_defined).
    If css_paths_map is given but URL is not found, print log message and return default_css_path.
    """
    if css_paths_map is None:
        return default_css_path, True

    parsed = urlparse(url if url.startswith(('http://', 'https://')) else f"https://{url}")
    domain = parsed.netloc.lower()
    full_url_norm = normalize_url_key(url)

    # 1. Check exact full URL match first
    if full_url_norm in css_paths_map:
        return css_paths_map[full_url_norm], True

    # 2. Check domain match (e.g. www.kompas.com or kompas.com)
    domain_norm = normalize_url_key(domain)
    if domain_norm in css_paths_map:
        return css_paths_map[domain_norm], True

    # 3. Check domain without www prefix
    domain_no_www = domain_norm.replace('www.', '')
    if domain_no_www in css_paths_map:
        return css_paths_map[domain_no_www], True

    # 4. Substring match check
    for key, selector in css_paths_map.items():
        if key in full_url_norm or key in domain_norm:
            return selector, True

    # Not defined in css_paths_map
    if not silent:
        print(f"css-path url '{url}' tidak didefinisikan, menggunakan default path ('{default_css_path}')")
    return default_css_path, False


def extract_content_js() -> str:
    """
    JavaScript snippet executed in browser context.
    Returns innerHTML of matched elements while filtering out nested child elements
    to avoid duplication (e.g. article containing .entry-content).
    """
    return """
    (cssPath) => {
        let elements = Array.from(document.querySelectorAll(cssPath));
        if (elements.length === 0) return '';
        // Filter elements that are already contained inside another matched element
        let topElements = elements.filter(el => {
            return !elements.some(other => other !== el && other.contains(el));
        });
        let scrapped = '';
        topElements.forEach(el => {
            scrapped += '\\n' + el.innerHTML;
        });
        return scrapped;
    }
    """


def clean_cpt_markdown(
    text: str,
    strip_links: bool = True,
    strip_images: bool = True
) -> str:
    """
    Spesialis pembersih teks/markdown untuk dataset Continual Pre-Training (CPT).
    Menghilangkan editorial links, ad markers, widget AI, donasi, paywall, dan noise umum berita Indonesia.
    """
    if not text or not text.strip():
        return ""

    lines = text.split("\n")
    cleaned_lines = []

    # Pola baris pengganggu yang harus dibuang seluruh barisnya
    noise_line_patterns = [
        r'^\s*\*{0,2}baca\s+juga\s*:.*',
        r'^\s*\*{0,2}(?:simak|tonton|lihat|baca)\s+(?:juga|video|artikel)?\s*:.*',
        r'^\s*ADVERTISEMENT\s*$',
        r'^\s*SCROLL\s+TO\s+(?:CONTINUE|RESUME)\s+WITH\s+CONTENT.*',
        r'^\s*Pilihan\s+(?:Editor|Untukmu)\s*:?.*',
        r'^\s*Artikel\s+ini\s+telah\s+(?:tayang|masuk\s+arsip).*',
        r'^\s*Dapatkan\s+update\s+berita\s+pilihan.*',
        r'^\s*Ikuti\s+saluran\s+WhatsApp.*',
        r'^\s*Bahas\s+berita\s+ini\s+dengan\s+KARIN.*',
        r'^\s*KARIN\s*$',
        r'^\s*BETA\s*$',
        r'^\s*Kompas\.com\s+Artificial\s+Intelligence\s*$',
        r'^\s*Hai,\s+Saya\s+KARIN\s*$',
        r'^\s*Apa\s+yang\s+ingin\s+kamu\s+ketahui\?*\s*$',
        r'^\s*Kamu\s+bisa\s+bertanya.*',
        r'^\s*Batas\s+akses\s+KARIN\s*$',
        r'^\s*Kamu\s+sudah\s+mencapai\s+batas\s+akses.*',
        r'^\s*Gabung\s+membership.*',
        r'^\s*Rp\d+[\d\.,]*/(?:bulan|tahun).*',
        r'^\s*Beri\s+umpan\s+balik\s*$',
        r'^\s*(?:Tidak\s+akurat|Tidak\s+relevan|Menyinggung|Terlalu\s+lama|Isu\s+privasi|Lainnya)\s*$',
        r'^\s*Khusus\s+Member\s*$',
        r'^\s*Akses\s+Tanya\s+Langsung\s+Tersedia.*',
        r'^\s*selengkapnya\s*$',
        r'^\s*Lihat\s+.*?\s+Selengkapnya\s*$',
        r'^\s*Pilihan\s+Untukmu\s*$',
        r'^\s*Intinya\s+Sih\s*$',
        r'^\s*Timeline\s*$',
        r'^\s*5W1H\s*$',
        r'^\s*Gini\s+Kak\s*$',
        r'^\s*Sisi\s+Positif\s*$',
        r'^\s*Editorial\s+Team\s*$',
        r'^\s*Topics\s*$',
        r'^\s*Isi\s+komentar\s+sepenuhnya\s+adalah\s+tanggung\s+jawab.*',
        r'^\s*Baca\s+berita\s+lainnya\s+di\s+Google\s+News.*',
        r'^\s*Share\s+Article.*',
        r'^\s*Curated\s+For\s+You.*',
        r'^\s*This\s+section\s+summary\s+was\s+AI-assisted.*',
        r'^\s*\[\!\[\]\(\)\]\(.*?\)\s*$',  # Empty image links [![]()](#)
        r'^\s*\!\[\]\(\)\s*$',              # Empty images ![]()
        r'^\s*\|\s*\|\s*\|\s*$',            # Empty markdown table rows
        r'^\s*Halaman\s+\d+/\d+\s*$',       # Tribun pagination Halaman 1/2
        r'^\s*Berita\s+Terkait\s*:?.*',     # Berita Terkait
    ]

    combined_regex = re.compile("|".join(f"(?:{p})" for p in noise_line_patterns), flags=re.IGNORECASE)

    skip_block = False
    for line in lines:
        stripped = line.strip()

        # Deteksi blok donasi Kompas / campaign banner
        if re.search(r'Bayangkan seorang anak Indonesia bercita-cita.*donasi lewat tautan', stripped, flags=re.IGNORECASE):
            continue
        # Deteksi awal blok widget KARIN / Chatbot / subscription paywall
        if re.search(r'Bahas berita ini dengan KARIN', stripped, flags=re.IGNORECASE):
            skip_block = True
            continue
        if skip_block:
            # Selesai lewati jika bertemu heading baru atau paragraf panjang konten utama
            if stripped.startswith("#") or (len(stripped) > 80 and not re.search(r'membership|karin|akses|rp39|umpan balik', stripped, flags=re.IGNORECASE)):
                skip_block = False
            else:
                continue

        if combined_regex.match(stripped):
            continue

        cleaned_lines.append(line)

    result = "\n".join(cleaned_lines)

    if strip_images:
        # Bersihkan link gambar markdown: ![alt](url) -> ""
        result = re.sub(r'\!\[[^\]]*\]\([^\)]+\)', '', result)
        # Bersihkan link bergambar rusak [Meniti... ![alt]()](url)
        result = re.sub(r'\[[^\]]*\!\[[^\]]*\]\([^\)]*\)[^\]]*\]\([^\)]+\)', '', result)

    if strip_links:
        # Untuk CPT, hilangkan syntax URL mentah dan sisakan teks jangkar: [Sekolah Rakyat](url) -> Sekolah Rakyat
        result = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', result)

    # Normalisasi spasi berulang & multi-newline
    result = re.sub(r'\n{3,}', '\n\n', result).strip()

    # Deduplikasi paragraf identik berurutan (sering terjadi karena DOM mobile & desktop)
    paras = result.split("\n\n")
    deduped_paras = []
    seen_paras = set()
    for p in paras:
        p_clean = p.strip()
        if len(p_clean) > 40 and p_clean in seen_paras:
            continue
        if len(p_clean) > 40:
            seen_paras.add(p_clean)
        deduped_paras.append(p)

    return "\n\n".join(deduped_paras).strip()


def clean_and_convert_html_to_markdown(
    html_content: str,
    converter: str = "trafilatura",
    strip_links: bool = True,
    strip_images: bool = True
) -> str:
    """
    Membersihkan elemen HTML yang tidak relevan (script, style, iklan, dll)
    dan mengonversi HTML ke Markdown bersih menggunakan trafilatura, markdownify, atau html2text.
    Disesuaikan untuk kualitas data Continual Pre-Training (CPT).
    """
    if not html_content or not html_content.strip():
        return ""

    md_text = ""

    if converter == "trafilatura":
        try:
            import trafilatura
            # Ekstraksi dengan algoritma heuristic boilerpipe / density trafilatura
            md_text = trafilatura.extract(
                html_content,
                output_format="markdown",
                include_links=not strip_links,
                include_images=not strip_images,
                include_comments=False,
                include_tables=True,
                favor_precision=True,
                deduplicate=True
            ) or ""
        except Exception as e:
            print(f"    [Warning] Trafilatura error ({e}), mencoba fallback markdownify...")
            md_text = ""

    # Jika trafilatura menghasilkan string kosong (misal HTML fragment terlalu pendek/non-standard),
    # atau jika converter lain dipilih, gunakan BeautifulSoup + markdownify/html2text
    if not md_text:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, "html.parser")

            # Hapus tag non-konten
            unwanted_tags = [
                "script", "style", "noscript", "iframe", "svg",
                "button", "form", "nav", "header", "footer", "aside"
            ]
            for tag_name in unwanted_tags:
                for el in soup.find_all(tag_name):
                    el.decompose()

            # Hapus class/id pengganggu (komentar, reaksi, iklan, share)
            noise_selectors = [
                ".ads", ".advertisement", ".iklan",
                ".komentar", ".comment", ".comments",
                ".reactions", ".reaction", ".share", ".social-share",
                ".baca-juga", ".related-article", ".tag-list"
            ]
            for sel in noise_selectors:
                for el in soup.select(sel):
                    el.decompose()

            cleaned_html = str(soup)

            if converter == "html2text":
                import html2text
                h = html2text.HTML2Text()
                h.body_width = 0  # No hard line wrapping
                h.ignore_links = strip_links
                h.ignore_images = strip_images
                md_text = h.handle(cleaned_html)
            else:
                # Default fallback: markdownify
                import markdownify
                md_text = markdownify.markdownify(
                    cleaned_html,
                    heading_style="ATX",
                    bullets="*"
                )
        except Exception as e:
            print(f"    [Warning] Gagal konversi HTML ke Markdown ({e}), menggunakan teks mentah.")
            md_text = html_content.strip()

    # Post-processing khusus CPT Indonesia
    return clean_cpt_markdown(md_text, strip_links=strip_links, strip_images=strip_images)


def scrape_with_playwright(
    urls: List[str],
    css_paths_map: Optional[Dict[str, str]],
    default_css_path: str = "body",
    headless: bool = True,
    timeout: int = 30,
    convert_markdown: bool = True,
    converter: str = "trafilatura",
    strip_links: bool = True,
    strip_images: bool = True
) -> List[Dict[str, str]]:
    """Scrape web pages using Playwright with innerHTML extraction."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[Error] Package 'playwright' belum terinstal. Install dengan: pip install playwright && playwright install")
        sys.exit(1)

    results = []
    print(f"[*] Starting Playwright (headless={headless}, default_css_path='{default_css_path}', converter='{converter}')...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for idx, raw_url in enumerate(urls, 1):
            url = raw_url if raw_url.startswith(('http://', 'https://')) else f"https://{raw_url}"
            final_url = url
            css_path, is_def = get_css_selector_for_url(raw_url, css_paths_map, default_css_path, silent=True)

            print(f"[{idx}/{len(urls)}] Opening {url}...")
            scrapped_raw_html = ""
            status = "SUCCESS"

            try:
                # Handle Google News redirect URLs with networkidle wait
                if "google.com" in url.lower():
                    try:
                        page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
                    except Exception:
                        page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                else:
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                
                page.wait_for_timeout(1000)

                # Re-check CSS selector if redirected away from Google
                final_url = page.url
                if "google.com" in url.lower() and "google.com" not in final_url.lower():
                    resolved_selector, _ = get_css_selector_for_url(final_url, css_paths_map, default_css_path, silent=True)
                    css_path = resolved_selector
                    print(f"    -> Ter-redirect ke: {final_url} (Menggunakan CSS Path: '{css_path}')")
                else:
                    if not is_def:
                        print(f"    -> css-path url '{raw_url}' tidak didefinisikan, menggunakan default path ('{default_css_path}')")

                # Ekstraksi innerHTML
                scrapped_raw_html = page.evaluate(extract_content_js(), css_path)
                if not (scrapped_raw_html and scrapped_raw_html.strip()) and css_path != default_css_path:
                    fallbacks = [
                        f"{css_path}, article, [itemprop='articleBody'], .entry-content, .post-content, main",
                        default_css_path
                    ]
                    for fb in fallbacks:
                        fb_html = page.evaluate(extract_content_js(), fb)
                        if fb_html and fb_html.strip():
                            scrapped_raw_html = fb_html
                            css_path = fb
                            print(f"    -> Auto-fallback ekstraksi berhasil dengan: '{fb}'")
                            break

            except Exception as e:
                status = f"ERROR: {str(e)}"
                print(f"    -> Gagal mengekstrak {url}: {e}")

            # Konversi innerHTML ke Markdown jika diminta
            if convert_markdown and scrapped_raw_html:
                content = clean_and_convert_html_to_markdown(
                    scrapped_raw_html,
                    converter=converter,
                    strip_links=strip_links,
                    strip_images=strip_images
                )
            else:
                content = scrapped_raw_html.strip()

            if status == "SUCCESS" and not (content and content.strip()):
                status = "EMPTY: Konten kosong / tidak ditemukan teks"

            results.append({
                "url": final_url,
                "raw_url": raw_url,
                "css_path": css_path,
                "content": content,
                "status": status
            })

        browser.close()

    return results


def scrape_with_selenium(
    urls: List[str],
    css_paths_map: Optional[Dict[str, str]],
    default_css_path: str = "body",
    headless: bool = True,
    timeout: int = 30,
    convert_markdown: bool = True,
    converter: str = "trafilatura",
    strip_links: bool = True,
    strip_images: bool = True
) -> List[Dict[str, str]]:
    """Scrape web pages using Selenium with innerHTML extraction."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except ImportError:
        print("[Error] Package 'selenium' belum terinstal. Install dengan: pip install selenium")
        sys.exit(1)

    results = []
    print(f"[*] Starting Selenium (headless={headless}, default_css_path='{default_css_path}', converter='{converter}')...")

    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(timeout)

    try:
        for idx, raw_url in enumerate(urls, 1):
            url = raw_url if raw_url.startswith(('http://', 'https://')) else f"https://{raw_url}"
            final_url = url
            css_path, is_def = get_css_selector_for_url(raw_url, css_paths_map, default_css_path, silent=True)

            print(f"[{idx}/{len(urls)}] Opening {url}...")
            scrapped_raw_html = ""
            status = "SUCCESS"

            try:
                driver.get(url)
                if "google.com" in url.lower():
                    time.sleep(3)
                else:
                    time.sleep(1)

                final_url = driver.current_url
                if "google.com" in url.lower() and "google.com" not in final_url.lower():
                    resolved_selector, _ = get_css_selector_for_url(final_url, css_paths_map, default_css_path, silent=True)
                    css_path = resolved_selector
                    print(f"    -> Ter-redirect ke: {final_url} (Menggunakan CSS Path: '{css_path}')")
                else:
                    if not is_def:
                        print(f"    -> css-path url '{raw_url}' tidak didefinisikan, menggunakan default path ('{default_css_path}')")

                js_script = """
                let cssPath = arguments[0];
                let elements = Array.from(document.querySelectorAll(cssPath));
                if (elements.length === 0) return '';
                let topElements = elements.filter(el => {
                    return !elements.some(other => other !== el && other.contains(el));
                });
                let scrapped = '';
                topElements.forEach(el => {
                    scrapped += '\\n' + el.innerHTML;
                });
                return scrapped;
                """
                scrapped_raw_html = driver.execute_script(js_script, css_path) or ""
                if not (scrapped_raw_html and scrapped_raw_html.strip()) and css_path != default_css_path:
                    fallbacks = [
                        f"{css_path}, article, [itemprop='articleBody'], .entry-content, .post-content, main",
                        default_css_path
                    ]
                    for fb in fallbacks:
                        fb_html = driver.execute_script(js_script, fb) or ""
                        if fb_html and fb_html.strip():
                            scrapped_raw_html = fb_html
                            css_path = fb
                            print(f"    -> Auto-fallback ekstraksi berhasil dengan: '{fb}'")
                            break
            except Exception as e:
                status = f"ERROR: {str(e)}"
                print(f"    -> Gagal mengekstrak {url}: {e}")

            # Konversi innerHTML ke Markdown jika diminta
            if convert_markdown and scrapped_raw_html:
                content = clean_and_convert_html_to_markdown(
                    scrapped_raw_html,
                    converter=converter,
                    strip_links=strip_links,
                    strip_images=strip_images
                )
            else:
                content = scrapped_raw_html.strip()

            if status == "SUCCESS" and not (content and content.strip()):
                status = "EMPTY: Konten kosong / tidak ditemukan teks"

            results.append({
                "url": final_url,
                "raw_url": raw_url,
                "css_path": css_path,
                "content": content,
                "status": status
            })
    finally:
        driver.quit()

    return results


def read_url_list(urls_file: str) -> List[str]:
    """Read list of URLs from file."""
    if not os.path.isfile(urls_file):
        print(f"[Error] File daftar URL '{urls_file}' tidak ditemukan.")
        sys.exit(1)

    urls = []
    with open(urls_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Skip header line if present (e.g., 'url')
            if line.lower() in ['url', 'urls', 'link', 'links']:
                continue
            urls.append(line)

    if not urls:
        print(f"[Warning] Tidak ada URL yang ditemukan pada file '{urls_file}'.")

    return urls


def sanitize_filename(name: str) -> str:
    """Sanitize string for filename use."""
    sub = re.sub(r'[^\w\-_\. ]', '_', name)
    return re.sub(r'_+', '_', sub).strip('_')


def save_output(results: List[Dict[str, str]], output_target: str, output_mode: str):
    """Save clean scraped content to Markdown file(s) for training dataset."""
    valid_items = [item for item in results if item.get('content') and item['content'].strip()]
    failed_items = [item for item in results if not item.get('content') or not item['content'].strip()]

    # Determine log file path and output directory
    if output_mode == 'merge':
        out_dir = os.path.dirname(output_target)
        if not out_dir:
            out_dir = '.'
        base_name = os.path.splitext(os.path.basename(output_target))[0]
        log_file = os.path.join(out_dir, f"{base_name}.log")
    else:
        out_dir = output_target
        if output_target.endswith('.md') or output_target.endswith('.txt'):
            out_dir = os.path.splitext(output_target)[0]
        log_file = os.path.join(out_dir, "scraper.log")

    os.makedirs(out_dir, exist_ok=True)

    # Selalu tulis file log lengkap untuk seluruh URL yang diproses (baik SUCCESS maupun Gagal)
    with open(log_file, 'w', encoding='utf-8') as log_f:
        log_f.write(f"=== SCRAPING LOG / FAILURE REPORT ({time.strftime('%Y-%m-%d %H:%M:%S')}) ===\n")
        log_f.write(f"Total URL diproses: {len(results)}\n")
        log_f.write(f"Total Berhasil: {len(valid_items)}\n")
        log_f.write(f"Total Gagal / Kosong: {len(failed_items)}\n\n")

        for item in results:
            raw_u = item.get('raw_url', '')
            final_u = item.get('url', '')
            log_f.write(f"- URL: {raw_u or final_u}\n")
            if final_u and raw_u and final_u != raw_u:
                log_f.write(f"  Redirected URL: {final_u}\n")
            log_f.write(f"  CSS Path: {item.get('css_path', '')}\n")
            log_f.write(f"  Status: {item.get('status', 'SUCCESS')}\n\n")

    print(f"[INFO] Log scraping lengkap ({len(results)} URL) tersimpan di: {os.path.abspath(log_file)}")

    # Save clean dataset Markdown file(s)
    if output_mode == 'merge':
        clean_contents = [item['content'].strip() for item in valid_items]
        merged_text = "\n\n---\n\n".join(clean_contents)
        if merged_text:
            merged_text += "\n"

        with open(output_target, 'w', encoding='utf-8') as f:
            f.write(merged_text)

        print(f"[OK] {len(valid_items)} konten bersih berhasil digabungkan ke: {os.path.abspath(output_target)}")

    elif output_mode == 'each':
        for idx, item in enumerate(valid_items, 1):
            parsed = urlparse(item['url'])
            domain_slug = sanitize_filename(parsed.netloc or "url")
            filename = f"scraped_{idx:03d}_{domain_slug}.md"
            filepath = os.path.join(out_dir, filename)

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(item['content'].strip() + "\n")

        print(f"[OK] Scrapping selesai. {len(valid_items)} file clean dataset tersimpan pada folder: {os.path.abspath(out_dir)}")


def main():
    parser = argparse.ArgumentParser(
        description="Web Content Scraper - Ekstraksi isi artikel/web ke Markdown bersih (Playwright/Selenium)."
    )
    parser.add_argument(
        "--urls", "-u",
        default=None,
        help="Path ke file yang berisi daftar URL (misal: --urls=Windows/output/crawler_url.txt)"
    )
    parser.add_argument(
        "--rss-query", "-q",
        default=None,
        help="Query Google News RSS Dorking langsung (contoh: --rss-query='site:kompas.com \"pendidikan\" when:10d')"
    )
    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Path lokasi output file/folder hasil scrapping"
    )
    parser.add_argument(
        "--output-mode",
        choices=["each", "merge"],
        default="merge",
        help="Mode simpan output: 'each' (1 file per URL) atau 'merge' (gabung semua ke 1 file). Default: merge"
    )
    parser.add_argument(
        "--css-path",
        default="body",
        help="Default CSS Path selector ekstraksi elemen. Default: 'body' (sebelumnya 'body p')"
    )
    parser.add_argument(
        "--css-paths",
        default=None,
        help="Path ke file CSV pemetaan URL ke CSS Path (contoh header: url;css_path)"
    )
    parser.add_argument(
        "--converter",
        choices=["trafilatura", "markdownify", "html2text"],
        default="trafilatura",
        help="Library Python untuk konversi HTML ke Markdown: 'trafilatura', 'markdownify', atau 'html2text'. Default: trafilatura"
    )
    parser.add_argument(
        "--keep-links",
        action="store_true",
        help="Pertahankan link URL markdown mentah [teks](url). Default: false (dibersihkan jadi 'teks' untuk dataset CPT)"
    )
    parser.add_argument(
        "--keep-images",
        action="store_true",
        help="Pertahankan format markdown gambar ![alt](url). Default: false (dibersihkan untuk dataset CPT)"
    )
    parser.add_argument(
        "--raw-html",
        action="store_true",
        help="Simpan raw innerHTML tanpa konversi ke format Markdown"
    )
    parser.add_argument(
        "--keywords-file", "-kf",
        default=None,
        help="Path ke file daftar keyword (misal: Scrapper/keyword_text.txt) untuk mencari ke 30+ website target sekaligus"
    )
    parser.add_argument(
        "--targets-file", "-tf",
        default="Scrapper/css_paths.csv",
        help="Path file target website CSV untuk batch mode. Default: Scrapper/css_paths.csv"
    )
    parser.add_argument(
        "--limit-per-target",
        type=int,
        default=2,
        help="Batas artikel per target website saat menggunakan --keywords-file. Default: 2"
    )
    parser.add_argument(
        "--engine",
        choices=["playwright", "selenium"],
        default="playwright",
        help="Engine scraping yang digunakan: 'playwright' atau 'selenium'. Default: playwright"
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Jalankan browser dengan UI visual (non-headless mode)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Timeout waktu tunggu loading halaman dalam detik. Default: 30"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Batas jumlah URL yang diambil saat menggunakan --rss-query. Default: 10"
    )

    args = parser.parse_args()

    if not args.urls and not args.rss_query and not args.keywords_file:
        print("[Error] Salah satu parameter harus diberikan: --keywords-file, --urls, atau --rss-query")
        sys.exit(1)

    # 1. Dapatkan daftar URL (dari keywords-file ke 30+ target, rss-query tunggal, atau file URL)
    urls = []
    if args.keywords_file:
        print(f"[*] Mode Batch Keyword aktif. Membaca keywords dari: {args.keywords_file}...")
        try:
            from Scrapper.rss_crawler import load_keywords, load_targets, crawl_keywords_across_targets
        except ImportError:
            try:
                from rss_crawler import load_keywords, load_targets, crawl_keywords_across_targets
            except ImportError:
                import importlib.util
                current_dir = os.path.dirname(os.path.abspath(__file__))
                crawler_path = os.path.join(current_dir, "rss_crawler.py")
                spec = importlib.util.spec_from_file_location("rss_crawler", crawler_path)
                rss_mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(rss_mod)
                load_keywords = rss_mod.load_keywords
                load_targets = rss_mod.load_targets
                crawl_keywords_across_targets = rss_mod.crawl_keywords_across_targets

        keywords = load_keywords(args.keywords_file)
        targets = load_targets(args.targets_file)
        articles = crawl_keywords_across_targets(
            keywords=keywords,
            targets=targets,
            limit_per_target=args.limit_per_target
        )
        urls = [a["link"] for a in articles if a.get("link")]
        print(f"[*] Total {len(urls)} URL terkumpul dari 30+ target untuk {len(keywords)} keywords.")

    elif args.rss_query:
        print(f"[*] Mengambil URL dari Google News RSS untuk query: '{args.rss_query}'...")
        try:
            from Scrapper.rss_crawler import fetch_articles_from_rss
        except ImportError:
            try:
                from rss_crawler import fetch_articles_from_rss
            except ImportError:
                import importlib.util
                current_dir = os.path.dirname(os.path.abspath(__file__))
                crawler_path = os.path.join(current_dir, "rss_crawler.py")
                spec = importlib.util.spec_from_file_location("rss_crawler", crawler_path)
                rss_mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(rss_mod)
                fetch_articles_from_rss = rss_mod.fetch_articles_from_rss

        articles = fetch_articles_from_rss(args.rss_query, limit=args.limit)
        urls = [a["link"] for a in articles if a.get("link")]
        print(f"[*] Ditemukan {len(urls)} URL dari RSS feed.")
    else:
        urls = read_url_list(args.urls)

    if not urls:
        print("[!] Tidak ada URL yang valid untuk diproses.")
        sys.exit(0)

    # 2. Load CSS path mapping (prioritas flag CLI, fallback ke Scrapper/css_paths.csv otomatis)
    css_paths_map = None
    css_paths_file = args.css_paths
    if not css_paths_file:
        default_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)), "css_paths.csv")
        if os.path.isfile(default_csv):
            css_paths_file = default_csv

    if css_paths_file and os.path.isfile(css_paths_file):
        css_paths_map = load_css_paths(css_paths_file)

    # 3. Perform scraping
    headless_mode = not args.no_headless
    convert_md = not args.raw_html
    strip_links = not args.keep_links
    strip_images = not args.keep_images

    if args.engine == "playwright":
        results = scrape_with_playwright(
            urls=urls,
            css_paths_map=css_paths_map,
            default_css_path=args.css_path,
            headless=headless_mode,
            timeout=args.timeout,
            convert_markdown=convert_md,
            converter=args.converter,
            strip_links=strip_links,
            strip_images=strip_images
        )
    else:
        results = scrape_with_selenium(
            urls=urls,
            css_paths_map=css_paths_map,
            default_css_path=args.css_path,
            headless=headless_mode,
            timeout=args.timeout,
            convert_markdown=convert_md,
            converter=args.converter,
            strip_links=strip_links,
            strip_images=strip_images
        )

    # 4. Save results to markdown
    save_output(results, args.output, args.output_mode)


if __name__ == "__main__":
    main()
