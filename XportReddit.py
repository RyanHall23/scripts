import os
import requests
from tqdm import tqdm
import tempfile
import shutil
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from flask import Flask, request, jsonify
from flask_cors import CORS
import threading
import queue

def get_reddit_images(post_url):
    # Ensure .json endpoint
    if not post_url.endswith('.json'):
        if post_url.endswith('/'):
            post_url += '.json'
        else:
            post_url += '/.json'
    
    # Use more complete headers to avoid 403 blocks
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    
    try:
        resp = requests.get(post_url, headers=headers, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            print(f"\n⚠️  Reddit blocked the request (403). Trying alternative method...")
            # Try without .json - scrape HTML instead or use old.reddit.com
            alt_url = post_url.replace('.json', '').replace('www.reddit.com', 'old.reddit.com') + '.json'
            resp = requests.get(alt_url, headers=headers, timeout=10)
            resp.raise_for_status()
        else:
            raise
    
    data = resp.json()
    post = data[0]['data']['children'][0]['data']
    post_title = post.get('title', 'Reddit Post')
    image_urls = []

    # Handle Reddit gallery
    if post.get('is_gallery'):
        media_metadata = post.get('media_metadata', {})
        for item in post.get('gallery_data', {}).get('items', []):
            media_id = item['media_id']
            meta = media_metadata.get(media_id, {})
            if meta.get('status') == 'valid':
                s = meta.get('s', {})
                # Try multiple possible keys for the URL
                img_url = (
                    s.get('u') or
                    s.get('gif') or
                    s.get('mp4') or
                    s.get('url')
                )
                if img_url:
                    img_url = img_url.replace('&amp;', '&')
                    image_urls.append(img_url)
    # Handle single image (Reddit-hosted)
    elif post.get('post_hint') == 'image' and 'url' in post:
        image_urls.append(post['url'])
    # Handle Reddit-hosted video or GIF
    elif post.get('post_hint') == 'hosted:video' and 'media' in post:
        reddit_video = post['media'].get('reddit_video')
        if reddit_video and 'fallback_url' in reddit_video:
            video_url = reddit_video['fallback_url']
            image_urls.append(video_url)
    # Handle GIFs (as MP4)
    elif post.get('post_hint') == 'rich:video' and 'preview' in post:
        if 'reddit_video_preview' in post['preview']:
            video_url = post['preview']['reddit_video_preview']['fallback_url']
            image_urls.append(video_url)
    # Handle preview images (fallback)
    elif 'preview' in post and 'images' in post['preview']:
        for img in post['preview']['images']:
            img_url = img['source']['url'].replace('&amp;', '&')
            image_urls.append(img_url)
    # Handle Imgur direct links
    elif 'imgur.com' in post.get('url', ''):
        url = post['url']
        if not url.endswith(('.jpg', '.png', '.gif', '.mp4')):
            url += '.jpg'
        image_urls.append(url)
    # Add more handlers as needed

    return image_urls, post_title

def download_images(image_urls, folder):
    file_paths = []
    for i, url in enumerate(tqdm(image_urls, desc="Downloading images")):
        ext = url.split('.')[-1].split('?')[0]
        filename = f"image_{i+1}.{ext}"
        path = os.path.join(folder, filename)
        with requests.get(url, stream=True) as r:
            with open(path, 'wb') as f:
                shutil.copyfileobj(r.raw, f)
        file_paths.append(path)
    return file_paths

def batch_images_for_x(image_paths, batch_size=4):
    """Batch images into groups of 4 for X threading."""
    return [image_paths[i:i + batch_size] for i in range(0, len(image_paths), batch_size)]

def upload_images_selenium(driver, image_paths, tweet_index=0):
    """Upload images using Selenium file input.
    
    Args:
        driver: WebDriver instance
        image_paths: List of file paths to upload
        tweet_index: Index of the tweet in thread (0 for first, 1 for second, etc.)
    """
    try:
        print(f"\n  📤 Uploading {len(image_paths)} image(s) to tweet {tweet_index + 1}...")
        
        # Find the file input element (X uses a hidden input with data-testid="fileInput")
        file_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[data-testid="fileInput"]'))
        )
        
        # Send all file paths at once (newline-separated for multiple files)
        files_string = '\n'.join(image_paths)
        file_input.send_keys(files_string)
        
        print(f"  ✅ Images uploaded!")
        time.sleep(2)  # Wait for upload processing
        return True
        
    except TimeoutException:
        print(f"  ⚠️  Could not find file input element")
        return False
    except Exception as e:
        print(f"  ⚠️  Upload failed: {e}")
        return False

