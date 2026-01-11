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

# ============================================================
# CONFIGURATION
# ============================================================
EXTENSION_MODE = True  # Set to False for manual URL input mode
# ============================================================

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

def check_for_x_error(driver):
    """Check if X is showing an error message."""
    try:
        error_messages = [
            "Something went wrong",
            "Try again",
            "Error",
            "didn't go through"
        ]
        
        for msg in error_messages:
            elements = driver.find_elements(By.XPATH, f"//*[contains(text(), '{msg}')]")
            if elements:
                return True
        return False
    except:
        return False

def wait_for_upload_completion(driver, timeout=60):
    """Wait for all media uploads to complete (important for videos).
    
    Args:
        driver: WebDriver instance
        timeout: Maximum time to wait in seconds
    """
    print("  ⏳ Waiting for uploads to complete...")
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            # Check if post button is disabled (indicates upload in progress)
            post_buttons = driver.find_elements(By.CSS_SELECTOR, '[data-testid="tweetButton"], [data-testid="tweetButtonInline"]')
            
            all_enabled = True
            for button in post_buttons:
                if button.is_displayed():
                    if button.get_attribute('disabled') or button.get_attribute('aria-disabled') == 'true':
                        all_enabled = False
                        break
            
            # Check for "Uploading" text
            uploading_texts = driver.find_elements(By.XPATH, "//*[contains(text(), 'Uploading') or contains(text(), 'Processing')]") 
            
            if all_enabled and len(uploading_texts) == 0:
                print("  ✅ All uploads completed!")
                return True
            
            time.sleep(1)
            
        except Exception as e:
            # If we can't check, assume it's done
            print(f"  ⚠️  Could not check upload status: {e}")
            time.sleep(2)
            return True
    
    print(f"  ⚠️  Upload check timed out after {timeout}s - continuing anyway")
    return False

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
        
        print(f"  ✅ Files sent to upload!")
        time.sleep(2)  # Initial wait for upload to start
        
        # Wait for uploads to complete (especially important for videos)
        wait_for_upload_completion(driver, timeout=60)
        
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
        
        # Try multiple button selectors (Post all, Post, etc.)
        post_button = None
        selectors = [
            '[data-testid="tweetButton"]',  # Modal "Post all" or "Post" button
            '[data-testid="tweetButtonInline"]',  # Inline composer button
        ]
        
        for selector in selectors:
            try:
                post_button = driver.find_element(By.CSS_SELECTOR, selector)
                if post_button and post_button.is_displayed():
                    print(f"     Found button: {selector}")
                    break
            except:
                continue
        
        if not post_button:
            raise Exception("Could not find any Post button")
        
        # Use JavaScript click to avoid interception issues
        driver.execute_script("arguments[0].click();", post_button)
        
        print("  ✅ Post button clicked!")
        time.sleep(2)  # Wait for action to complete
        return True
        
    except TimeoutException:
        print(f"  ⚠️  Could not find Post button")
        return False
    except Exception as e:
        print(f"  ⚠️  Failed to click Post button: {e}")
        return False

def click_add_button_selenium(driver):
    """Click the add button to add a new tweet to the thread."""
    try:
        print("\n  ➕ Adding new tweet to thread...")
        
        add_button = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="addButton"]'))
        )
        # Use JavaScript click to avoid interception
        driver.execute_script("arguments[0].click();", add_button)
        
        print("  ✅ New tweet added to thread!")
        time.sleep(3)  # Wait for new textarea to appear and be ready
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
completion_status = {}  # Track completion status: {url: 'processing'|'completed'|'failed'}
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
        completion_status[reddit_url] = 'processing'
        print(f"   ✅ Added to queue (queue size: {url_queue.qsize()})")
        
        return jsonify({'status': 'success', 'message': 'URL queued for processing'})
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/status', methods=['GET'])
def status():
    """Check if server is running."""
    return jsonify({'status': 'running', 'queue_size': url_queue.qsize()})

@app.route('/check/<path:url>', methods=['GET'])
def check_completion(url):
    """Check completion status of a URL."""
    status = completion_status.get(url, 'unknown')
    return jsonify({'url': url, 'status': status})

