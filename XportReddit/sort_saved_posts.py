#!/usr/bin/env python3
"""
Sort Reddit saved posts from oldest to newest based on post ID
"""

import json
import re
from pathlib import Path
from datetime import datetime

def extract_post_id(url):
    """Extract the post ID from a Reddit URL."""
    match = re.search(r'/comments/([a-z0-9]+)/', url)
    if match:
        return match.group(1)
    return None

def sort_posts_by_age(input_file, output_file):
    """Sort posts from oldest to newest and save to a new file."""
    
    # Read the input file
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Fix common JSON errors (trailing commas)
    content = re.sub(r',(\s*[}\]])', r'\1', content)
    
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"❌ JSON parsing error: {e}")
        print("Attempting to fix common JSON issues...")
        # Additional cleanup if needed
        raise
    
    urls = data.get('urls', [])
    print(f"📖 Loaded {len(urls)} posts from {input_file.name}")
    
    # Create list of (post_id, url) tuples for sorting
    posts_with_ids = []
    for url in urls:
        post_id = extract_post_id(url)
        if post_id:
            # Reddit IDs are base-36, convert to integer for proper sorting
            try:
                id_as_int = int(post_id, 36)
                posts_with_ids.append((id_as_int, url))
            except ValueError:
                # If conversion fails, keep the URL anyway
                posts_with_ids.append((0, url))
        else:
            # No ID found, put at the beginning
            posts_with_ids.append((0, url))
    
    # Sort by the integer ID (oldest first)
    posts_with_ids.sort(key=lambda x: x[0])
    
    # Extract just the URLs in sorted order
    sorted_urls = [url for _, url in posts_with_ids]
    
    # Create output data
    output_data = {
        "indexed_at": data.get("indexed_at", datetime.now().isoformat()),
        "sorted_at": datetime.now().isoformat(),
        "sort_order": "oldest_to_newest",
        "count": len(sorted_urls),
        "urls": sorted_urls
    }
    
    # Save to output file
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"✅ Sorted {len(sorted_urls)} posts from oldest to newest")
    print(f"💾 Saved to: {output_file}")
    print(f"\n📋 First few posts (oldest):")
    for i, url in enumerate(sorted_urls[:5], 1):
        post_id = extract_post_id(url)
        print(f"  {i}. {url} (ID: {post_id})")
    
    if len(sorted_urls) > 5:
        print(f"\n📋 Last few posts (newest):")
        for i, url in enumerate(sorted_urls[-3:], len(sorted_urls) - 2):
            post_id = extract_post_id(url)
            print(f"  {i}. {url} (ID: {post_id})")

def main():
    # Look for the input file
    input_file = Path.home() / "Downloads" / "reddit_saved_posts.json"
    
    if not input_file.exists():
        print(f"❌ Could not find {input_file}")
        print("Please specify the path to your reddit_saved_posts.json file:")
        file_path = input("> ").strip()
        input_file = Path(file_path)
        
        if not input_file.exists():
            print(f"❌ File not found: {input_file}")
            return
    
    # Set output file
    output_file = Path.home() / "Downloads" / "saved_ordered_posts.json"
    
    try:
        sort_posts_by_age(input_file, output_file)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
