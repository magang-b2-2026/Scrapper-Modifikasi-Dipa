#!/usr/bin/env python3
"""
Google News RSS & Google Dorking URL Collector
Mengambil daftar URL artikel dari Google News RSS feed menggunakan query Google Dorking.
Mendukung input query tunggal (--query) ATAU batch dari file keyword (--keywords-file)
yang otomatis di-query ke 30+ website (media berita & non-berita) dengan kondisi when masing-masing.
"""

import argparse
import concurrent.futures
import csv
import os
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional


def normalize_query_for_google(query: str) -> str:
    """
    Google Search & News RSS tidak mengenali single quotes ('...') sebagai operator exact match,
    melainkan mencari karakter kutip secara literal sehingga menghasilkan 0 hasil.
    Fungsi ini otomatis mengubah 'keyword' menjadi "keyword".
    """
    import re
    cleaned = re.sub(r"(?<!\w)'([^']+)'(?!\w)", r'"\1"', query.strip())
    return cleaned


def build_rss_url(query: str, hl: str = "id", gl: str = "ID", ceid: str = "ID:id") -> str:
    """Membentuk URL Google News RSS feed dengan query dan parameter lokasi Indonesia."""
    norm_q = normalize_query_for_google(query)
    encoded_q = urllib.parse.quote(norm_q)
    return f"https://news.google.com/rss/search?q={encoded_q}&hl={hl}&gl={gl}&ceid={ceid}"


def fetch_articles_from_rss(
    query: str,
    hl: str = "id",
    gl: str = "ID",
    ceid: str = "ID:id",
    limit: Optional[int] = None
) -> List[Dict[str, str]]:
    """
    Mengambil dan mem-parsing artikel dari Google News RSS XML.
    Mengembalikan list dictionary: {'title': ..., 'link': ..., 'pubDate': ..., 'source': ...}
    """
    rss_url = build_rss_url(query, hl=hl, gl=gl, ceid=ceid)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "id,en-US;q=0.9,en;q=0.8",
    }
    req = urllib.request.Request(rss_url, headers=headers)

    articles = []
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                xml_data = response.read()
                root = ET.fromstring(xml_data)
                items = root.findall("./channel/item")

                for item in items:
                    title_el = item.find("title")
                    link_el = item.find("link")
                    pub_el = item.find("pubDate")
                    source_el = item.find("source")

                    title = title_el.text if title_el is not None and title_el.text else ""
                    link = link_el.text if link_el is not None and link_el.text else ""
                    pub_date = pub_el.text if pub_el is not None and pub_el.text else ""
                    source = source_el.text if source_el is not None and source_el.text else ""

                    if link:
                        articles.append({
                            "title": title,
                            "link": link,
                            "pubDate": pub_date,
                            "source": source,
                            "query": query
                        })

                    if limit and len(articles) >= limit:
                        break
            # Berhasil, hentikan retry loop
            break

        except Exception as e:
            if attempt < max_retries:
                import time
                time.sleep(1.0 * attempt)
            else:
                pass

    return articles


def load_keywords(keywords_file: str) -> List[str]:
    """Membaca daftar keyword dari file teks (1 baris 1 keyword, abaikan baris #)."""
    if not os.path.isfile(keywords_file):
        print(f"[Error] File keyword '{keywords_file}' tidak ditemukan.")
        sys.exit(1)

    keywords = []
    with open(keywords_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                keywords.append(line)
    return keywords


def load_targets(targets_file: str) -> List[Dict[str, str]]:
    """
    Membaca target website langsung dari css_paths.csv.
    Mendukung kolom: url, css_path, dan opsional: when.
    """
    if not os.path.isfile(targets_file):
        print(f"[Error] File targets '{targets_file}' tidak ditemukan.")
        sys.exit(1)

    targets = []
    with open(targets_file, "r", encoding="utf-8-sig") as f:
        first_line = f.readline()
        f.seek(0)
        delimiter = ";" if ";" in first_line else ","
        reader = csv.DictReader(f, delimiter=delimiter)

        for row in reader:
            domain = row.get("url", "") or row.get("domain", "")
            domain = domain.strip().lower()
            if not domain:
                continue

            name = domain
            when_val = row.get("when", "") or row.get("when_condition", "")
            when_val = when_val.strip()

            when_clause = ""
            if "when:10d" in when_val:
                when_clause = "when:10d"
            elif "when:30d" in when_val:
                when_clause = "when:30d"
            elif when_val.startswith("when:"):
                when_clause = when_val

            targets.append({
                "name": name,
                "domain": domain,
                "when_clause": when_clause,
                "css_path": row.get("css_path", "body")
            })

    return targets


def crawl_keywords_across_targets(
    keywords: List[str],
    targets: List[Dict[str, str]],
    limit_per_target: int = 2,
    max_workers: int = 5,
    hl: str = "id",
    gl: str = "ID",
    ceid: str = "ID:id"
) -> List[Dict[str, str]]:
    """
    Mengambil artikel Google News RSS secara paralel untuk setiap keyword di seluruh target.
    """
    all_articles = []
    total_combinations = len(keywords) * len(targets)
    print(f"[*] Menjalankan batch crawl: {len(keywords)} keyword x {len(targets)} target domain = {total_combinations} pencarian...")

    tasks = []
    for kw in keywords:
        for tgt in targets:
            domain = tgt["domain"]
            when_clause = tgt["when_clause"]
            # Bentuk query dorking
            query = f'site:{domain} "{kw}" {when_clause}'.strip()
            tasks.append((kw, tgt, query))

    found_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(fetch_articles_from_rss, q, hl, gl, ceid, limit_per_target): (kw, tgt, q)
            for (kw, tgt, q) in tasks
        }

        for idx, future in enumerate(concurrent.futures.as_completed(future_map), 1):
            kw, tgt, q = future_map[future]
            try:
                articles = future.result()
                if articles:
                    for a in articles:
                        a["keyword"] = kw
                        a["target_domain"] = tgt["domain"]
                        a["target_name"] = tgt["name"]
                    all_articles.extend(articles)
                    found_count += len(articles)
                    print(f"  [{idx}/{total_combinations}] {tgt['name']} ('{kw}') -> {len(articles)} artikel")
            except Exception:
                pass

    print(f"[OK] Selesai batch crawl. Total URL terkumpul: {len(all_articles)}")
    return all_articles