def click_post_button_selenium(driver, inline=False):
    """Click the Post button using Selenium.
    
    Args:
        driver: WebDriver instance
        inline: If True, uses tweetButtonInline (for thread composer)
                If False, uses tweetButton (for final post)
    """
    try:
        print("\n  📤 Clicking 'Post' button...")
        
        button_id = "tweetButtonInline" if inline else "tweetButton"
        post_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, f'[data-testid="{button_id}"]'))
        )
        post_button.click()
        
        print("  ✅ Post button clicked!")
        time.sleep(2)  # Wait for action to complete
        return True
        
    except TimeoutException:
        print(f"  ⚠️  Could not find Post button ({button_id})")
        return False
    except Exception as e:
        print(f"  ⚠️  Failed to click Post button: {e}")
        return False

def click_add_button_selenium(driver):
    """Click the add button to add a new tweet to the thread."""
    try:
        print("\n  ➕ Adding new tweet to thread...")
        
        add_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-testid="addButton"]'))
        )
        add_button.click()
        
        print("  ✅ New tweet added to thread!")
        time.sleep(1)  # Wait for new textarea to appear
        return True
        
    except TimeoutException:
        print("  ⚠️  Could not find add button")
        return False
    except Exception as e:
        print(f"  ⚠️  Failed to click add button: {e}")
        return False

def get_latest_tweet_id_selenium(driver):
    """Get the latest tweet ID from current page using Selenium."""
    try:
        print("\n  🔍 Getting latest tweet ID...")
        
        # Get current URL and extract tweet ID
        current_url = driver.current_url
        
        if '/status/' in current_url:
            parts = current_url.split('/')
            for i, part in enumerate(parts):
                if part == 'status' and i + 1 < len(parts):
                    tweet_id = parts[i + 1].split('?')[0]
                    print(f"  ✅ Got tweet ID: {tweet_id}")
                    return tweet_id
        
        print(f"  ⚠️  Could not extract tweet ID from URL: {current_url}")
        return None
        
    except Exception as e:
        print(f"  ⚠️  Failed to get tweet ID: {e}")
        return None

# Flask server for receiving URLs from browser extension
url_queue = queue.Queue()
app = Flask(__name__)
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})

# Add headers to allow private network access
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    response.headers.add('Access-Control-Allow-Private-Network', 'true')
    return response

@app.route('/share', methods=['POST', 'OPTIONS'])
def share_to_x():
    """Receive Reddit URL from browser extension."""
    # Handle preflight OPTIONS request
    if request.method == 'OPTIONS':
        return '', 200
        
    try:
        data = request.json
        reddit_url = data.get('url')
        
        print(f"\n📩 Received request from extension: {reddit_url}")
        
        if not reddit_url or 'reddit.com' not in reddit_url:
            print("   ❌ Invalid URL")
            return jsonify({'status': 'error', 'message': 'Invalid Reddit URL'}), 400
        
        # Add to queue for processing
        url_queue.put(reddit_url)
        print(f"   ✅ Added to queue (queue size: {url_queue.qsize()})")
        
        return jsonify({'status': 'success', 'message': 'URL queued for processing'})
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/status', methods=['GET'])
def status():
    """Check if server is running."""
    return jsonify({'status': 'running', 'queue_size': url_queue.qsize()})

