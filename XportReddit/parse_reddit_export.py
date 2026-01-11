#!/usr/bin/env python3
"""
Parse Reddit HTML export file and extract saved post URLs
"""

import json
import re
from pathlib import Path
from datetime import datetime

def extract_urls_from_html(html_file):
    """Extract post URLs from Reddit HTML export file."""
    
    with open(html_file, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    urls = []
    seen = set()
    
    # Debug: Show a sample of the HTML
    print("=== Debugging HTML content ===")
    if "THREAD" in html_content:
        print("Found 'THREAD' text in file")
        # Find a sample line with THREAD
        for line in html_content.split('\n'):
            if 'THREAD' in line:
                print(f"Sample line: {line[:200]}")
                break
    else:
        print("No 'THREAD' text found in file")
    
    if "reddit.com/r/" in html_content:
        print("Found 'reddit.com/r/' in file")
        # Find a sample reddit URL
        for line in html_content.split('\n'):
            if 'reddit.com/r/' in line and 'comments' in line:
                print(f"Sample reddit line: {line[:200]}")
                break
    print("==============================\n")
    
    # Try different patterns
    
    # Pattern 1: THREAD links with single or double quotes
    pattern1 = r'<a\s+href=["\']+(https://www\.reddit\.com/r/[^/]+/comments/[^"\']+)["\']>\s*THREAD\s*</a>'
    matches1 = re.findall(pattern1, html_content, re.IGNORECASE | re.DOTALL)
    print(f"Pattern 1 (strict THREAD): {len(matches1)} matches")
    
    # Pattern 2: Any href with reddit comments URL (single or double quotes)
    pattern2 = r'href=["\']+(https://www\.reddit\.com/r/[^/]+/comments/[^"\']+)["\']'
    matches2 = re.findall(pattern2, html_content)
    print(f"Pattern 2 (any reddit comments href): {len(matches2)} matches")
    
    # Use whichever found results
    all_matches = matches1 if matches1 else matches2
    
    for match in all_matches:
        # Clean up the URL
        url = match.split('?')[0].split('#')[0]
        if url.endswith('/'):
            url = url[:-1]
        
        if url not in seen:
            seen.add(url)
            urls.append(url)
    
    return urls

def main():
    # Look for the export file
    export_file = Path.home() / "Downloads" / "reddit_export.html"
    
    if not export_file.exists():
        print(f"❌ Could not find {export_file}")
        print("Please specify the path to your reddit_export.html file:")
        file_path = input("> ").strip()
        export_file = Path(file_path)
        
        if not export_file.exists():
            print(f"❌ File not found: {export_file}")
            return
    
    print(f"📂 Reading {export_file}")
    
    try:
        urls = extract_urls_from_html(export_file)
        
        print(f"✅ Found {len(urls)} saved posts!")
        
        # Create JSON file
        output_file = Path.home() / "Downloads" / "reddit_saved_posts.json"
        
        data = {
            "indexed_at": datetime.now().isoformat(),
            "count": len(urls),
            "urls": urls
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        print(f"💾 Saved to: {output_file}")
        print(f"\n📋 First few URLs:")
        for i, url in enumerate(urls[:5], 1):
            print(f"  {i}. {url}")
        
        if len(urls) > 5:
            print(f"  ... and {len(urls) - 5} more")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
