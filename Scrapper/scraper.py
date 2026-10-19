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


def extract_page_title_js() -> str:
    """
    JavaScript snippet to extract the visual page headline / H1 article title from the DOM.
    Prioritizes article headline selectors over generic document title to avoid SEO brand suffixes.
    """
    return """
    () => {
        const isNoise = (txt) => {
            if (!txt || txt.length < 5) return true;
            const low = txt.toLowerCase();
            return /^(home|beranda|menu|indeks|index|login|daftar|rubrik|kategori|tag|tags|search|cari)$/i.test(low) ||
                   /blocked|cloudflare|attention required|just a moment|security check|access denied|robot|captcha/i.test(low);
        };

        const cleanTitleText = (txt) => {
            if (!txt) return '';
            let t = txt.trim().replace(/\\s+/g, ' ');
            // Strip common brand suffixes: " - Kompas.com", " | TEMPO.CO", " - Tirto.ID"
            t = t.replace(/\\s*[-–—|]\\s*(?:halaman\\s+\\d+|page\\s+\\d+|kompas|tempo|tirto|detik|cnn\\s+indonesia|antara|republika|kumparan|liputan6|sindonews|jawapos|suara|tribun|idntimes|mojok|inews|rri|zenius|ruangguru|historia|media\\s+indonesia).*/i, '').trim();
            // Don't accept bare domain names
            if (/^[a-z0-9\\.-]+\\.(com|id|co|co\\.id|org|net)$/i.test(t)) return '';
            return t;
        };

        // 1. Priority Article Headline H1 selectors
        const prioritySelectors = [
            "h1[itemprop='headline']",
            "[itemprop='headline'] h1",
            "[itemprop='headline']",
            "h1.article-title",
            "h1.read__title",
            "h1.detail__title",
            "h1.detail-title",
            "h1.post-title",
            "h1.entry-title",
            "h1.title",
            "h1.art-title",
            "#arttitle",
            ".read__title",
            ".detail__title",
            "article h1",
            "main h1",
            ".post-header h1",
            ".detail-header h1"
        ];
        for (const sel of prioritySelectors) {
            const el = document.querySelector(sel);
            if (el) {
                const text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
                if (!isNoise(text)) {
                    const cleaned = cleanTitleText(text);
                    if (cleaned.length > 5) return cleaned;
                }
            }
        }

        // 2. Generic H1 tags (excluding logos/brands)
        const allH1 = Array.from(document.querySelectorAll('h1'));
        for (const h1 of allH1) {
            const className = (h1.className || '') + ' ' + (h1.parentElement ? h1.parentElement.className : '');
            if (/logo|brand|site-title|header-logo|navbar/i.test(className)) continue;
            const text = (h1.innerText || h1.textContent || '').trim().replace(/\\s+/g, ' ');
            if (!isNoise(text)) {
                const cleaned = cleanTitleText(text);
                if (cleaned.length > 5) return cleaned;
            }
        }

        // 3. OpenGraph / Twitter meta title
        const ogTitle = document.querySelector("meta[property='og:title']")?.content ||
                        document.querySelector("meta[name='twitter:title']")?.content || '';
        if (ogTitle && !isNoise(ogTitle)) {
            const cleaned = cleanTitleText(ogTitle);
            if (cleaned.length > 5) return cleaned;
        }

        // 4. document.title fallback
        let docTitle = document.title || '';
        if (docTitle && !isNoise(docTitle)) {
            const cleaned = cleanTitleText(docTitle);
            if (cleaned.length > 5) return cleaned;
        }
        return '';
    }
    """


