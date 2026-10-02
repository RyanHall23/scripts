#!/usr/bin/env python3
"""
XportReddit2 - Unified Reddit to X Thread Automation

Merges:
  - parse_reddit_export.py  (Reddit HTML export parsing)
  - sort_saved_posts.py     (sort by post age)
  - XportReddit.py          (Selenium X/Twitter posting)

Supported input formats:
  - saveddit4reddit CSV  (semicolon-delimited, e.g. from Saveddit)
  - Reddit HTML export   (reddit_export.html)
  - Previously generated JSON (reddit_saved_posts.json)
"""

import csv
import json
import os
import re
import shutil
import socket
import subprocess
import time
import random
from datetime import datetime
from io import StringIO
from pathlib import Path

import requests
from tqdm import tqdm
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from seleniumbase import Driver

# ============================================================
# CONFIGURATION
# ============================================================
UPLOAD_TIMEOUT = 90      # Max seconds to wait for media uploads
POST_RETRY_ATTEMPTS = 5  # Number of times to retry posting
SAVED_POSTS_FILE = "reddit_saved_posts.json"
POSTED_URLS_FILE = "reddit_posted_urls.json"

# Browser session cookies — saved after first login, reused automatically.
# Delete x_session_cookies.json next to the script to force a fresh login.
# ============================================================


# ============================================================
# INPUT PARSING — HTML EXPORT
# ============================================================

def extract_urls_from_html(html_file):
    """Extract post URLs from a Reddit HTML export file."""
    with open(html_file, 'r', encoding='utf-8') as f:
        html_content = f.read()

    urls = []
    seen = set()

    print("=== Debugging HTML content ===")
    if "THREAD" in html_content:
        print("Found 'THREAD' text in file")
        for line in html_content.split('\n'):
            if 'THREAD' in line:
                print(f"Sample line: {line[:200]}")
                break
    else:
        print("No 'THREAD' text found in file")

    if "reddit.com/r/" in html_content:
        print("Found 'reddit.com/r/' in file")
        for line in html_content.split('\n'):
            if 'reddit.com/r/' in line and 'comments' in line:
                print(f"Sample reddit line: {line[:200]}")
                break
    print("==============================\n")

    pattern1 = r'<a\s+href=["\']+(https://www\.reddit\.com/r/[^/]+/comments/[^"\']+)["\']>\s*THREAD\s*</a>'
    matches1 = re.findall(pattern1, html_content, re.IGNORECASE | re.DOTALL)
    print(f"Pattern 1 (strict THREAD): {len(matches1)} matches")

    pattern2 = r'href=["\']+(https://www\.reddit\.com/r/[^/]+/comments/[^"\']+)["\']'
    matches2 = re.findall(pattern2, html_content)
    print(f"Pattern 2 (any reddit comments href): {len(matches2)} matches")

    all_matches = matches1 if matches1 else matches2

    for match in all_matches:
        url = match.split('?')[0].split('#')[0].rstrip('/')
        if url not in seen:
            seen.add(url)
            urls.append(url)

    return urls


# ============================================================
# INPUT PARSING — CSV EXPORT (saveddit4reddit format)
# ============================================================

def parse_csv_export(csv_file):
    """
    Parse a saveddit4reddit-style CSV export.

    Expected header (semicolon-delimited, double-quoted fields):
        author;comments;created;id;image;score;subreddit;text;title;url

    Returns:
        tuple: (urls: list[str], title_cache: dict[str, str], rows_cache: dict[str, dict])
               title_cache maps URL -> post title so API calls can be skipped.
               rows_cache maps URL -> full CSV row dict for use in categorization output.
    """
    urls = []
    title_cache = {}
    rows_cache = {}
    seen = set()

    with open(csv_file, 'r', encoding='utf-8') as f:
        content = f.read()

    reader = csv.DictReader(StringIO(content), delimiter=';', quotechar='"')

    for row in reader:
        url = (row.get('url') or '').strip().strip('"')
        title = (row.get('title') or '').strip().strip('"')

        # Only keep proper Reddit post URLs
        if not url or 'reddit.com/r/' not in url or '/comments/' not in url:
            continue

        url = url.split('?')[0].split('#')[0].rstrip('/')

        if url not in seen:
            seen.add(url)
            urls.append(url)
            if title:
                title_cache[url] = title
            rows_cache[url] = dict(row)

    print(f"✅ Parsed {len(urls)} posts from CSV")
    return urls, title_cache, rows_cache


# ============================================================
# SORTING — oldest post first (by Reddit base-36 post ID)
# ============================================================

def extract_post_id(url):
    """Extract the base-36 post ID from a Reddit post URL."""
    match = re.search(r'/comments/([a-z0-9]+)/', url)
    return match.group(1) if match else None


def sort_posts_oldest_first(urls):
    """Return urls sorted from oldest to newest post."""
    posts_with_ids = []
    for url in urls:
        post_id = extract_post_id(url)
        if post_id:
            try:
                posts_with_ids.append((int(post_id, 36), url))
            except ValueError:
                posts_with_ids.append((0, url))
        else:
            posts_with_ids.append((0, url))

    posts_with_ids.sort(key=lambda x: x[0])
    return [url for _, url in posts_with_ids]


# ============================================================
# SUBREDDIT CATEGORIZATION  (pre-requisite sort step)
# ============================================================

def extract_subreddit(url):
    """Extract subreddit name from a Reddit post URL."""
    match = re.search(r'/r/([^/]+)/', url)
    return match.group(1) if match else 'unknown'


def _check_filename_routing(source_path):
    """
    Inspect the source filename to determine how to proceed.

    Returns:
        str:
          'direct'  — filename contains 'main' or 'secondary', or is the
                      progress file (reddit_saved_posts) → skip categorization
          'ignored' — filename contains 'ignored' → error out
          'sort'    — generic file → run the interactive categorization step
    """
    if source_path is None:
        return 'sort'
    name = source_path.stem.lower()  # filename without extension
    if 'ignored' in name:
        return 'ignored'
    if 'main' in name or 'secondary' in name or name == 'reddit_saved_posts':
        return 'direct'
    return 'sort'


def _write_categorized_csvs(categorized, title_cache, rows_cache, out_dir):
    """
    Write main / secondary / ignored URL lists to dated CSV files.

    Args:
        categorized: dict  {'main': [...], 'secondary': [...], 'ignored': [...]}
        title_cache: dict  url -> title
        rows_cache:  dict  url -> original CSV row dict (may be empty)
        out_dir:     Path  output directory

    Returns:
        dict  category -> output Path
    """
    date_str = datetime.now().strftime('%Y%m%d')
    output_paths = {}

    for category, urls in categorized.items():
        if not urls:
            continue
        out_file = out_dir / f"{date_str}_{category}.csv"
        with open(out_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f, delimiter=';', quotechar='"', quoting=csv.QUOTE_ALL)
            writer.writerow(['subreddit', 'title', 'url', 'image'])
            for url in urls:
                subreddit = extract_subreddit(url)
                title = title_cache.get(url, '')
                image = ''
                if url in rows_cache:
                    row = rows_cache[url]
                    subreddit = row.get('subreddit', subreddit).strip().strip('"')
                    title = row.get('title', title).strip().strip('"')
                    image = row.get('image', '').strip().strip('"')
                writer.writerow([subreddit, title, url, image])
        output_paths[category] = out_file
        print(f"  💾 {out_file.name}  ({len(urls)} posts)")

    return output_paths