def save_urls_to_file(articles: List[Dict[str, str]], output_file: str, append: bool = False):
    """Menyimpan daftar link artikel ke file teks."""
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    mode = "a" if append else "w"

    existing_urls = set()
    if append and os.path.exists(output_file):
        with open(output_file, "r", encoding="utf-8") as f:
            for line in f:
                existing_urls.add(line.strip())

    written_count = 0
    with open(output_file, mode, encoding="utf-8") as f:
        # Tulis header jika file baru
        if not append or not existing_urls:
            f.write("url\n")

        for art in articles:
            url = art["link"].strip()
            if url and url not in existing_urls:
                f.write(f"{url}\n")
                existing_urls.add(url)
                written_count += 1

    print(f"[OK] {written_count} URL artikel berhasil disimpan ke: {os.path.abspath(output_file)}")


def main():
    parser = argparse.ArgumentParser(
        description="Google News RSS & Google Dorking Batch Collector (hl=id, gl=ID, ceid=ID:id)"
    )
    parser.add_argument(
        "--keywords-file", "-kf",
        type=str,
        default=None,
        help="Path file daftar keyword (misal: Scrapper/keyword_text.txt) untuk mencari di 30+ website target"
    )
    parser.add_argument(
        "--targets-file", "-tf",
        type=str,
        default="Scrapper/css_paths.csv",
        help="Path file target website CSV (default: Scrapper/css_paths.csv)"
    )
    parser.add_argument(
        "--limit-per-target",
        type=int,
        default=2,
        help="Batas maksimal artikel per target per keyword saat batch mode. Default: 2"
    )
    parser.add_argument(
        "--query", "-q",
        type=str,
        default=None,
        help="Query pencarian / dorking tunggal (contoh: 'site:kompas.com \"pendidikan\" when:10d')"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="Scrapper/sample_urls.txt",
        help="Path file output untuk menyimpan URL. Default: Scrapper/sample_urls.txt"
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=50,
        help="Batas maksimal URL untuk mode query tunggal. Default: 50"
    )
    parser.add_argument(
        "--hl",
        type=str,
        default="id",
        help="Parameter bahasa Google News (default: id)"
    )
    parser.add_argument(
        "--gl",
        type=str,
        default="ID",
        help="Parameter negara/lokasi Google News (default: ID)"
    )
    parser.add_argument(
        "--ceid",
        type=str,
        default="ID:id",
        help="Parameter Country Edition Google News (default: ID:id)"
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Tambahkan ke file yang sudah ada (tidak menimpa)"
    )

    args = parser.parse_args()

    # Mode 1: Batch crawl menggunakan keywords-file ke 30+ target
    if args.keywords_file:
        keywords = load_keywords(args.keywords_file)
        targets = load_targets(args.targets_file)
        articles = crawl_keywords_across_targets(
            keywords=keywords,
            targets=targets,
            limit_per_target=args.limit_per_target,
            hl=args.hl,
            gl=args.gl,
            ceid=args.ceid
        )
        if articles:
            save_urls_to_file(articles, args.output, append=args.append)
        else:
            print("[!] Tidak ada artikel yang ditemukan dari kombinasi keyword & target.")
        return

    # Mode 2: Query tunggal
    query = args.query if args.query else 'site:kompas.com "pendidikan" when:10d'
    print(f"\n[+] Memproses query tunggal: {query}")
    articles = fetch_articles_from_rss(query, hl=args.hl, gl=args.gl, ceid=args.ceid, limit=args.limit)
    if articles:
        print(f"    Ditemukan {len(articles)} artikel")
        save_urls_to_file(articles, args.output, append=args.append)
    else:
        print("[!] Tidak ada artikel yang ditemukan dari query tersebut.")


if __name__ == "__main__":
    main()