def clean_cpt_markdown(
    text: str,
    strip_links: bool = True,
    strip_images: bool = True,
    page_title: str = ""
) -> str:
    """
    Spesialis pembersih teks/markdown untuk dataset Continual Pre-Training (CPT).
    Menghilangkan editorial links, ad markers, widget AI, donasi, paywall, prefix media (datelines),
    dan noise umum berita Indonesia, serta menyematkan judul headline artikel di bagian teratas.
    """
    if not text or not text.strip():
        return ""

    # Deteksi proteksi Cloudflare / Bot Verification yang gagal dibypass
    if re.search(r'security service to protect against malicious bots|Performing security verification|Attention Required! \| Cloudflare|Just a moment\.\.\.|Sorry, you have been blocked', text, flags=re.IGNORECASE):
        return ""

    # Normalisasi spasi khusus
    text = text.replace('\xa0', ' ')

    lines = text.split("\n")
    cleaned_lines = []

    # Pola baris pengganggu yang harus dibuang seluruh barisnya
    noise_line_patterns = [
        # Penulis, Editor, Reporter, Pewarta, Redaktur, Kontributor, dsb.
        r'^\s*(?:\*\*)?(?:penulis|editor|reporter|pewarta|redaktur|jurnalis|kontributor|fotografer|alih\s+bahasa|penerjemah)\s*[:/].*',
        # Baca juga / Simak / Rekomendasi (dengan atau tanpa titik dua, bold atau tidak)
        r'^\s*(?:\*\*)?(?:baca\s+juga|baca\s+selengkapnya|baca\s+artikel|baca\s+berita|simak\s+juga|simak\s+video|lihat\s+juga|lihat\s+video|tonton\s+juga|artikel\s+terkait|berita\s+terkait|pilihan\s+editor|rekomendasi\s+berita|pilihan\s+untukmu)\b.*',
        # Copyright & Legal disclaimers
        r'^\s*(?:\*\*)?copyright\s+(?:©|@|\(c\)).*',
        r'^\s*dilarang\s+keras\s+(?:mengambil|menyalin|menyebarluaskan|melakukan\s+crawling).*',
        r'^\s*all\s+rights\s+reserved.*',
        r'^\s*\*?konten\s+ini\s+diolah\s+dengan\s+bantuan\s+ai\.?\*?.*',
        # Tag labels & Social hashtags
        r'^\s*TAG:\s*.*',
        r'^\s*#(?:Pendidikan|Kemendik|Sekolah|Berita)[a-zA-Z0-9_]+.*',
        # Citations & references (e.g. "Sumber Gambar:", "Gambar ‘...’ [Daring]. Tautan: ...")
        r'^\s*(?:\*\*)?(?:sumber|daftar)\s+(?:gambar|foto|ilustrasi|rujukan|referensi|pustaka)\s*:?.*$',
        r'^\s*Gambar\s+.*?(?:\[Daring\]|\\\[Daring\\\]|Tautan:|Diakses:).*$',
        # Inline image caption with source in italics (e.g. "*Malahayati (Sumber: kompasiana.com)*")
        r'^\s*[*_][^*_]+(?:\((?:sumber|foto|dok|doc|credit)[^)]*\))[^*_]*[*_]\s*$',
        # Blog promo CTA
        r'^\s*(?:Nah,\s*)?(?:supaya|biar|agar)\s+belajarmu\s+semakin\s+seru.*gabung.*yuk!?.*$',
        r'^\s*Siaran\s+Pers\s+Kemendik.*',
        r'^\s*Memuat\s+rekomendasi\s+berita.*',
        r'^\s*(?:\*\*)?\([a-z]{2,5}/[a-z]{2,5}\)(?:\*\*)?\s*$',
        # Standalone date/timestamp lines (e.g. "NU Online · Senin, 13 Januari 2025 | 16:00 WIB", "- 19 Okt 2026 08:57 WIB", "14 Oktober 2026")
        r'^\s*[-–—·•]?\s*(?:[A-Za-z\s\.-]+[·•–—-]\s*)?(?:Senin|Selasa|Rabu|Kamis|Jumat|Sabtu|Minggu)?,?\s*\d{1,2}\s+(?:Januari|Februari|Maret|April|Mei|Juni|Juli|Agustus|September|Oktober|November|Desember|Jan|Feb|Mar|Apr|Mei|Jun|Jul|Agu|Sep|Okt|Nov|Des)[a-z]*\s+\d{4}(?:\s*(?:[|•·–—-]|pukul)?\s*\d{1,2}[:\.]\d{2}(?:\s*(?:WIB|WITA|WIT))?)?\s*$',
        # Standalone agency dateline lines (e.g. "Jakarta, **NUOnline**", "JAKARTA, ANTARA")
        r'^\s*[*_~]{0,2}\s*(?:[A-Za-z\s]+[,\s]+)?(?:\*\*)?(?:nu\s*online|nuonline|antara|[a-z0-9\.-]+\.(?:com|co\.id|id|org))(?:\*\*)?\s*[*_~]{0,2}\s*[-–—:=]*\s*$',
        # Standalone photo/illustration credit lines (e.g. "Foto/Ilustrasi/Dok.SindoNews")
        r'^\s*(?:\*\*)?(?:ilustrasi|foto|sumber|dok\.|dokumentasi|tangkapan layar)\s*[:/].*$',
        r'^\s*#{1,6}\s*(?:Headline|Rekomendasi|Kategori|Tag|Tags|Topik|Berita)\s*$',
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
        r'^\s*-\s*Akses\s+.*?(?:Tempo\+|edisi\s+mingguan).*',
        r'^\s*-\s*Baca\s+dengan\s+lebih\s+sedikit\s+gangguan\s+iklan.*',
        r'^\s*-\s*Fitur\s+baca\s+cepat.*',
        r'^\s*-\s*Anda\s+Mendukung\s+Independensi\s+Jurnalisme\s+Tempo.*',
        r'^\s*Lihat\s+Benefit\s+Lainnya\s*$',
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
        r'^\s*\(INFO\s+KINI\)\s*$',         # Tirto tag
        r'^\s*#\s*[a-z0-9\.-]+\.(?:com|id|co|org|net)\s*$',  # Bare domain header like '# mediaindonesia.com'
    ]

    combined_regex = re.compile("|".join(f"(?:{p})" for p in noise_line_patterns), flags=re.IGNORECASE)

    # Pola agency dateline di awal paragraf berita (tirto.id -, KOMPAS.com -, MOJOK.CO -, dll)
    media_names = [
        r'tirto(?:\.id)?',
        r'kompas(?:\.com|\.id)?',
        r'tempo(?:\.co|\.com)?',
        r'antara(?:\s+news)?',
        r'detik(?:com|news|edu|finance|hot|inet)?',
        r'cnn\s+indonesia',
        r'liputan6(?:\.com)?',
        r'kumparan(?:\.com)?',
        r'suara(?:\.com)?',
        r'idntimes(?:\.com)?|idn\s+times',
        r'mojok(?:\.co)?',
        r'bisnis(?:\.com)?',
        r'sindonews(?:\.com)?',
        r'republika(?:\.co\.id)?',
        r'jawapos(?:\.com)?',
        r'suaramerdeka(?:\.com)?|suara\s+merdeka',
        r'inews(?:\s+[a-zA-Z0-9\.-]+)?',
        r'tribun(?:news)?(?:\.com)?(?:\s+[a-zA-Z]+)?',
        r'merdeka\.com',
        r'viva(?:\.co\.id)?',
        r'katadata(?:\.co\.id)?',
        r'kontan(?:\.co\.id)?',
        r'cnbc\s+indonesia',
        r'jpnn(?:\.com)?',
        r'mediaindonesia(?:\.com)?|media\s+indonesia',
        r'rri(?:\.co\.id)?',
        r'nu\s*online|nuonline',
        r'[a-z0-9\.-]+\.(?:com|co\.id|id)'
    ]
    media_pattern = "|".join(f"(?:{m})" for m in media_names)

    standalone_dateline_regex = re.compile(
        r'^\s*[*_~]{0,2}\s*(?:[A-Za-z\s]+[,\s]+)?(?:' + media_pattern + r')(?:[,\s]+[A-Za-z\s]+)?\s*[-–—:=]*\s*[*_~]{0,2}\s*[-–—:=]{1,3}\s*$',
        re.IGNORECASE
    )

    inline_dateline_regex = re.compile(
        r'^\s*(?:'
            r'[*_~]{0,2}\s*(?:[A-Za-z\s]+[,\(]\s*(?:ANTARA|' + media_pattern + r')\)?|(?:ANTARA|' + media_pattern + r')[,\s]+[A-Za-z\s]+|(?:ANTARA|' + media_pattern + r'))[,;\s]*[-–—:\x97\\]+\s*[*_~]{0,2}\s*[-–—:\x97\\]*\s*|'
            r'[*_~]{0,2}\s*[A-Z\s]{3,20}\s*[*_~]{0,2}\s*\\?[-–—:\x97]+\s*|'
            r'[*_~]{0,2}\s*(?:[A-Za-z\s]+[,\s]+)?\d{1,2}\s+(?:Januari|Februari|Maret|April|Mei|Juni|Juli|Agustus|September|Oktober|November|Desember|[A-Z][a-z]{2})\s+\d{4}\s*[*_~]{0,2}\s*\\?[-–—:]+\s*'
        r')',
        re.IGNORECASE
    )

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
        # Bersihkan link kosong [](...)
        result = re.sub(r'\[\s*\]\([^\)]+\)', '', result)
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

    # Hapus standalone datelines, inline datelines, serta lead image caption pada paragraf pembuka
    dateline_stripped = False
    filtered_paras = []
    for p in deduped_paras:
        p_strip = p.strip()
        if not p_strip:
            continue
        if standalone_dateline_regex.match(p_strip):
            continue

        # Cek apakah paragraf ini merupakan caption gambar / teaser visual di awal artikel
        is_caption = False
        if not filtered_paras or (len(filtered_paras) == 1 and filtered_paras[0].startswith('#')):
            if re.match(r'^\s*[–—]{1,2}\s+', p_strip):
                is_caption = True
            elif re.match(r'^\s*[*_][^*_]+[*_]\s*$', p_strip) and len(p_strip) < 250:
                is_caption = True
            elif re.search(r'\((?:sumber|foto|dok|doc|antara|reuters|afp)[^)]*\)\s*$', p_strip, re.IGNORECASE):
                is_caption = True
            elif re.search(r'(?:foto|sumber|dok\.|dokumentasi|ilustrasi|tangkapan layar)\s*[:/].*$', p_strip, re.IGNORECASE) and len(p_strip) < 300:
                is_caption = True

        if is_caption:
            continue

        if not dateline_stripped and not p_strip.startswith('#') and not p_strip.startswith('- '):
            p_subbed = inline_dateline_regex.sub('', p_strip)
            if p_subbed != p_strip:
                dateline_stripped = True
                # Jika setelah dateline dibuang, sisanya adalah caption miring murni: buang juga
                if re.match(r'^\s*[*_][^*_]+[*_]\s*$', p_subbed.strip()) and len(p_subbed.strip()) < 250:
                    continue
                filtered_paras.append(p_subbed)
                continue

        filtered_paras.append(p)

    final_content = "\n\n".join(filtered_paras).strip()

    # Prepend page headline jika diberikan dan belum ada di awal teks
    if page_title and page_title.strip():
        clean_title = re.sub(r'\s+', ' ', page_title.strip())
        first_lines = [l.strip() for l in final_content.split("\n") if l.strip()][:3]
        has_title = False
        norm_title = re.sub(r'[^\w\s]', '', clean_title).lower().strip()
        for fl in first_lines:
            fl_clean = re.sub(r'^#+\s*', '', fl)
            fl_norm = re.sub(r'[^\w\s]', '', fl_clean).lower().strip()
            if norm_title and (norm_title in fl_norm or fl_norm in norm_title) and len(fl_norm) > 10:
                has_title = True
                break
        if not has_title and clean_title:
            final_content = f"# {clean_title}\n\n{final_content}".strip()

    return final_content