def categorize_subreddits(urls, title_cache, rows_cache, source_path):
    """
    Interactive step: group posts by subreddit and let the user assign
    each subreddit to main / secondary / ignored.

    Saves three dated CSV files next to the source file, then returns
    only the 'main' URL list so the posting loop can continue.

    Args:
        urls:         sorted list of Reddit post URLs
        title_cache:  dict url -> title
        rows_cache:   dict url -> original CSV row dict
        source_path:  Path of the loaded source file (sets output dir)

    Returns:
        list[str]: URLs assigned to 'main'
    """
    print("\n" + "="*60)
    print("  SUBREDDIT CATEGORIZATION")
    print("="*60)
    print("Assign each subreddit to a posting batch:")
    print("  m  / main       → post NOW  (this run)")
    print("  s  / secondary  → post LATER  (saved to secondary file)")
    print("  i  / ignore     → skip entirely")
    print("  all m/s/i       → assign ALL remaining to that category")
    print()

    # Group URLs by subreddit, preserving order of first appearance
    subreddit_map = {}          # subreddit -> [url, ...]
    for url in urls:
        sub = extract_subreddit(url)
        if url in rows_cache:
            sub = rows_cache[url].get('subreddit', sub).strip().strip('"')
        subreddit_map.setdefault(sub, []).append(url)

    subreddits = list(subreddit_map.keys())
    total_subs = len(subreddits)
    print(f"Found {total_subs} subreddit(s) across {len(urls)} posts.\n")

    choice_map = {
        'm': 'main',       'main': 'main',
        's': 'secondary',  'secondary': 'secondary',
        'i': 'ignored',    'ignore': 'ignored',   'ignored': 'ignored',
    }
    assignments = {}    # subreddit -> 'main' | 'secondary' | 'ignored'
    bulk_assign = None

    for idx, sub in enumerate(subreddits, 1):
        sub_urls = subreddit_map[sub]

        if bulk_assign:
            assignments[sub] = bulk_assign
            continue

        print(f"[{idx}/{total_subs}] r/{sub}  ({len(sub_urls)} post{'s' if len(sub_urls) != 1 else ''})")

        # Show up to 3 example titles
        shown = 0
        for url in sub_urls:
            if shown >= 3:
                break
            title = title_cache.get(url, '')
            if url in rows_cache:
                title = rows_cache[url].get('title', title).strip().strip('"')
            if title:
                print(f"     • {title[:80]}")
                shown += 1

        while True:
            raw = input("  Category [m/s/i  or  all m/s/i]: ").strip().lower()

            if raw.startswith('all'):
                parts = raw.split()
                bulk_key = parts[1] if len(parts) > 1 else ''
                if bulk_key in choice_map:
                    bulk_assign = choice_map[bulk_key]
                    assignments[sub] = bulk_assign
                    remaining = total_subs - idx
                    print(f"  → '{bulk_assign}' applied to this and all {remaining} remaining subreddit(s).")
                    break
                print("  ⚠️  Use:  all m   all s   or   all i")
                continue

            if raw in choice_map:
                assignments[sub] = choice_map[raw]
                break
            print("  ⚠️  Enter m, s, i, or 'all m/s/i'.")

        print()

    # Build URL lists per category, then re-sort each by post age
    categorized = {'main': [], 'secondary': [], 'ignored': []}
    for sub, sub_urls in subreddit_map.items():
        cat = assignments.get(sub, 'secondary')
        categorized[cat].extend(sub_urls)
    for cat in categorized:
        categorized[cat] = sort_posts_oldest_first(categorized[cat])

    # Summary
    print("="*60)
    print("CATEGORIZATION SUMMARY")
    print("="*60)
    for cat in ('main', 'secondary', 'ignored'):
        count = len(categorized[cat])
        nsubs = sum(1 for c in assignments.values() if c == cat)
        print(f"  {cat:<12}: {count:>4} post(s)  ({nsubs} subreddit(s))")
    print()

    out_dir = source_path.parent if source_path else Path.cwd()
    print("Saving categorized files…")
    _write_categorized_csvs(categorized, title_cache, rows_cache, out_dir)

    main_count = len(categorized['main'])
    if main_count == 0:
        print("\n⚠️  No subreddits assigned to 'main'. Nothing to post in this run.")
        raise SystemExit(0)

    print(f"\n▶  Continuing with {main_count} main post(s)…\n")
    return categorized['main']


# ============================================================
# INPUT AUTO-DETECTION & LOAD / SAVE
# ============================================================

def find_input_file():
    """
    Search common locations for a supported input file.

    Priority order:
      1. Dated category files  (*_main.csv, *_secondary.csv)  — newest first
      2. saveddit4reddit.csv
      3. reddit_export.html
      4. reddit_saved_posts.json (progress file)

    Searches: current working directory, then script directory.

    Returns:
        tuple: (Path, file_type) where file_type is 'csv' | 'html' | 'json',
               or (None, None) if nothing found.
    """
    search_dirs = [Path.cwd(), Path(__file__).parent]

    # 0. Resume an in-progress session if the progress file exists and has URLs left
    for folder in search_dirs:
        progress = folder / SAVED_POSTS_FILE
        if progress.exists():
            try:
                data = json.loads(progress.read_text(encoding='utf-8'))
                if data.get('urls'):   # only resume when there is work remaining
                    remaining = len(data['urls'])
                    print(f"🔁 Found in-progress session ({remaining} posts remaining).")
                    print(f"   Resuming from {progress.name}")
                    print(f"   (Delete {progress.name} to start a fresh batch)\n")
                    return progress, 'json'
            except Exception:
                pass

    # 1. Dated category files (*_main.csv / *_secondary.csv), newest first
    for folder in search_dirs:
        for pattern in ('*_main.csv', '*_secondary.csv'):
            matches = sorted(folder.glob(pattern), reverse=True)
            if matches:
                return matches[0], 'csv'

    # 2. Fixed-name fallbacks (CSV only — no JSON progress file here)
    candidates = [
        ("saveddit4reddit.csv", "csv"),
        ("reddit_export.html",  "html"),
        (SAVED_POSTS_FILE,      "json"),
    ]
    for folder in search_dirs:
        for filename, ftype in candidates:
            path = folder / filename
            if path.exists():
                return path, ftype

    return None, None