def run_flask_server():
    """Run Flask server in background."""
    app.run(host='127.0.0.1', port=8765, debug=False, use_reloader=False)

if __name__ == "__main__":
    print("🚀 XportReddit - Reddit to X Thread Automation (Selenium)\n")
    print("⚠️  Requirements: pip install selenium flask flask-cors\n")
    
    # Start Flask server in background
    print("🌐 Starting local server on http://127.0.0.1:8765")
    flask_thread = threading.Thread(target=run_flask_server, daemon=True)
    flask_thread.start()
    time.sleep(2)
    print("✅ Server ready! Install the browser extension to share Reddit posts.\n")
    
    # Initialize Selenium WebDriver with Edge using remote debugging
    print("🌐 Connecting to Edge...")
    try:
        from selenium.webdriver.edge.options import Options
        from selenium.webdriver.edge.service import Service
        import subprocess
        import socket
        
        options = Options()
        debug_port = 9222
        
        # Check if Edge is already running with debugging enabled
        def is_port_open(port):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(('127.0.0.1', port))
                sock.close()
                return result == 0
            except:
                return False
        
        if not is_port_open(debug_port):
            print("   Edge debugging port not detected.")
            print("   Please close ALL Edge windows and let me start it...\n")
            
            # Kill any existing Edge processes
            subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], 
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
            
            # Start Edge with debugging and open Reddit
            edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
            subprocess.Popen([edge_path, f'--remote-debugging-port={debug_port}', '--no-first-run', '--no-default-browser-check', 'https://www.reddit.com'], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Wait for Edge to start
            print("   Starting Edge...")
            for i in range(10):
                time.sleep(1)
                if is_port_open(debug_port):
                    break
            else:
                raise Exception("Edge did not start with debugging port")
        
        # Connect to the running Edge instance
        options.add_experimental_option("debuggerAddress", f"127.0.0.1:{debug_port}")
        
        driver = webdriver.Edge(options=options)
        driver.maximize_window()
        print("✅ Connected to Edge!")
        print("   (Using your normal Edge session with all your logins)\n")
    except Exception as e:
        print(f"❌ Failed to connect to Edge: {e}")
        print("   Make sure Edge is installed and selenium is updated:")
        print("   pip install --upgrade selenium")
        exit(1)
    
    # Select mode
    print("\n📋 Select Mode:")
    print("  [1] Extension Mode - Wait for 'Share to X' button clicks from browser")
    print("  [2] Manual Mode - Paste Reddit URLs manually\n")
    
    mode = input("Choice (1 or 2, default=1): ").strip() or "1"
    extension_mode = (mode == "1")
    
    if extension_mode:
        print("\n✅ Extension Mode Active!", flush=True)
        print("   Browse Reddit and click '📤 Share to X' buttons", flush=True)
        print("   Waiting for posts to share...\n", flush=True)
    else:
        print("\n✅ Manual Mode Active!", flush=True)
        print("   Paste Reddit URLs when prompted\n", flush=True)
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            while True:
                reddit_url = None
                
                if extension_mode:
                    # Extension mode - only check queue
                    if not url_queue.empty():
                        reddit_url = url_queue.get()
                        print(f"\n{'='*60}", flush=True)
                        print(f"🔄 Processing URL from extension...", flush=True)
                        print(f"{'='*60}", flush=True)
                    else:
                        time.sleep(1)
                        continue
                else:
                    # Manual mode - ask for input
                    reddit_url = input("\nEnter Reddit post URL (or press Enter to quit): ").strip()
                    if not reddit_url:
                        print("Goodbye!")
                        break

                try:
                    print(f"📥 Fetching images from Reddit...", flush=True)
                    image_urls, post_title = get_reddit_images(reddit_url)
                    
                    if not image_urls:
                        print("❌ No images found in this post.", flush=True)
                        continue

                    file_paths = download_images(image_urls, tmpdir)
                    batches = batch_images_for_x(file_paths)
                    
                    print(f"\n📊 Found {len(image_urls)} images -> Creating {len(batches)} tweet(s) in thread")
                    
                    # Navigate to X home feed in a new tab
                    print("\n🧵 Composing thread from feed...\n", flush=True)
                    
                    # Check if we're already on X, if not open new tab
                    current_url = driver.current_url
                    if 'x.com' not in current_url and 'twitter.com' not in current_url:
                        print("  📑 Opening new tab for X...", flush=True)
                        driver.execute_script("window.open('https://x.com/home', '_blank');")
                        driver.switch_to.window(driver.window_handles[-1])
                        time.sleep(4)  # Wait for X to load
                    else:
                        driver.get("https://x.com/home")
                        time.sleep(3)
                    
                    # Click the "Post" button to open composer
                    try:
                        print("  📝 Opening composer...")
                        # The main tweet button on the feed has different test IDs depending on where it is
                        # Try the floating action button first, then sidebar
                        composer_button = None
                        for selector in ['[data-testid="SideNav_NewTweet_Button"]', '[aria-label="Post"]', '[data-testid="tweetButtonInline"]']:
                            try:
                                composer_button = WebDriverWait(driver, 5).until(
                                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                                )
                                break
                            except:
                                continue
                        
                        if not composer_button:
                            raise Exception("Could not find composer button")
                        
                        composer_button.click()
                        time.sleep(2)  # Wait for composer to open
                        print("  ✅ Composer opened!")
                    except Exception as e:
                        print(f"  ⚠️  Could not open composer: {e}")
                        input("     Please click the Post button manually, then press Enter...")
                    
                    # Build the entire thread before posting
                    for i, batch in enumerate(batches):
                        batch_nums = list(range(i*4 + 1, i*4 + len(batch) + 1))
                        print(f"\n{'='*60}")
                        print(f"Tweet {i+1}/{len(batches)}")
                        print(f"📷 Images: {batch_nums[0]}-{batch_nums[-1]} ({len(batch)} files)")
                        print(f"{'='*60}")
                        
                        # Add tweet text for first tweet only (BEFORE uploading images)
                        if i == 0:
                            try:
                                text_area = WebDriverWait(driver, 10).until(
                                    EC.presence_of_element_located((By.CSS_SELECTOR, f'[data-testid="tweetTextarea_{i}"]'))
                                )
                                text_area.send_keys(post_title)
                                print(f"  ✅ Added title: {post_title[:50]}...")
                                time.sleep(1)  # Let text register
                            except Exception as e:
                                print(f"  ⚠️  Could not add title: {e}")
                        
                        # Upload images for this batch
                        if not upload_images_selenium(driver, batch, i):
                            print("\n  ⚠️  Upload failed. Skipping this batch...")
                            continue
                        
                        # Add another tweet to the thread if not the last batch
                        if i < len(batches) - 1:
                            if not click_add_button_selenium(driver):
                                print("  ⚠️  Failed to add tweet to thread.")
                                break
                    
                    # Post the entire thread at once
                    print("\n" + "="*60)
                    print("📤 Posting entire thread...")
                    print("="*60)
                    
                    if not click_post_button_selenium(driver, inline=False):
                        print("  ⚠️  Failed to auto-post thread.")
                        input("     Click 'Post all' manually, then press Enter...")
                    else:
                        print("  ⏳ Waiting for thread to post...")
                        time.sleep(5)
                    
                    print("\n" + "="*60)
                    print("🎉 Thread complete!")
                    print("="*60)
                    
                    # Clear temp directory
                    for filename in os.listdir(tmpdir):
                        file_path = os.path.join(tmpdir, filename)
                        if os.path.isfile(file_path):
                            os.remove(file_path)

                    print("✅ Done! Post processed successfully.\n", flush=True)
                    
                except Exception as e:
                    print(f"❌ Error processing post: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
                    
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user. Cleaning up...")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            driver.quit()
            print("🔒 Browser closed.")
        except:
            pass