def clean_and_convert_html_to_markdown(
    html_content: str,
    converter: str = "trafilatura",
    strip_links: bool = True,
    strip_images: bool = True,
    page_title: str = ""
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
    return clean_cpt_markdown(md_text, strip_links=strip_links, strip_images=strip_images, page_title=page_title)


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

        # Abort gambar, media, dan font untuk mempercepat crawling teks hingga 5x-10x lipat
        try:
            page.route(
                "**/*",
                lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_()
            )
        except Exception:
            pass

        for idx, raw_url in enumerate(urls, 1):
            url = raw_url if raw_url.startswith(('http://', 'https://')) else f"https://{raw_url}"
            final_url = url
            css_path, is_def = get_css_selector_for_url(raw_url, css_paths_map, default_css_path, silent=True)

            print(f"[{idx}/{len(urls)}] Opening {url}...")
            scrapped_raw_html = ""
            page_title = ""
            status = "SUCCESS"

            try:
                # Navigasi cepat dengan batas timeout wajar (default 15s) menggunakan domcontentloaded
                nav_timeout = min(timeout, 15) * 1000
                page.goto(url, wait_until="domcontentloaded", timeout=nav_timeout)

                # Jika link Google News RSS, tunggu sampai redirect ke domain target selesai
                if "google.com" in page.url.lower():
                    try:
                        page.wait_for_url(lambda u_str: "google.com" not in u_str.lower(), timeout=6000)
                    except Exception:
                        pass

                # Pastikan DOM halaman target sudah siap
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=4000)
                except Exception:
                    pass

                # Re-check CSS selector setelah ter-redirect
                final_url = page.url

                # Normalisasi URL jika Google News RSS mengarah ke gallery/image viewer (misal kompasiana.com/image/...)
                if "kompasiana.com/image/" in final_url.lower():
                    clean_kurl = final_url.replace("/image/", "/")
                    try:
                        page.goto(clean_kurl, wait_until="domcontentloaded", timeout=8000)
                        final_url = page.url
                    except Exception:
                        pass

                # Auto-expand multi-page articles to single page (?page=all atau ?single=1)
                if any(dom in final_url.lower() for dom in ["kompas.com", "tribunnews.com", "suaramerdeka.com"]) and "page=all" not in final_url.lower():
                    sep = "&" if "?" in final_url else "?"
                    paged_url = f"{final_url}{sep}page=all"
                    try:
                        page.goto(paged_url, wait_until="domcontentloaded", timeout=8000)
                        final_url = page.url
                    except Exception:
                        pass
                elif "detik.com" in final_url.lower() and "single=1" not in final_url.lower():
                    sep = "&" if "?" in final_url else "?"
                    paged_url = f"{final_url}{sep}single=1"
                    try:
                        page.goto(paged_url, wait_until="domcontentloaded", timeout=8000)
                        final_url = page.url
                    except Exception:
                        pass

                if "google.com" in url.lower() and "google.com" not in final_url.lower():
                    resolved_selector, _ = get_css_selector_for_url(final_url, css_paths_map, default_css_path, silent=True)
                    css_path = resolved_selector
                    print(f"    -> Ter-redirect ke: {final_url} (Menggunakan CSS Path: '{css_path}')")
                else:
                    if not is_def:
                        print(f"    -> css-path url '{raw_url}' tidak didefinisikan, menggunakan default path ('{default_css_path}')")

                # Ekstraksi headline dan innerHTML
                page_title = page.evaluate(extract_page_title_js()) or ""
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
                    strip_images=strip_images,
                    page_title=page_title
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
            page_title = ""
            status = "SUCCESS"

            try:
                driver.get(url)
                if "google.com" in url.lower():
                    time.sleep(3)
                else:
                    time.sleep(1)

                final_url = driver.current_url

                # Normalisasi URL jika Google News RSS mengarah ke gallery/image viewer (misal kompasiana.com/image/...)
                if "kompasiana.com/image/" in final_url.lower():
                    clean_kurl = final_url.replace("/image/", "/")
                    try:
                        driver.get(clean_kurl)
                        time.sleep(1)
                        final_url = driver.current_url
                    except Exception:
                        pass

                # Auto-expand multi-page articles to single page (?page=all atau ?single=1)
                if any(dom in final_url.lower() for dom in ["kompas.com", "tribunnews.com", "suaramerdeka.com"]) and "page=all" not in final_url.lower():
                    sep = "&" if "?" in final_url else "?"
                    paged_url = f"{final_url}{sep}page=all"
                    try:
                        driver.get(paged_url)
                        time.sleep(1)
                        final_url = driver.current_url
                    except Exception:
                        pass
                elif "detik.com" in final_url.lower() and "single=1" not in final_url.lower():
                    sep = "&" if "?" in final_url else "?"
                    paged_url = f"{final_url}{sep}single=1"
                    try:
                        driver.get(paged_url)
                        time.sleep(1)
                        final_url = driver.current_url
                    except Exception:
                        pass

                if "google.com" in url.lower() and "google.com" not in final_url.lower():
                    resolved_selector, _ = get_css_selector_for_url(final_url, css_paths_map, default_css_path, silent=True)
                    css_path = resolved_selector
                    print(f"    -> Ter-redirect ke: {final_url} (Menggunakan CSS Path: '{css_path}')")
                else:
                    if not is_def:
                        print(f"    -> css-path url '{raw_url}' tidak didefinisikan, menggunakan default path ('{default_css_path}')")

                title_js = f"let fn = {extract_page_title_js()}; return fn();"
                try:
                    page_title = driver.execute_script(title_js) or ""
                except Exception:
                    page_title = ""

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
                    strip_images=strip_images,
                    page_title=page_title
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