def load_saved_posts():
    """
    Detect and load saved posts from the best available input file.

    - CSV  → parsed, sorted oldest-first, title cache populated
    - HTML → parsed, sorted oldest-first
    - JSON → loaded as-is (already sorted / processed)

    Returns:
        tuple: (urls: list[str], title_cache: dict[str, str],
                rows_cache: dict[str, dict], source_path: Path | None)
    """
    title_cache = {}
    rows_cache = {}

    file_path, file_type = find_input_file()

    if file_path is None:
        print("❌ Could not find an input file automatically.")
        print("Supported files (place in the current directory):")
        print("  *_main.csv / *_secondary.csv  — categorized batch files")
        print("  saveddit4reddit.csv           — Saveddit CSV export")
        print("  reddit_export.html            — Reddit HTML export")
        print(f"  {SAVED_POSTS_FILE}           — previously generated JSON")
        print("\nEnter full path to your file:")
        raw = input("> ").strip()
        file_path = Path(raw)
        if not file_path.exists():
            print(f"❌ File not found: {file_path}")
            return [], title_cache, {}, None
        ext = file_path.suffix.lower()
        if ext == '.csv':
            file_type = 'csv'
        elif ext in ('.html', '.htm'):
            file_type = 'html'
        elif ext == '.json':
            file_type = 'json'
        else:
            print(f"❌ Unrecognised file extension: {ext}")
            return [], title_cache, {}, None

    print(f"📂 Reading {file_path}  (format: {file_type})")

    if file_type == 'csv':
        urls, csv_titles, rows_cache = parse_csv_export(file_path)
        title_cache.update(csv_titles)
        print("🔄 Sorting posts oldest → newest by post ID…")
        urls = sort_posts_oldest_first(urls)
        print(f"📋 {len(urls)} posts ready (sorted oldest first)")
        _write_json_snapshot(urls)
        return urls, title_cache, rows_cache, file_path

    if file_type == 'html':
        urls = extract_urls_from_html(file_path)
        print(f"✅ Extracted {len(urls)} posts from HTML export")
        print("🔄 Sorting posts oldest → newest by post ID…")
        urls = sort_posts_oldest_first(urls)
        _write_json_snapshot(urls)
        return urls, title_cache, rows_cache, file_path

    # JSON
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        content = re.sub(r',(\s*[}\]])', r'\1', content)
        data = json.loads(content)
        urls = data.get('urls', [])
        print(f"✅ Loaded {len(urls)} posts from JSON")
        return urls, title_cache, rows_cache, file_path
    except Exception as e:
        print(f"❌ Error reading JSON: {e}")
        return [], title_cache, {}, None


def _write_json_snapshot(urls):
    """Write current URL list to reddit_saved_posts.json in the cwd for progress tracking."""
    out = Path.cwd() / SAVED_POSTS_FILE
    data = {
        "indexed_at": datetime.now().isoformat(),
        "sort_order": "oldest_to_newest",
        "count": len(urls),
        "urls": urls,
    }
    try:
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"💾 Snapshot saved to {out.name}")
    except Exception as e:
        print(f"⚠️  Could not write snapshot: {e}")


def save_saved_posts(urls):
    """Overwrite the JSON progress file with the current URL list."""
    json_file = Path.cwd() / SAVED_POSTS_FILE
    if not json_file.exists():
        json_file = Path(__file__).parent / SAVED_POSTS_FILE
    try:
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump({'urls': urls}, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"⚠️  Warning: Could not save updated list: {e}")
        return False


def add_to_posted_urls(url, status='success'):
    """Append a processed URL to the posted-URLs archive."""
    json_file = Path.cwd() / POSTED_URLS_FILE

    posted_data = {'urls': []}
    if json_file.exists():
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                posted_data = json.load(f)
        except Exception:
            posted_data = {'urls': []}

    posted_data['urls'].append({
        'url': url,
        'status': status,
        'posted_at': datetime.now().isoformat(),
    })

    try:
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(posted_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"⚠️  Warning: Could not save to posted URLs archive: {e}")
        return False


# ============================================================
# ANTI-BOTTING HELPERS
# ============================================================

def ensure_x_tab_active(driver):
    """Switch to an X tab if the current tab is not on X."""
    try:
        if 'x.com' in driver.current_url or 'twitter.com' in driver.current_url:
            return True
        original_window = driver.current_window_handle
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            if 'x.com' in driver.current_url or 'twitter.com' in driver.current_url:
                print("  🔄 Switched to X tab", flush=True)
                return True
        driver.switch_to.window(original_window)
        return False
    except Exception:
        return False


def human_delay(base_seconds, variance=0.3):
    """Sleep for base_seconds ± variance*base_seconds."""
    delay = random.uniform(base_seconds * (1 - variance), base_seconds * (1 + variance))
    time.sleep(delay)


def human_type(element, text, min_delay=0.05, max_delay=0.15, with_typos=False):
    """Type text into a Selenium element character-by-character with human timing."""
    typo_map = {
        'a': ['s', 'q', 'w'], 'b': ['v', 'n', 'g'], 'c': ['x', 'v', 'd'],
        'd': ['s', 'f', 'e'], 'e': ['w', 'r', 'd'], 'f': ['d', 'g', 'r'],
        'g': ['f', 'h', 't'], 'h': ['g', 'j', 'y'], 'i': ['u', 'o', 'k'],
        'j': ['h', 'k', 'u'], 'k': ['j', 'l', 'i'], 'l': ['k', 'o', 'p'],
        'm': ['n', 'j', 'k'], 'n': ['b', 'm', 'h'], 'o': ['i', 'p', 'l'],
        'p': ['o', 'l'],      'q': ['w', 'a'],      'r': ['e', 't', 'f'],
        's': ['a', 'd', 'w'], 't': ['r', 'y', 'g'], 'u': ['y', 'i', 'j'],
        'v': ['c', 'b', 'f'], 'w': ['q', 'e', 's'], 'x': ['z', 'c', 's'],
        'y': ['t', 'u', 'h'], 'z': ['x', 'a'],
    }

    i = 0
    while i < len(text):
        char = text[i]
        if with_typos and char.lower() in typo_map and random.random() < 0.05:
            wrong = random.choice(typo_map[char.lower()])
            if char.isupper():
                wrong = wrong.upper()
            element.send_keys(wrong)
            time.sleep(random.uniform(min_delay, max_delay))
            time.sleep(random.uniform(0.1, 0.3))
            element.send_keys(Keys.BACKSPACE)
            time.sleep(random.uniform(0.05, 0.1))
            element.send_keys(char)
            time.sleep(random.uniform(min_delay, max_delay))
        else:
            element.send_keys(char)
            time.sleep(random.uniform(min_delay, max_delay))

        if random.random() < 0.15:
            time.sleep(random.uniform(0.2, 0.6))
        i += 1

    if random.random() < 0.3:
        time.sleep(random.uniform(0.3, 0.8))