def check_and_recover_window(driver):
    """Check if browser window is still open, recover if closed."""
    try:
        # Try to get current window handle
        _ = driver.current_window_handle
        return True
    except Exception as e:
        print(f"\n⚠️  Browser window lost: {e}")
        print("   Reconnecting to browser...")
        try:
            # If we have multiple handles, switch to first available
            if len(driver.window_handles) > 0:
                driver.switch_to.window(driver.window_handles[0])
                print("   ✅ Reconnected!")
                return True
            else:
                print("   ❌ All windows closed. Please keep browser open.")
                return False
        except:
            print("   ❌ Could not recover. Please keep browser open.")
            return False

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
    
    # Track tab handles (initialize early)
    x_tab_handle = None
    reddit_tab_handle = None
    
    try:
        from selenium.webdriver.edge.options import Options
        from selenium.webdriver.edge.service import Service
        import subprocess
        import socket
        
        options = Options()
        debug_port = 9222
        
        # Always kill existing Edge processes to avoid "Browser window not found" error
        print("   Killing any existing Edge processes...")
        subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], 
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        
        # Start fresh Edge with debugging and open Reddit
        print("   Starting Edge with debugging enabled...")
        edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        subprocess.Popen([edge_path, f'--remote-debugging-port={debug_port}', '--no-first-run', '--no-default-browser-check', 'https://www.reddit.com'], 
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Wait for Edge to start
        def is_port_open(port):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(('127.0.0.1', port))
                sock.close()
                return result == 0
            except:
                return False
        
        for i in range(10):
            time.sleep(1)
            if is_port_open(debug_port):
                break
        else:
            raise Exception("Edge did not start with debugging port")
        
        # Connect to the running Edge instance
        options.add_experimental_option("debuggerAddress", f"127.0.0.1:{debug_port}")
        
        driver = webdriver.Edge(options=options)
        print("✅ Connected to Edge!")
        print("   (Using your normal Edge session with all your logins)\n")
        
    except Exception as e:
        print(f"❌ Failed to connect to Edge: {e}")
        print("   Make sure Edge is installed and selenium is updated:")
        print("   pip install --upgrade selenium")
        exit(1)
    
    # Use configured mode (no prompt)
    if EXTENSION_MODE:
        print("\n✅ Extension Mode Active! (Change EXTENSION_MODE in script to switch)", flush=True)
        print("   Browse Reddit and click '📤 Share to X' buttons", flush=True)
        print("   Waiting for posts to share...\n", flush=True)
    else:
        print("\n✅ Manual Mode Active! (Change EXTENSION_MODE in script to switch)", flush=True)
        print("   Paste Reddit URLs when prompted\n", flush=True)
    
    # Open X in second tab and keep it open
    print("🌐 Setting up windows...", flush=True)
    try:
        # Wait for initial window to be fully ready
        time.sleep(3)
        
        # First window is Reddit
        reddit_tab_handle = driver.current_window_handle
        print("   ✅ Reddit window ready", flush=True)
        
        # Open X in a new tab (like Ctrl+T)
        initial_handles = driver.window_handles
        driver.execute_script("window.open('https://x.com/home', '_blank');")
        
        # Wait for new window to appear
        for i in range(10):
            time.sleep(0.5)
            current_handles = driver.window_handles
            if len(current_handles) > len(initial_handles):
                break
        
        # Get the new window handle
        new_handles = [h for h in driver.window_handles if h not in initial_handles]
        if not new_handles:
            raise Exception("New window was not created")
        
        # Switch to X window and store its handle
        driver.switch_to.window(new_handles[0])
        x_tab_handle = driver.current_window_handle
        
        # Wait for X home to load
        print("   Loading X home page...", flush=True)
        time.sleep(4)
        
        # Check if X loaded
        current_url = driver.current_url
        if 'x.com' not in current_url and 'twitter.com' not in current_url:
            print(f"   ⚠️  X didn't load (got: {current_url}), navigating manually...", flush=True)
            driver.get("https://x.com/home")
            time.sleep(4)
        
        print(f"   ✅ X window loaded: {driver.current_url}", flush=True)
        
        # Try to maximize X window to make it visible
        try:
            driver.maximize_window()
            time.sleep(1)
        except Exception as max_error:
            print(f"   Note: Could not maximize window (this is OK): {max_error}")
        
        # Switch back to Reddit window
        driver.switch_to.window(reddit_tab_handle)
        print("✅ Both windows ready! (X window should be visible)\n", flush=True)
    except Exception as e:
        print(f"⚠️  Could not open X window: {e}")
        x_tab_handle = None
        reddit_tab_handle = driver.current_window_handle
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            while True:
                reddit_url = None
                
                # Check if browser window is still valid
                if not check_and_recover_window(driver):
                    print("⚠️  Browser closed. Exiting...")
                    break
                
                if EXTENSION_MODE:
                    # Extension mode - only check queue
                    if not url_queue.empty():
                        reddit_url = url_queue.get()
                        print(f"\n{'='*60}", flush=True)
                        print(f"🔄 Processing URL from extension... (Queue: {url_queue.qsize()} remaining)", flush=True)
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
                    
                    # Switch to X window (open new one if closed)
                    print("\n🧵 Switching to X compose window...\n", flush=True)
                    
                    try:
                        # Check if X window still exists
                        if x_tab_handle and x_tab_handle in driver.window_handles:
                            # X window exists, switch to it
                            print("  🔄 Switching to existing X window...", flush=True)
                            driver.switch_to.window(x_tab_handle)
                            
                            # Bring window to front and maximize
                            driver.maximize_window()
                            
                            current_url = driver.current_url
                            print(f"  📍 Current URL: {current_url}", flush=True)
                            
                            # Navigate to compose - use the home page with compose trigger
                            print("  📝 Opening compose...", flush=True)
                            
                            # First navigate to home if not already there
                            if 'x.com/home' not in current_url and 'twitter.com/home' not in current_url:
                                driver.get("https://x.com/home")
                                time.sleep(2)
                            
                            # Open compose modal via JavaScript (more reliable than URL)
                            try:
                                # Click the compose button if available
                                compose_button = driver.find_element(By.CSS_SELECTOR, 'a[data-testid="SideNav_NewTweet_Button"]')
                                driver.execute_script("arguments[0].click();", compose_button)
                                print("  ✅ Opened compose via button click", flush=True)
                                time.sleep(2)
                            except:
                                # Fallback to URL navigation
                                print("  📝 Using compose URL (fallback)...", flush=True)
                                driver.get("https://x.com/compose/post")
                                time.sleep(3)
                        else:
                            # X window was closed, open new one
                            print("  📑 Opening new X compose window...", flush=True)
                            
                            # Open X home page in new tab
                            driver.execute_script("window.open('https://x.com/home', '_blank');")
                            time.sleep(2)
                            driver.switch_to.window(driver.window_handles[-1])
                            x_tab_handle = driver.current_window_handle
                            time.sleep(3)
                            
                            # Now open compose modal
                            try:
                                compose_button = driver.find_element(By.CSS_SELECTOR, 'a[data-testid="SideNav_NewTweet_Button"]')
                                driver.execute_script("arguments[0].click();", compose_button)
                                print("  ✅ Opened compose modal", flush=True)
                                time.sleep(2)
                            except:
                                # Fallback to compose URL
                                driver.get("https://x.com/compose/post")
                                time.sleep(3)
                            
                            print(f"  📍 Opened X window: {driver.current_url}", flush=True)
                    except Exception as tab_error:
                        print(f"  ⚠️  Window switching failed: {tab_error}")
                        # Fallback: try to find X window or open new one
                        x_found = False
                        for handle in driver.window_handles:
                            try:
                                driver.switch_to.window(handle)
                                if 'x.com' in driver.current_url or 'twitter.com' in driver.current_url:
                                    x_tab_handle = handle
                                    x_found = True
                                    print("  ✅ Found existing X window", flush=True)
                                    
                                    # Navigate to home and open compose
                                    if 'x.com/home' not in driver.current_url and 'twitter.com/home' not in driver.current_url:
                                        driver.get("https://x.com/home")
                                        time.sleep(2)
                                    
                                    try:
                                        compose_button = driver.find_element(By.CSS_SELECTOR, 'a[data-testid="SideNav_NewTweet_Button"]')
                                        driver.execute_script("arguments[0].click();", compose_button)
                                        time.sleep(2)
                                    except:
                                        driver.get("https://x.com/compose/post")
                                        time.sleep(3)
                                    break
                            except:
                                continue
                        
                        if not x_found:
                            # No X window found, open new one
                            print("  📑 Creating new X compose window...", flush=True)
                            driver.execute_script("window.open('https://x.com/home', '_blank');")
                            time.sleep(2)
                            driver.switch_to.window(driver.window_handles[-1])
                            x_tab_handle = driver.current_window_handle
                            time.sleep(3)
                            
                            # Open compose modal
                            try:
                                compose_button = driver.find_element(By.CSS_SELECTOR, 'a[data-testid="SideNav_NewTweet_Button"]')
                                driver.execute_script("arguments[0].click();", compose_button)
                                time.sleep(2)
                            except:
                                driver.get("https://x.com/compose/post")
                                time.sleep(3)
                    
                    # Verify compose opened and is fully ready
                    try:
                        print("  ⏳ Waiting for compose to be fully ready...")
                        
                        # Wait for textarea to be present
                        WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="tweetTextarea_0"]'))
                        )
                        
                        # Wait for file input to be present
                        WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[data-testid="fileInput"]'))
                        )
                        
                        print("  ✅ Compose window ready!")
                        
                        # Additional wait to ensure all JavaScript is loaded
                        time.sleep(3)
                    except Exception as e:
                        print(f"  ⚠️  Compose window may not be fully ready: {e}")
                        time.sleep(2)
                    
                    # Build the entire thread before posting
                    for i, batch in enumerate(batches):
                        batch_nums = list(range(i*4 + 1, i*4 + len(batch) + 1))
                        print(f"\n{'='*60}")
                        print(f"Tweet {i+1}/{len(batches)}")
                        print(f"📷 Images: {batch_nums[0]}-{batch_nums[-1]} ({len(batch)} files)")
                        print(f"{'='*60}")
                        
                        # Add tweet text for first tweet only (AFTER opening modal, BEFORE uploading images)
                        if i == 0:
                            try:
                                # Find the active text area in modal (tweet 0)
                                text_area = WebDriverWait(driver, 10).until(
                                    EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="tweetTextarea_0"]'))
                                )
                                
                                # Click to ensure focus
                                driver.execute_script("arguments[0].click();", text_area)
                                time.sleep(0.5)
                                
                                # Use send_keys for more natural input that X recognizes
                                from selenium.webdriver.common.keys import Keys
                                text_area.send_keys(post_title)
                                
                                print(f"  ✅ Added title: {post_title[:50]}...")
                                time.sleep(2)  # Let text register properly
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
                    
                    # Final wait to ensure everything is stable
                    print("  ⏳ Final stability check before posting...")
                    time.sleep(2)
                    
                    # Check for any X errors before posting
                    if check_for_x_error(driver):
                        print("  ⚠️  X is showing an error. Waiting and retrying...")
                        time.sleep(5)
                    
                    # Try to post with retries and exponential backoff
                    posted = False
                    for attempt in range(5):
                        if attempt > 0:
                            wait_time = 3 * (attempt + 1)  # 3s, 6s, 9s, 12s, 15s
                            print(f"  🔄 Retry {attempt}/4 (waiting {wait_time}s)...")
                            time.sleep(wait_time)
                        
                        if click_post_button_selenium(driver, inline=False):
                            time.sleep(3)  # Wait for post to process
                            
                            # Check if X showed an error
                            if check_for_x_error(driver):
                                print("  ⚠️  X returned an error after clicking Post")
                                continue
                            
                            posted = True
                            break
                    
                    if not posted:
                        print("  ⚠️  Failed to auto-post thread after 5 attempts.")
                        print("  📋 Thread is ready in composer - verify and post manually")
                        print("  💡 Common issues: rate limit, media still uploading, or X temporary error")
                        input("     Press Enter after you post manually to continue...")
                    else:
                        print("  ⏳ Waiting for thread to post...")
                        time.sleep(5)
                    
                    print("\n" + "="*60)
                    print("🎉 Thread complete!")
                    print("="*60)
                    
                    # Mark as completed
                    completion_status[reddit_url] = 'completed'
                    
                    # Switch back to Reddit window (keep X window open)
                    try:
                        # Find and switch back to Reddit window
                        if reddit_tab_handle and reddit_tab_handle in driver.window_handles:
                            driver.switch_to.window(reddit_tab_handle)
                            print("✅ Switched back to Reddit window - ready for next post\n", flush=True)
                        else:
                            # Reddit window handle lost, use first available non-X window
                            for handle in driver.window_handles:
                                driver.switch_to.window(handle)
                                if 'x.com' not in driver.current_url and 'twitter.com' not in driver.current_url:
                                    reddit_tab_handle = handle
                                    print("✅ Switched back to first window - ready for next post\n", flush=True)
                                    break
                            else:
                                # All windows are X, just stay on first one
                                driver.switch_to.window(driver.window_handles[0])
                                reddit_tab_handle = driver.window_handles[0]
                                print("✅ Ready for next post\n", flush=True)
                    except Exception as window_error:
                        print(f"⚠️  Window switching failed: {window_error}")
                        if not check_and_recover_window(driver):
                            raise
                    
                    # Clear temp directory
                    for filename in os.listdir(tmpdir):
                        file_path = os.path.join(tmpdir, filename)
                        if os.path.isfile(file_path):
                            os.remove(file_path)

                    print("✅ Done! Post processed successfully.\n", flush=True)
                    
                except Exception as e:
                    print(f"❌ Error processing post: {e}", flush=True)
                    import traceback
                    traceback.print_exc()
                    
                    # Mark as failed
                    if reddit_url:
                        completion_status[reddit_url] = 'failed'
                    
                    # Close X tab and return to Reddit on error
                    try:
                        if len(driver.window_handles) > 1:
                            driver.close()
                            driver.switch_to.window(driver.window_handles[0])
                    except:
                        pass
                    
                    print("🔄 Ready for next post...\n", flush=True)
                    # Continue to next item in queue instead of stopping
                    
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