def move_to_element_naturally(driver, element):
    """Move mouse to element with a short natural pause."""
    try:
        ActionChains(driver).move_to_element(element).perform()
        human_delay(0.2, variance=0.5)
    except Exception:
        pass


def visit_profile_and_scroll(driver):
    """Visit the X profile page and scroll to simulate human browsing."""
    try:
        print("\n👤 [HUMAN BEHAVIOR] Visiting profile…")
        profile_link = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="AppTabBar_Profile_Link"]'))
        )
        driver.execute_script("arguments[0].click();", profile_link)
        human_delay(2.0, variance=0.5)

        scroll_count = random.randint(3, 6)
        print(f"   Scrolling profile {scroll_count} times…")
        for _ in range(scroll_count):
            driver.execute_script(f"window.scrollBy(0, {random.randint(300, 700)});")
            human_delay(random.uniform(1.5, 3.5), variance=0.3)

        if random.random() < 0.4:
            print("   Scrolling back to top…")
            driver.execute_script("window.scrollTo(0, 0);")
            human_delay(1.0, variance=0.4)

        print("   Returning to home feed…")
        home_link = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="AppTabBar_Home_Link"]'))
        )
        driver.execute_script("arguments[0].click();", home_link)
        human_delay(2.0, variance=0.5)
        print("✅ Profile visit complete\n")
        return True
    except Exception as e:
        print(f"⚠️  Could not visit profile: {e}")
        try:
            driver.get("https://x.com/home")
            human_delay(2.0, variance=0.3)
        except Exception:
            pass
        return False


# ============================================================
# REDDIT API — fetch images & title
# ============================================================

def get_reddit_images(post_url):
    """
    Fetch images / video and post title from a Reddit post via the JSON API.

    Returns:
        tuple: (image_urls: list[str], post_title: str)
    """
    if not post_url.endswith('.json'):
        post_url = post_url.rstrip('/') + '/.json'

    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/131.0.0.0 Safari/537.36'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }

    try:
        resp = requests.get(post_url, headers=headers, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            print("\n⚠️  Reddit blocked the request (403). Trying old.reddit.com…")
            alt_url = (
                post_url
                .replace('.json', '')
                .replace('www.reddit.com', 'old.reddit.com')
                + '.json'
            )
            resp = requests.get(alt_url, headers=headers, timeout=10)
            resp.raise_for_status()
        else:
            raise

    data = resp.json()
    post = data[0]['data']['children'][0]['data']
    post_title = post.get('title', 'Reddit Post')
    image_urls = []

    if post.get('is_gallery'):
        media_metadata = post.get('media_metadata', {})
        for item in post.get('gallery_data', {}).get('items', []):
            meta = media_metadata.get(item['media_id'], {})
            if meta.get('status') == 'valid':
                s = meta.get('s', {})
                img_url = s.get('u') or s.get('gif') or s.get('mp4') or s.get('url')
                if img_url:
                    image_urls.append(img_url.replace('&amp;', '&'))

    elif post.get('post_hint') == 'image' and 'url' in post:
        image_urls.append(post['url'])

    elif post.get('post_hint') == 'hosted:video' and 'media' in post:
        reddit_video = post['media'].get('reddit_video', {})
        if 'fallback_url' in reddit_video:
            image_urls.append(reddit_video['fallback_url'])

    elif post.get('post_hint') == 'rich:video' and 'preview' in post:
        rvp = post['preview'].get('reddit_video_preview', {})
        if 'fallback_url' in rvp:
            image_urls.append(rvp['fallback_url'])

    elif 'preview' in post and 'images' in post['preview']:
        for img in post['preview']['images']:
            image_urls.append(img['source']['url'].replace('&amp;', '&'))

    elif 'imgur.com' in post.get('url', ''):
        url = post['url']
        if not url.endswith(('.jpg', '.png', '.gif', '.mp4')):
            url += '.jpg'
        image_urls.append(url)

    return image_urls, post_title


def _parse_reddit_json(data):
    """
    Extract image/video URLs and post title from a Reddit JSON payload.
    Shared by both the requests-based and browser-based fetchers.
    """
    post = data[0]['data']['children'][0]['data']
    post_title = post.get('title', 'Reddit Post')
    image_urls = []

    if post.get('is_gallery'):
        media_metadata = post.get('media_metadata', {})
        for item in post.get('gallery_data', {}).get('items', []):
            meta = media_metadata.get(item['media_id'], {})
            if meta.get('status') == 'valid':
                s = meta.get('s', {})
                img_url = s.get('u') or s.get('gif') or s.get('mp4') or s.get('url')
                if img_url:
                    image_urls.append(img_url.replace('&amp;', '&'))
    elif post.get('post_hint') == 'image' and 'url' in post:
        image_urls.append(post['url'])
    elif post.get('post_hint') == 'hosted:video' and 'media' in post:
        rv = post['media'].get('reddit_video', {})
        if 'fallback_url' in rv:
            image_urls.append(rv['fallback_url'])
    elif post.get('post_hint') == 'rich:video' and 'preview' in post:
        rvp = post['preview'].get('reddit_video_preview', {})
        if 'fallback_url' in rvp:
            image_urls.append(rvp['fallback_url'])
    elif 'preview' in post and 'images' in post['preview']:
        for img in post['preview']['images']:
            image_urls.append(img['source']['url'].replace('&amp;', '&'))
    elif 'imgur.com' in post.get('url', ''):
        url = post['url']
        if not url.endswith(('.jpg', '.png', '.gif', '.mp4')):
            url += '.jpg'
        image_urls.append(url)

    return image_urls, post_title


def get_reddit_images_via_browser(driver, post_url):
    """
    Fetch Reddit post images through the Chrome session (uses browser cookies,
    bypassing Reddit's API rate-limit / 403 blocks).

    Navigates to the post's .json URL in Chrome, parses the JSON from the page,
    then returns to x.com/home.

    Returns:
        tuple: (image_urls: list[str], post_title: str)
    """
    json_url = post_url.rstrip('/') + '/.json'
    print(f"   🌐 Fetching via browser: {json_url}")

    previous_url = driver.current_url
    try:
        driver.get(json_url)
        time.sleep(1.5)

        # Chrome renders JSON inside a <pre> tag
        source = driver.page_source
        pre_match = re.search(r'<pre[^>]*>(.*?)</pre>', source, re.DOTALL)
        raw_json = pre_match.group(1) if pre_match else source

        # Unescape HTML entities that Chrome may inject
        raw_json = raw_json.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')

        data = json.loads(raw_json)
        return _parse_reddit_json(data)

    finally:
        # Always return to X
        try:
            driver.get('https://x.com/home')
            time.sleep(1)
        except Exception:
            pass


def download_images(image_urls, folder):
    """Download a list of image/video URLs into folder. Returns local file paths."""
    file_paths = []
    for i, url in enumerate(tqdm(image_urls, desc="Downloading images")):
        ext = url.split('.')[-1].split('?')[0]
        path = os.path.join(folder, f"image_{i + 1}.{ext}")
        with requests.get(url, stream=True) as r:
            with open(path, 'wb') as f:
                shutil.copyfileobj(r.raw, f)
        file_paths.append(path)
    return file_paths


def batch_images_for_x(image_paths, batch_size=4):
    """Split image paths into groups of ≤4 for X threading."""
    return [image_paths[i:i + batch_size] for i in range(0, len(image_paths), batch_size)]


# ============================================================
# X / SELENIUM HELPERS
# ============================================================

def check_if_post_published(driver, post_title, timeout=5):
    """Return True if the compose modal closed (indicating a successful post)."""
    try:
        start_time = time.time()
        initial_url = driver.current_url

        end_time = time.time() + timeout
        while time.time() < end_time:
            modal_closed = False
            url_changed = False

            try:
                modal = driver.find_element(By.CSS_SELECTOR, '[aria-labelledby="modal-header"]')
                if not modal.is_displayed():
                    modal_closed = True
            except Exception:
                modal_closed = True

            if driver.current_url != initial_url and 'status' in driver.current_url:
                url_changed = True

            if modal_closed:
                filtered_title = ''.join(c for c in post_title if ord(c) <= 0xFFFF)
                if filtered_title[:50] in driver.page_source or url_changed:
                    if time.time() - start_time > 2:
                        return True

            human_delay(0.5, variance=0.4)

        return modal_closed
    except Exception as e:
        print(f"  ⚠️  Could not verify post publication: {e}")
        return False


def check_for_x_error(driver):
    """Return True if X is showing a known error message."""
    try:
        error_messages = [
            "Something went wrong", "Try again", "Error",
            "didn't go through", "You are over the daily limit", "rate limit",
        ]
        for msg in error_messages:
            elements = driver.find_elements(By.XPATH, f"//*[contains(text(), '{msg}')]")
            if elements:
                if 'limit' in msg.lower():
                    print("  ⚠️  RATE LIMIT detected! X may be temporarily blocking posts.")
                return True
        return False
    except Exception:
        return False


def check_for_duplicate_post(driver):
    """Return True if X is showing an 'Already said that' error."""
    try:
        for msg in ["Already said that", "You already said that", "already posted"]:
            if driver.find_elements(By.XPATH, f"//*[contains(text(), '{msg}')]"):
                return True
        return False
    except Exception:
        return False


def wait_for_upload_completion(driver, timeout=UPLOAD_TIMEOUT):
    """Block until all media uploads finish or timeout is reached."""
    print("  ⏳ Waiting for uploads to complete…")
    start_time = time.time()
    last_status_check = start_time
    last_button_state = None

    while time.time() - start_time < timeout:
        try:
            post_buttons = driver.find_elements(
                By.CSS_SELECTOR,
                '[data-testid="tweetButton"], [data-testid="tweetButtonInline"]'
            )
            button_enabled = False
            for button in post_buttons:
                if button.is_displayed():
                    is_disabled = (
                        button.get_attribute('disabled') or
                        button.get_attribute('aria-disabled') == 'true'
                    )
                    if not is_disabled:
                        button_enabled = True
                    current_state = 'enabled' if not is_disabled else 'disabled'
                    if last_button_state != current_state and time.time() - start_time > 2:
                        print(f"  🔘 Post button: {current_state}", flush=True)
                    last_button_state = current_state
                    break

            has_upload_status = False
            for keyword in ['Uploading', 'Processing', 'Encoding', 'Compressing', 'Preparing']:
                if driver.find_elements(By.XPATH, f"//*[contains(text(), '{keyword}')]"):
                    has_upload_status = True
                    if time.time() - last_status_check > 3:
                        print(f"  ⏳ Media still {keyword.lower()}…", flush=True)
                        last_status_check = time.time()
                    break

            if button_enabled and not has_upload_status:
                print("  ✅ All uploads completed!")
                return True

            if time.time() - start_time > 30 and not button_enabled:
                print("  ⚠️  Button still disabled after 30s, checking status…", flush=True)

            human_delay(1.0, variance=0.3)

        except Exception as e:
            print(f"  ⚠️  Could not check upload status: {e}")
            human_delay(2.0, variance=0.3)
            return True

    print(f"  ⚠️  Upload check timed out after {timeout}s — continuing anyway")
    return False


def upload_images_selenium(driver, image_paths, tweet_index=0):
    """Send image/video file paths to the X file input element."""
    try:
        print(f"\n  📤 Uploading {len(image_paths)} file(s) to tweet {tweet_index + 1}…")
        video_exts = ['.mp4', '.mov', '.avi', '.webm', '.mkv', '.flv', '.gif']
        has_video = any(any(p.lower().endswith(e) for e in video_exts) for p in image_paths)

        file_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[data-testid="fileInput"]'))
        )
        file_input.send_keys('\n'.join(image_paths))
        print("  ✅ Files sent to upload!")

        if has_video:
            print("  ℹ️  Video detected, waiting for upload to complete…", flush=True)
            human_delay(2.0, variance=0.3)
            wait_for_upload_completion(driver, timeout=60)
        else:
            human_delay(2.0, variance=0.3)
            print("  ✅ Images ready!", flush=True)

        return True
    except TimeoutException:
        print("  ⚠️  Could not find file input element")
        return False
    except Exception as e:
        print(f"  ⚠️  Upload failed: {e}")
        return False


def click_post_button_selenium(driver):
    """Click the Post / Post all button."""
    try:
        print("\n  📤 Clicking 'Post' button…")
        post_button = None
        for selector in ['[data-testid="tweetButton"]', '[data-testid="tweetButtonInline"]']:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, selector)
                if btn and btn.is_displayed():
                    post_button = btn
                    print(f"     Found button: {selector}")
                    break
            except Exception:
                continue

        if not post_button:
            raise Exception("Could not find any Post button")

        driver.execute_script("arguments[0].click();", post_button)
        print("  ✅ Post button clicked!")
        human_delay(2.0, variance=0.4)
        return True
    except TimeoutException:
        print("  ⚠️  Could not find Post button")
        return False
    except Exception as e:
        print(f"  ⚠️  Failed to click Post button: {e}")
        return False


def click_add_button_selenium(driver):
    """Click the + button to add another tweet to the thread."""
    try:
        print("\n  ➕ Adding new tweet to thread…")
        add_button = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="addButton"]'))
        )
        driver.execute_script("arguments[0].click();", add_button)
        print("  ✅ New tweet added to thread!")
        human_delay(3.0, variance=0.4)
        return True
    except Exception as e:
        print(f"  ⚠️  Failed to click add button: {e}")
        return False


def prompt_user_for_post_action(post_title, auto_mode=False):
    """
    Ask the user what to do with a post.

    Returns:
        tuple: (action: str, custom_title: str | None)
               action ∈ {'y', 'a', 'r', 'n', 's', 'q'}
    """
    if auto_mode:
        print(f"\n{'='*60}")
        print(f"📄 [AUTO] Post: {post_title}")
        print(f"{'='*60}")
        return 'y', None

    print(f"\n{'='*60}")
    print(f"📄 Post: {post_title}")
    print(f"{'='*60}")
    print("  y = Post with original title")
    print("  a = Auto-process remaining posts")
    print("  r = Reword title (edit original)")
    print("  n = Enter new title")
    print("  s = Skip this post")
    print("  q = Quit")

    while True:
        choice = input("\nYour choice [y/a/r/n/s/q]: ").lower().strip()
        if choice in ('y', 'a', 's', 'q'):
            return choice, None
        if choice == 'r':
            try:
                import readline
                readline.set_pre_input_hook(lambda: (readline.insert_text(post_title), readline.redisplay()))
                custom_title = input("Edit title: ").strip()
                readline.set_pre_input_hook()
            except (ImportError, AttributeError):
                print(f"\nOriginal: {post_title}")
                custom_title = input("Reword title: ").strip()
            if custom_title:
                return 'r', custom_title
            print("⚠️  Title cannot be empty. Try again.")
        elif choice == 'n':
            custom_title = input("Enter new title: ").strip()
            if custom_title:
                return 'n', custom_title
            print("⚠️  Title cannot be empty. Try again.")
        else:
            print("⚠️  Invalid choice. Enter y, a, r, n, s, or q.")


def open_x_compose(driver):
    """Open the X compose modal."""
    print("  📝 Opening compose modal…", flush=True)
    try:
        if not ensure_x_tab_active(driver):
            print("⚠️  Not on X tab, navigating…", flush=True)
            driver.get("https://x.com/home")
            human_delay(3.0, variance=0.3)

        # Close any already-open composer
        try:
            existing = driver.find_element(By.CSS_SELECTOR, '[data-testid="tweetTextarea_0"]')
            if existing:
                print("  ℹ️  Compose already open, closing it…", flush=True)
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                human_delay(1.0, variance=0.5)
        except Exception:
            pass

        if 'x.com/home' not in driver.current_url:
            driver.get("https://x.com/home")
            human_delay(3.0, variance=0.3)

        try:
            compose_button = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'a[data-testid="SideNav_NewTweet_Button"]')
                )
            )
            driver.execute_script("arguments[0].click();", compose_button)
            print("  ✅ Compose modal opened", flush=True)
            human_delay(2.0, variance=0.4)
            return True
        except Exception:
            ActionChains(driver).send_keys('n').perform()
            human_delay(2.0, variance=0.4)
            print("  ✅ Compose opened via keyboard", flush=True)
            return True

    except Exception as e:
        print(f"  ⚠️  Failed to open compose: {e}", flush=True)
        return False


# ============================================================
# BROWSER SETUP
# ============================================================

# Cookies are stored next to the script; delete to force a fresh login.
_COOKIES_FILE = Path(__file__).parent / 'x_session_cookies.json'


def _save_cookies(driver):
    """Persist current browser cookies to disk."""
    cookies = driver.get_cookies()
    with open(_COOKIES_FILE, 'w', encoding='utf-8') as f:
        json.dump(cookies, f, indent=2)
    print(f"   ✅ Session saved → {_COOKIES_FILE.name}")


def _load_cookies(driver):
    """
    Inject saved cookies into the browser.
    Returns True if the file existed and was loaded.
    """
    if not _COOKIES_FILE.exists():
        return False
    print("   Loading saved session cookies…")
    with open(_COOKIES_FILE, 'r', encoding='utf-8') as f:
        cookies = json.load(f)
    for cookie in cookies:
        cookie.pop('sameSite', None)  # can raise in Selenium
        try:
            driver.add_cookie(cookie)
        except Exception:
            pass
    return True


def _prompt_manual_login(driver):
    """Navigate to the login page and wait for the user, then save cookies."""
    driver.get("https://x.com/login")
    print()
    input("   Press Enter once you are logged in and can see the X home feed… ")
    _save_cookies(driver)


def _ensure_reddit_login(driver):
    """
    Navigate to Reddit and prompt the user to log in if not already logged in.
    Tip: 'Continue with X' works since X is already authenticated in this session.
    """
    print("   Checking Reddit login…")
    driver.get("https://www.reddit.com")
    time.sleep(2)

    # Detect login state: logged-out Reddit shows a "Log In" link in the header
    try:
        login_links = driver.find_elements(
            By.XPATH,
            "//*[normalize-space(text())='Log In' or normalize-space(text())='Log in']"
        )
        logged_in = len(login_links) == 0
    except Exception:
        logged_in = False

    if not logged_in:
        print()
        print("   ─" * 30)
        print("   Please log into Reddit in the browser.")
        print("   💡 Tip: click 'Continue with X' — no password needed.")
        print("   ─" * 30)
        input("   Press Enter once you're logged into Reddit… ")
        print("   ✅ Reddit login recorded")
    else:
        print("   ✅ Already logged into Reddit")

    driver.get("https://x.com/home")
    time.sleep(1)


def start_browser():
    """
    Launches a persistent stealth Chrome instance. 
    Auto-detects active sessions: returns driver immediately if logged in,
    otherwise pauses for a manual first-time login and saves the profile.
    """
    # 1. Clean up lingering tasks that could lock profile database files
    subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)

    print("🚀 Launching stealth browser...")
    driver = Driver(
        uc=True,
        user_data_dir=r"C:\Users\RyanN\AppData\Local\Google\Chrome\XportAutomation",
        headed=True
    )
    
    # 2. Check persistence by navigating to X
    print("🌐 Checking session persistence on X...")
    driver.get("https://x.com")
    
    # 3. Dynamic authentication check
    try:
        # Check for a UI element exclusive to a logged-in home feed (e.g., the main nav bar)
        WebDriverWait(driver, 7).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="AppTabBar_Home_Link"]'))
        )
        print("✅ Session active! Persistent login verified.")
        return driver  # Return driver immediately to your scraping/posting logic
        
    except Exception:
        # Fallback to First Run if the home feed element isn't found
        print("\n" + "─" * 50)
        print("⚠️  No active session found (First Run or expired session).")
        print("👉 Please complete your login manually in the Chrome window.")
        print("👉 Once your home feed has fully loaded, return here.")
        print("─" * 50 + "\n")
        
        input("Press ENTER here ONLY when you are looking at your logged-in X home feed...")
        
        print("💾 Saving session data and closing browser gracefully...")
        time.sleep(2)
        driver.quit()  # Forces Chrome to dump cookies from RAM to disk
        
        print("\n✅ Profile securely saved! Please restart the script to run automated.")
        raise SystemExit(0)


    # if _load_cookies(driver):
    #     driver.refresh()
    #     time.sleep(3)
    #     # Check we're actually logged in
    #     try:
    #         WebDriverWait(driver, 10).until(
    #             EC.presence_of_element_located(
    #                 (By.CSS_SELECTOR, '[data-testid="AppTabBar_Home_Link"]')
    #             )
    #         )
    #         print("   ✅ Session restored — already logged in")
    #     except Exception:
    #         print("   ⚠️  Cookies expired or invalid. Please log in again…")
    #         _COOKIES_FILE.unlink(missing_ok=True)
    #         _prompt_manual_login(driver)
    # else:
    #     print()
    #     print("   ─" * 30)
    #     print("   FIRST RUN: log into X in the browser window.")
    #     print("   Return here once you\'re on the home feed.")
    #     print("   ─" * 30)
    #     _prompt_manual_login(driver)

    # driver.get("https://x.com/home")
    # time.sleep(2)

    # Ensure Reddit is also logged in (needed for browser-based image fetching)
    # _ensure_reddit_login(driver)

    return driver


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("🚀 XportReddit2 — Reddit to X Thread Automation\n")

    # --- Load posts (auto-detects CSV / HTML / JSON) ---
    reddit_urls, title_cache, rows_cache, source_path = load_saved_posts()

    if not reddit_urls:
        print("\n❌ No posts found. Exiting.")
        raise SystemExit(1)

    # --- Route based on filename ---
    routing = _check_filename_routing(source_path)

    if routing == 'ignored':
        print(f"\n❌ '{source_path.name}' is an ignored-batch file. Nothing to post.")
        raise SystemExit(1)

    if routing == 'sort':
        # Run the interactive subreddit categorization step
        reddit_urls = categorize_subreddits(reddit_urls, title_cache, rows_cache, source_path)

    # routing == 'direct' (main/secondary/progress file) → skip categorization

    total_posts = len(reddit_urls)
    print(f"\n📋 Ready to process {total_posts} saved posts\n")

    # --- Start browser ---
    print("🌐 Starting Chrome…")
    try:
        driver = start_browser()
        print("✅ Chrome launched — make sure you are logged into X\n")
        time.sleep(3)
    except ImportError as e:
        print(f"❌ {e}")
        raise SystemExit(1)
    except Exception as e:
        print(f"❌ Failed to start browser: {e}")
        raise SystemExit(1)

    # Temp directory for downloaded media
    tmpdir = os.path.join(os.path.dirname(__file__), 'temp_downloads')
    os.makedirs(tmpdir, exist_ok=True)

    posts_processed = 0
    posts_skipped = 0
    posts_failed = 0
    auto_mode = False
    posts_since_profile_visit = 0
    next_profile_visit = random.randint(5, 10)

    try:
        for idx, reddit_url in enumerate(reddit_urls[:], 1):
            print(f"\n{'='*60}")
            print(f"POST {idx}/{total_posts}")
            print(f"{'='*60}")

            # --- Fetch title (use cache if available from CSV) ---
            print("📥 Fetching post info from Reddit…")
            original_title = None
            if reddit_url in title_cache:
                original_title = title_cache[reddit_url]
                print(f"   ℹ️  Title from cache: {original_title}")
            else:
                try:
                    _, original_title = get_reddit_images_via_browser(driver, reddit_url)
                except Exception as e:
                    print(f"   ⚠️  Could not fetch title via browser: {e}")

            if not original_title:
                # Derive a readable title from the URL slug as last resort
                slug = reddit_url.rstrip('/').split('/')[-1]
                original_title = slug.replace('_', ' ').strip() or reddit_url
                print(f"   ℹ️  Using URL-derived title: {original_title}")

            action, custom_title = prompt_user_for_post_action(original_title, auto_mode=auto_mode)

            if action == 'a':
                print("\n🤖 AUTO MODE ENABLED")
                print("   Posts will be processed automatically with human-like delays.")
                print("   Press Ctrl+C to stop at any time.\n")
                auto_mode = True
                action = 'y'

            if action == 'q':
                print("\n👋 Quitting…")
                break

            if action == 's':
                print("⏭️  Skipping…", flush=True)
                posts_skipped += 1
                add_to_posted_urls(reddit_url, status='skipped')
                reddit_urls.remove(reddit_url)
                if save_saved_posts(reddit_urls):
                    print(f"✅ Archived and removed from list ({len(reddit_urls)} remaining)\n")
                else:
                    print("⚠️  Could not update list file\n")
                continue

            post_title = original_title
            if action in ('n', 'r') and custom_title:
                post_title = custom_title
                print(f"✏️  Using custom title: {post_title}")

            try:
                print("\n📥 Fetching media from Reddit…", flush=True)
                try:
                    image_urls, _ = get_reddit_images_via_browser(driver, reddit_url)
                    if not image_urls:
                        raise ValueError("No images returned")
                    print(f"   ✅ Got {len(image_urls)} image(s) via browser")
                except Exception as browser_err:
                    print(f"   ⚠️  Browser fetch failed: {browser_err}")
                    # Fallback: single preview image cached in the CSV row
                    cached_img = rows_cache.get(reddit_url, {}).get('image', '').strip().strip('"')
                    if cached_img:
                        print("   ℹ️  Using cached preview image from CSV")
                        image_urls = [cached_img]
                    else:
                        print("   ❌ No fallback image — skipping post", flush=True)
                        posts_failed += 1
                        continue

                if not image_urls:
                    print("❌ No images found in this post.", flush=True)
                    continue

                file_paths = download_images(image_urls, tmpdir)
                batches = batch_images_for_x(file_paths)

                print(f"\n📊 Found {len(image_urls)} image(s) → {len(batches)} tweet(s) in thread")

                # --- Open composer ---
                print("\n🧵 Setting up X compose…\n", flush=True)
                ensure_x_tab_active(driver)

                if 'x.com' not in driver.current_url and 'twitter.com' not in driver.current_url:
                    print("  ⏳ Navigating to X…", flush=True)
                    driver.get("https://x.com/home")
                    time.sleep(3)

                open_x_compose(driver)

                print("  ⏳ Waiting for compose to load…", flush=True)
                try:
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, '[data-testid="tweetTextarea_0"]')
                        )
                    )
                    WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, 'input[data-testid="fileInput"]')
                        )
                    )
                    print("  ✅ Compose ready!", flush=True)
                    time.sleep(2)
                except Exception as e:
                    print(f"  ❌ Compose not ready: {e}", flush=True)
                    print("  💡 Please open compose manually (click + or press N)")
                    input("     Press Enter when compose is open…")
                    time.sleep(1)

                # --- Build thread ---
                for i, batch in enumerate(batches):
                    batch_nums = list(range(i * 4 + 1, i * 4 + len(batch) + 1))
                    print(f"\n{'='*60}")
                    print(f"Tweet {i+1}/{len(batches)} — Images {batch_nums[0]}–{batch_nums[-1]} ({len(batch)} files)")
                    print(f"{'='*60}")

                    if i == 0:
                        try:
                            ensure_x_tab_active(driver)
                            text_area = WebDriverWait(driver, 10).until(
                                EC.presence_of_element_located(
                                    (By.CSS_SELECTOR, '[data-testid="tweetTextarea_0"]')
                                )
                            )
                            move_to_element_naturally(driver, text_area)
                            driver.execute_script("arguments[0].click();", text_area)
                            human_delay(0.4, variance=0.5)

                            filtered_title = ''.join(
                                c for c in post_title if ord(c) <= 0xFFFF
                            )
                            print(f"  ⌨️  Typing title…")
                            human_type(
                                text_area, filtered_title,
                                min_delay=0.03, max_delay=0.12,
                                with_typos=auto_mode
                            )
                            print(
                                f"  ✅ Added title: "
                                f"{filtered_title[:50]}{'…' if len(filtered_title) > 50 else ''}"
                            )
                            human_delay(1.5, variance=0.4)
                        except Exception as e:
                            print(f"  ⚠️  Could not add title: {e}")

                    if not upload_images_selenium(driver, batch, i):
                        print("\n  ⚠️  Upload failed. Skipping this batch…")
                        continue

                    if i < len(batches) - 1:
                        if not click_add_button_selenium(driver):
                            print("  ⚠️  Failed to add tweet to thread.")
                            break

                # --- Post thread ---
                print("\n" + "="*60)
                print("📤 Posting entire thread…")
                print("="*60)
                print("  ⏳ Final stability check before posting…")
                human_delay(2.0, variance=0.4)

                posted = False
                for attempt in range(POST_RETRY_ATTEMPTS):
                    if attempt > 0:
                        print("  🔍 Checking if post was already published…")
                        if check_if_post_published(driver, post_title, timeout=3):
                            print("  ✅ Post found on page — previous attempt succeeded!")
                            posted = True
                            break
                        base_wait = 3 * (attempt + 1)
                        wait_time = base_wait + random.uniform(-0.5, 1.5)
                        print(f"  🔄 Retry {attempt}/{POST_RETRY_ATTEMPTS-1} (waiting ~{base_wait}s)…", flush=True)
                        time.sleep(wait_time)

                    if click_post_button_selenium(driver):
                        human_delay(3.0, variance=0.3)

                        if check_for_duplicate_post(driver):
                            print("  ⚠️  X says 'Already said that' — duplicate detected")
                            print("  🚫 Closing composer and skipping to next post…")
                            try:
                                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                                human_delay(1.0, variance=0.3)
                            except Exception:
                                pass
                            posts_failed += 1
                            add_to_posted_urls(reddit_url, status='skipped')
                            reddit_urls.remove(reddit_url)
                            save_saved_posts(reddit_urls)
                            posted = None
                            break

                        print("  🔍 Verifying post publication…")
                        if check_if_post_published(driver, post_title, timeout=5):
                            print("  ✅ Post verified on page!")
                            posted = True
                            break

                        if check_for_x_error(driver):
                            print("  ⚠️  X returned an error after clicking Post")
                            continue

                        print("  ⚠️  Post not verified yet, will retry…")

                if posted is None:
                    print("\n⏭️  Skipped duplicate post\n")
                    continue

                if not posted:
                    print(f"  ⚠️  Failed to auto-post after {POST_RETRY_ATTEMPTS} attempts.", flush=True)
                    print("  📋 Thread is ready in composer — you can post manually", flush=True)
                    user_choice = input(
                        "  Choose: [p]ost manually and continue, [s]kip, or [q]uit: "
                    ).lower().strip()

                    if user_choice == 'p':
                        input("     Press Enter after you post manually…")
                        add_to_posted_urls(reddit_url, status='manual')
                        reddit_urls.remove(reddit_url)
                        save_saved_posts(reddit_urls)
                    elif user_choice == 's':
                        print("  ⏭️  Skipping this post", flush=True)
                        posts_failed += 1
                        add_to_posted_urls(reddit_url, status='skipped')
                        reddit_urls.remove(reddit_url)
                        save_saved_posts(reddit_urls)
                    elif user_choice == 'q':
                        print("  👋 Quitting…", flush=True)
                        raise KeyboardInterrupt()
                else:
                    print("  ⏳ Waiting for thread to post…")
                    time.sleep(5)

                print("\n" + "="*60)
                print("🎉 Thread complete!")
                print("="*60)

                # Clean temp media
                for fname in os.listdir(tmpdir):
                    fpath = os.path.join(tmpdir, fname)
                    if os.path.isfile(fpath):
                        os.remove(fpath)

                print("✅ Post processed successfully.\n", flush=True)
                posts_processed += 1
                posts_since_profile_visit += 1

                add_to_posted_urls(reddit_url, status='success')
                reddit_urls.remove(reddit_url)
                save_saved_posts(reddit_urls)

                remaining = len(reddit_urls)
                print(f"\n📊 Progress: {posts_processed} completed | {remaining} remaining")

                if auto_mode and posts_since_profile_visit >= next_profile_visit:
                    print(f"\n🤖 [AUTO MODE] Posted {posts_since_profile_visit} posts, simulating profile check…")
                    if visit_profile_and_scroll(driver):
                        posts_since_profile_visit = 0
                        next_profile_visit = random.randint(5, 10)
                        print(f"   Next profile visit in {next_profile_visit} posts\n")

            except Exception as e:
                print(f"❌ Error processing post: {e}", flush=True)
                import traceback
                traceback.print_exc()
                posts_failed += 1
                try:
                    for fname in os.listdir(tmpdir):
                        fpath = os.path.join(tmpdir, fname)
                        if os.path.isfile(fpath):
                            os.remove(fpath)
                except Exception:
                    pass
                print("🔄 Ready for next post…\n", flush=True)

        # Summary
        print("\n" + "="*60)
        print("📊 SUMMARY")
        print("="*60)
        print(f"✅ Posts processed: {posts_processed}")
        print(f"⏭️  Posts skipped:   {posts_skipped}")
        print(f"❌ Posts failed:    {posts_failed}")
        print(f"📋 Total posts:     {total_posts}")
        print("="*60)

    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        print("\n" + "="*60)
        print("📊 SUMMARY")
        print("="*60)
        print(f"✅ Posts processed: {posts_processed}")
        print(f"⏭️  Posts skipped:   {posts_skipped}")
        print(f"❌ Posts failed:    {posts_failed}")
        print(f"📋 Total attempted: {posts_processed + posts_skipped + posts_failed}/{total_posts}")
        print("="*60)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            if os.path.exists(tmpdir):
                shutil.rmtree(tmpdir)
            print("\n🔒 Closing browser…")
            driver.quit()
            print("✅ Done. Goodbye!")
        except Exception:
            pass
