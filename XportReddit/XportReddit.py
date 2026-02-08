# filepath: e:\Projects\scripts\XportReddit.py
import os
import requests
from tqdm import tqdm
import shutil
import time
import random
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
import json
from pathlib import Path

# ============================================================
# CONFIGURATION
# ============================================================
UPLOAD_TIMEOUT = 90     # Max seconds to wait for media uploads
POST_RETRY_ATTEMPTS = 5 # Number of times to retry posting
SAVED_POSTS_FILE = "reddit_saved_posts.json"  # File to read URLs from
POSTED_URLS_FILE = "reddit_posted_urls.json"  # File to store successfully posted URLs
# ============================================================

# ============================================================
# ANTI-BOTTING HELPERS
# ============================================================
def ensure_x_tab_active(driver):
    """Ensure we're on an X tab and switch to it if needed.
    
    Args:
        driver: WebDriver instance
        
    Returns:
        bool: True if X tab is active
    """
    try:
        current_url = driver.current_url
        # If already on X, we're good
        if 'x.com' in current_url or 'twitter.com' in current_url:
            return True
        
        # Check all windows/tabs for X
        original_window = driver.current_window_handle
        for window_handle in driver.window_handles:
            driver.switch_to.window(window_handle)
            if 'x.com' in driver.current_url or 'twitter.com' in driver.current_url:
                print(f"  🔄 Switched to X tab", flush=True)
                return True
        
        # No X tab found, switch back to original
        driver.switch_to.window(original_window)
        return False
    except:
        return False

def human_delay(base_seconds, variance=0.3):
    """Add human-like randomized delay.
    
    Args:
        base_seconds: Base delay time
        variance: Randomization factor (0.3 = ±30%)
    """
    min_delay = base_seconds * (1 - variance)
    max_delay = base_seconds * (1 + variance)
    delay = random.uniform(min_delay, max_delay)
    time.sleep(delay)

def human_type(element, text, min_delay=0.05, max_delay=0.15, with_typos=False):
    """Type text character-by-character with human-like delays.
    
    Args:
        element: Selenium WebElement to type into
        text: Text to type
        min_delay: Minimum delay between characters (seconds)
        max_delay: Maximum delay between characters (seconds)
        with_typos: Whether to simulate occasional typos and corrections
    """
    # Common typo patterns (nearby keys)
    typo_map = {
        'a': ['s', 'q', 'w'], 'b': ['v', 'n', 'g'], 'c': ['x', 'v', 'd'],
        'd': ['s', 'f', 'e'], 'e': ['w', 'r', 'd'], 'f': ['d', 'g', 'r'],
        'g': ['f', 'h', 't'], 'h': ['g', 'j', 'y'], 'i': ['u', 'o', 'k'],
        'j': ['h', 'k', 'u'], 'k': ['j', 'l', 'i'], 'l': ['k', 'o', 'p'],
        'm': ['n', 'j', 'k'], 'n': ['b', 'm', 'h'], 'o': ['i', 'p', 'l'],
        'p': ['o', 'l'], 'q': ['w', 'a'], 'r': ['e', 't', 'f'],
        's': ['a', 'd', 'w'], 't': ['r', 'y', 'g'], 'u': ['y', 'i', 'j'],
        'v': ['c', 'b', 'f'], 'w': ['q', 'e', 's'], 'x': ['z', 'c', 's'],
        'y': ['t', 'u', 'h'], 'z': ['x', 'a']
    }
    
    i = 0
    while i < len(text):
        char = text[i]
        
        # Simulate typo occasionally (5% chance for non-space characters)
        if with_typos and char.lower() in typo_map and random.random() < 0.05:
            # Type wrong character
            wrong_char = random.choice(typo_map[char.lower()])
            if char.isupper():
                wrong_char = wrong_char.upper()
            
            element.send_keys(wrong_char)
            time.sleep(random.uniform(min_delay, max_delay))
            
            # Brief pause (noticing the mistake)
            time.sleep(random.uniform(0.1, 0.3))
            
            # Delete the wrong character
            element.send_keys(Keys.BACKSPACE)
            time.sleep(random.uniform(0.05, 0.1))
            
            # Type the correct character
            element.send_keys(char)
            time.sleep(random.uniform(min_delay, max_delay))
        else:
            # Type normally
            element.send_keys(char)
            time.sleep(random.uniform(min_delay, max_delay))
        
        # Occasional longer pause (like thinking or looking at source)
        if random.random() < 0.15:  # 15% chance
            time.sleep(random.uniform(0.2, 0.6))
        
        i += 1
    
    # Final pause after typing complete
    if random.random() < 0.3:  # 30% chance
        time.sleep(random.uniform(0.3, 0.8))

def move_to_element_naturally(driver, element):
    """Move mouse to element with ActionChains for more natural interaction.
    
    Args:
        driver: Selenium WebDriver
        element: Element to move to
    """
    try:
        action = ActionChains(driver)
        action.move_to_element(element).perform()
        human_delay(0.2, variance=0.5)  # Small pause after moving
    except:
        pass  # If movement fails, continue anyway

def visit_profile_and_scroll(driver):
    """Visit profile page and scroll to simulate human browsing behavior.
    
    Args:
        driver: WebDriver instance
    """
    try:
        print("\n👤 [HUMAN BEHAVIOR] Visiting profile...")
        
        # Click profile link
        profile_link = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="AppTabBar_Profile_Link"]'))
        )
        driver.execute_script("arguments[0].click();", profile_link)
        human_delay(2.0, variance=0.5)
        
        # Scroll down the profile a few times
        scroll_count = random.randint(3, 6)
        print(f"   Scrolling profile {scroll_count} times...")
        
        for i in range(scroll_count):
            # Scroll by a random amount
            scroll_amount = random.randint(300, 700)
            driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
            
            # Random pause between scrolls (like reading)
            human_delay(random.uniform(1.5, 3.5), variance=0.3)
        
        # Scroll back to top occasionally
        if random.random() < 0.4:  # 40% chance
            print("   Scrolling back to top...")
            driver.execute_script("window.scrollTo(0, 0);")
            human_delay(1.0, variance=0.4)
        
        # Return to home feed
        print("   Returning to home feed...")
        home_link = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="AppTabBar_Home_Link"]'))
        )
        driver.execute_script("arguments[0].click();", home_link)
        human_delay(2.0, variance=0.5)
        
        print("✅ Profile visit complete\n")
        return True
        
    except Exception as e:
        print(f"⚠️  Could not visit profile: {e}")
        # Try to get back to home anyway
        try:
            driver.get("https://x.com/home")
            human_delay(2.0, variance=0.3)
        except:
            pass
        return False

# ============================================================

def load_saved_posts():
    """Load saved posts from JSON file.
    
    Returns:
        list: List of Reddit post URLs
    """
    # Check Downloads folder first
    downloads_path = Path.home() / "Downloads" / SAVED_POSTS_FILE
    script_path = Path(__file__).parent / SAVED_POSTS_FILE
    
    json_file = None
    if downloads_path.exists():
        json_file = downloads_path
        print(f"📂 Found {SAVED_POSTS_FILE} in Downloads folder")
    elif script_path.exists():
        json_file = script_path
        print(f"📂 Found {SAVED_POSTS_FILE} in script directory")
    else:
        print(f"❌ Could not find {SAVED_POSTS_FILE}")
        print(f"   Looked in:")
        print(f"   - {downloads_path}")
        print(f"   - {script_path}")
        return []
    
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        urls = data.get('urls', [])
        print(f"✅ Loaded {len(urls)} saved posts from {json_file.name}")
        return urls
    except Exception as e:
        print(f"❌ Error reading JSON file: {e}")
        return []

def save_saved_posts(urls):
    """Save updated posts list back to JSON file.
    
    Args:
        urls: Updated list of Reddit post URLs
    """
    # Use the same path logic as load_saved_posts
    downloads_path = Path.home() / "Downloads" / SAVED_POSTS_FILE
    script_path = Path(__file__).parent / SAVED_POSTS_FILE
    
    json_file = None
    if downloads_path.exists():
        json_file = downloads_path
    elif script_path.exists():
        json_file = script_path
    else:
        # Default to Downloads if no file exists yet
        json_file = downloads_path
    
    try:
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump({'urls': urls}, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"⚠️  Warning: Could not save updated list: {e}")
        return False

def add_to_posted_urls(url, status='success'):
    """Add URL to the posted URLs archive file.
    
    Args:
        url: Reddit post URL that was posted
        status: Status of the post ('success', 'manual', 'skipped')
    """
    # Use the same directory as the main saved posts file
    downloads_path = Path.home() / "Downloads" / POSTED_URLS_FILE
    script_path = Path(__file__).parent / POSTED_URLS_FILE
    
    # Determine which path to use
    main_file_downloads = Path.home() / "Downloads" / SAVED_POSTS_FILE
    if main_file_downloads.exists():
        json_file = downloads_path
    else:
        json_file = script_path
    
    # Load existing posted URLs or create new list
    posted_data = {'urls': []}
    if json_file.exists():
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                posted_data = json.load(f)
        except:
            posted_data = {'urls': []}
    
    # Add new entry with timestamp
    from datetime import datetime
    entry = {
        'url': url,
        'status': status,
        'posted_at': datetime.now().isoformat()
    }
    posted_data['urls'].append(entry)
    
    # Save updated list
    try:
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(posted_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"⚠️  Warning: Could not save to posted URLs archive: {e}")
        return False

def get_reddit_images(post_url):
    """Fetch images from Reddit post.
    
    Returns:
        tuple: (image_urls, post_title)
    """
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

def check_if_post_published(driver, post_title, timeout=5):
    """Check if the post was successfully published by looking for the title text on the page.
    
    Args:
        driver: WebDriver instance
        post_title: Title text to search for
        timeout: Maximum time to wait
        
    Returns:
        bool: True if post appears to be published
    """
    try:
        # Primary check: Is compose modal closed?
        # This is more reliable than text search
        start_time = time.time()
        modal_closed = False
        url_changed = False
        initial_url = driver.current_url
        
        end_time = time.time() + timeout
        while time.time() < end_time:
            # Check if compose modal is closed
            try:
                compose_modal = driver.find_element(By.CSS_SELECTOR, '[aria-labelledby="modal-header"]')
                if not compose_modal.is_displayed():
                    modal_closed = True
            except:
                # Modal not found = closed
                modal_closed = True
            
            # Check if URL changed (navigated to post page)
            if driver.current_url != initial_url and 'status' in driver.current_url:
                url_changed = True
            
            # If modal closed, verify with title check (but only after modal is gone)
            if modal_closed:
                # Filter title for comparison (same as what we posted)
                filtered_title = ''.join(char for char in post_title if ord(char) <= 0xFFFF)
                search_text = filtered_title[:50]
                
                page_source = driver.page_source
                # Look for the title OUTSIDE the compose textarea
                # Check it appears in the timeline/feed area
                if search_text in page_source or url_changed:
                    # Wait a bit to ensure it's stable
                    if time.time() - start_time > 2:
                        return True
            
            human_delay(0.5, variance=0.4)
        
        # If modal closed even without text match, likely posted
        return modal_closed
    except Exception as e:
        print(f"  ⚠️  Could not verify post publication: {e}")
        return False

def check_for_x_error(driver):
    """Check if X is showing an error message."""
    try:
        error_messages = [
            "Something went wrong",
            "Try again",
            "Error",
            "didn't go through",
            "You are over the daily limit",
            "rate limit"
        ]
        
        for msg in error_messages:
            elements = driver.find_elements(By.XPATH, f"//*[contains(text(), '{msg}')]")
            if elements:
                # Check specifically for rate limit
                if 'limit' in msg.lower():
                    print(f"  ⚠️  RATE LIMIT detected! X may be temporarily blocking posts.")
                return True
        return False
    except:
        return False

def check_for_duplicate_post(driver):
    """Check if X is showing 'Already said that' duplicate error.
    
    Returns:
        bool: True if duplicate post error detected
    """
    try:
        duplicate_messages = [
            "Already said that",
            "You already said that",
            "already posted"
        ]
        
        for msg in duplicate_messages:
            elements = driver.find_elements(By.XPATH, f"//*[contains(text(), '{msg}')]")
            if elements:
                return True
        return False
    except:
        return False

def wait_for_upload_completion(driver, timeout=UPLOAD_TIMEOUT):
    """Wait for all media uploads to complete (important for videos).
    
    Args:
        driver: WebDriver instance
        timeout: Maximum time to wait in seconds
    """
    print("  ⏳ Waiting for uploads to complete...")
    start_time = time.time()
    last_status_check = start_time
    last_button_state = None
    
    while time.time() - start_time < timeout:
        try:
            # Primary check: Post button state (disabled = still uploading)
            post_buttons = driver.find_elements(By.CSS_SELECTOR, '[data-testid="tweetButton"], [data-testid="tweetButtonInline"]')
            
            button_enabled = False
            for button in post_buttons:
                if button.is_displayed():
                    is_disabled = button.get_attribute('disabled') or button.get_attribute('aria-disabled') == 'true'
                    if not is_disabled:
                        button_enabled = True
                        
                    # Log button state changes
                    current_state = 'enabled' if not is_disabled else 'disabled'
                    if last_button_state != current_state:
                        if time.time() - start_time > 2:  # Only log after initial wait
                            print(f"  🔘 Post button: {current_state}", flush=True)
                        last_button_state = current_state
                    break
            
            # Secondary check: Look for upload status text (less reliable)
            status_keywords = ['Uploading', 'Processing', 'Encoding', 'Compressing', 'Preparing']
            has_upload_status = False
            
            for keyword in status_keywords:
                elements = driver.find_elements(By.XPATH, f"//*[contains(text(), '{keyword}')]")
                if len(elements) > 0:
                    has_upload_status = True
                    # Print status periodically
                    if time.time() - last_status_check > 3:  # Every 3 seconds
                        print(f"  ⏳ Media still {keyword.lower()}...", flush=True)
                        last_status_check = time.time()
                    break
            
            # Upload complete when button is enabled AND no status text
            if button_enabled and not has_upload_status:
                print("  ✅ All uploads completed!")
                return True
            
            # If button stays disabled for too long, something may be wrong
            if time.time() - start_time > 30 and not button_enabled:
                print(f"  ⚠️  Button still disabled after 30s, checking status...", flush=True)
            
            human_delay(1.0, variance=0.3)
            
        except Exception as e:
            # If we can't check, assume it's done
            print(f"  ⚠️  Could not check upload status: {e}")
            human_delay(2.0, variance=0.3)
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
        print(f"\n  📤 Uploading {len(image_paths)} file(s) to tweet {tweet_index + 1}...")
        
        # Check if any files are videos (need upload feedback)
        video_extensions = ['.mp4', '.mov', '.avi', '.webm', '.mkv', '.flv', '.gif']
        has_video = any(any(path.lower().endswith(ext) for ext in video_extensions) for path in image_paths)
        
        # Find the file input element (X uses a hidden input with data-testid="fileInput")
        file_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[data-testid="fileInput"]'))
        )
        
        # Send all file paths at once (newline-separated for multiple files)
        files_string = '\n'.join(image_paths)
        file_input.send_keys(files_string)
        
        print(f"  ✅ Files sent to upload!")
        
        # Only wait for upload feedback if we have videos (images are nearly instant)
        if has_video:
            print(f"  ℹ️  Video detected, waiting for upload to complete...", flush=True)
            human_delay(2.0, variance=0.3)  # Initial wait for upload to start
            wait_for_upload_completion(driver, timeout=60)
        else:
            # Images upload quickly, just brief wait
            human_delay(2.0, variance=0.3)
            print(f"  ✅ Images ready!", flush=True)
        
        return True
        
    except TimeoutException:
        print(f"  ⚠️  Could not find file input element")
        return False
    except Exception as e:
        print(f"  ⚠️  Upload failed: {e}")
        return False

def click_post_button_selenium(driver):
    """Click the Post button using Selenium.
    
    Args:
        driver: WebDriver instance
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
        human_delay(2.0, variance=0.4)  # Wait for action to complete
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
        human_delay(3.0, variance=0.4)  # Wait for new textarea to appear and be ready
        return True
    except Exception as e:
        print(f"  ⚠️  Failed to click add button: {e}")
        return False

def prompt_user_for_post_action(post_title, auto_mode=False):
    """Prompt user for action on a post.
    
    Args:
        post_title: The title of the post
        auto_mode: If True, automatically accept posts without prompting
        
    Returns:
        tuple: (action, custom_title) where action is 'y'/'r'/'n'/'s'/'q'/'a' and custom_title is the new title if action is 'n' or 'r'
    """
    if auto_mode:
        print(f"\n{'='*60}")
        print(f"📄 [AUTO] Post: {post_title}")
        print(f"{'='*60}")
        return 'y', None
    
    print(f"\n{'='*60}")
    print(f"📄 Post: {post_title}")
    print(f"{'='*60}")
    print("Options:")
    print("  y = Post with original title")
    print("  a = Auto-process remaining posts")
    print("  r = Reword title (edit original)")
    print("  n = Enter new title")
    print("  s = Skip this post")
    print("  q = Quit")
    
    while True:
        choice = input("\nYour choice [y/a/r/n/s/q]: ").lower().strip()
        
        if choice in ['y', 'a', 's', 'q']:
            return choice, None
        elif choice == 'r':
            # Pre-fill with original title for editing
            try:
                import readline
                def prefill_input():
                    readline.insert_text(post_title)
                    readline.redisplay()
                readline.set_pre_input_hook(prefill_input)
                custom_title = input("Edit title: ").strip()
                readline.set_pre_input_hook()  # Clear the hook
            except (ImportError, AttributeError):
                # Fallback for systems without readline
                print(f"\nOriginal: {post_title}")
                custom_title = input("Reword title: ").strip()
            
            if custom_title:
                return 'r', custom_title
            else:
                print("⚠️  Title cannot be empty. Try again.")
        elif choice == 'n':
            custom_title = input("Enter new title: ").strip()
            if custom_title:
                return 'n', custom_title
            else:
                print("⚠️  Title cannot be empty. Try again.")
        else:
            print("⚠️  Invalid choice. Please enter y, r, n, s, or q.")



def open_x_compose(driver):
    """Open the compose modal on X.
    
    Args:
        driver: WebDriver instance
        
    Returns:
        bool: True if compose opened successfully
    """
    print("  📝 Opening compose modal...", flush=True)
    
    try:        # Make sure we're on the X tab
        if not ensure_x_tab_active(driver):
            print("⚠️  Not on X tab, navigating...", flush=True)
            driver.get("https://x.com/home")
            human_delay(3.0, variance=0.3)        
        # First, check if compose is already open (from previous post)
        try:
            existing_compose = driver.find_element(By.CSS_SELECTOR, '[data-testid="tweetTextarea_0"]')
            if existing_compose:
                print("  ℹ️  Compose already open from previous post, closing it...", flush=True)
                # Press Escape to close the modal
                from selenium.webdriver.common.keys import Keys
                from selenium.webdriver.common.action_chains import ActionChains
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                human_delay(1.0, variance=0.5)
        except:
            pass  # No existing compose, which is good
        
        # Make sure we're on X home
        if 'x.com/home' not in driver.current_url:
            driver.get("https://x.com/home")
            human_delay(3.0, variance=0.3)
        
        # Try clicking the compose button
        try:
            compose_button = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'a[data-testid="SideNav_NewTweet_Button"]'))
            )
            driver.execute_script("arguments[0].click();", compose_button)
            print("  ✅ Compose modal opened", flush=True)
            human_delay(2.0, variance=0.4)
            return True
        except:
            # Fallback: use keyboard shortcut
            from selenium.webdriver.common.action_chains import ActionChains
            ActionChains(driver).send_keys('n').perform()
            human_delay(2.0, variance=0.4)
            print("  ✅ Compose opened via keyboard", flush=True)
            return True
            
    except Exception as e:
        print(f"  ⚠️  Failed to open compose: {e}", flush=True)
        return False

if __name__ == "__main__":
    print("🚀 XportReddit - Reddit to X Thread Automation\n")
    
    # Load saved posts from JSON file
    reddit_urls = load_saved_posts()
    
    if not reddit_urls:
        print("\n❌ No posts found. Please run parse_reddit_export.py first or")
        print("   use the browser extension to create reddit_saved_posts.json")
        exit(1)
    
    print(f"\n📋 Ready to process {len(reddit_urls)} saved posts\n")
    
    # Initialize Selenium WebDriver with Edge
    print("🌐 Starting Edge browser...")
    
    try:
        from selenium.webdriver.edge.options import Options
        import subprocess
        import socket
        
        options = Options()
        debug_port = 9222
        
        # Kill existing Edge processes
        print("   Closing existing Edge windows...")
        subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], 
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        
        # Start Edge with debugging
        print("   Starting Edge...")
        edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        subprocess.Popen([
            edge_path, 
            f'--remote-debugging-port={debug_port}',
            '--no-first-run',
            '--no-default-browser-check',
            'https://x.com/home'
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
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
        
        print("   Waiting for browser to start...")
        for i in range(15):
            time.sleep(1)
            if is_port_open(debug_port):
                break
        else:
            raise Exception("Edge did not start with debugging port")
        
        # Connect to Edge
        options.add_experimental_option("debuggerAddress", f"127.0.0.1:{debug_port}")
        driver = webdriver.Edge(options=options)
        
        print("✅ Connected to Edge!")
        print("   Make sure you're logged into X (Twitter)\n")
        time.sleep(3)
        
    except Exception as e:
        print(f"❌ Failed to start Edge: {e}")
        print("   Make sure:")
        print("   - Edge is installed")
        print("   - pip install selenium")
        exit(1)
    
    # Create temp directory for downloads
    tmpdir = os.path.join(os.path.dirname(__file__), 'temp_downloads')
    os.makedirs(tmpdir, exist_ok=True)
    
    # Counters
    posts_processed = 0
    posts_skipped = 0
    posts_failed = 0
    total_posts = len(reddit_urls)  # Capture original total before processing
    auto_mode = False  # Toggle for auto-processing
    posts_since_profile_visit = 0  # Track when to visit profile
    next_profile_visit = random.randint(5, 10)  # Visit profile every 5-10 posts
    
    try:
        # Process each saved post (iterate over a copy to avoid issues when removing items)
        for idx, reddit_url in enumerate(reddit_urls[:], 1):
            print(f"\n{'='*60}")
            print(f"POST {idx}/{total_posts}")
            print(f"{'='*60}")
            
            # Fetch post title from Reddit
            print(f"📥 Fetching post info from Reddit...")
            try:
                _, original_title = get_reddit_images(reddit_url)
            except Exception as e:
                print(f"❌ Failed to fetch post: {e}")
                posts_failed += 1
                continue
            
            action, custom_title = prompt_user_for_post_action(original_title, auto_mode=auto_mode)
            
            if action == 'a':
                print("\n🤖 AUTO MODE ENABLED")
                print("   Posts will be processed automatically with human-like delays")
                print("   Typing will include occasional typos and corrections")
                print("   Press Ctrl+C to stop at any time\n")
                auto_mode = True
                action = 'y'  # Process this post
            
            if action == 'q':
                print("\n👋 Quitting...")
                break
            elif action == 's':
                print("⏭️  Skipping...", flush=True)
                posts_skipped += 1
                
                # Archive and remove from list
                add_to_posted_urls(reddit_url, status='skipped')
                reddit_urls.remove(reddit_url)
                if save_saved_posts(reddit_urls):
                    print(f"✅ Archived and removed from list ({len(reddit_urls)} remaining)\n")
                else:
                    print(f"⚠️  Could not update list file\n")
                continue
            
            # Determine the title to use
            post_title = original_title
            if action in ['n', 'r'] and custom_title:
                post_title = custom_title
                print(f"✏️  Using custom title: {post_title}")
            
            try:
                print(f"\n📥 Fetching media from Reddit...", flush=True)
                image_urls, _ = get_reddit_images(reddit_url)
                
                if not image_urls:
                    print("❌ No images found in this post.", flush=True)
                    continue

                file_paths = download_images(image_urls, tmpdir)
                batches = batch_images_for_x(file_paths)
                
                print(f"\n📊 Found {len(image_urls)} images -> Creating {len(batches)} tweet(s) in thread")
                
                # Open or switch to X tab
                print("\n🧵 Setting up X compose...\n", flush=True)
                
                # Ensure we're on the X tab
                ensure_x_tab_active(driver)
                
                # Make sure we're on X home
                if 'x.com' not in driver.current_url and 'twitter.com' not in driver.current_url:
                    print("  ⏳ Navigating to X...", flush=True)
                    driver.get("https://x.com/home")
                    time.sleep(3)
                
                # Open compose modal
                open_x_compose(driver)
                
                # Verify compose modal is ready
                print("  ⏳ Waiting for compose to load...", flush=True)
                try:
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="tweetTextarea_0"]'))
                    )
                    WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'input[data-testid="fileInput"]'))
                    )
                    print("  ✅ Compose ready!", flush=True)
                    time.sleep(2)
                except Exception as e:
                    print(f"  ❌ Compose not ready: {e}", flush=True)
                    print("  💡 Please open compose manually (click + button or press N)")
                    input("     Press Enter when compose is open...")
                    time.sleep(1)
                
                # Build the entire thread before posting
                for i, batch in enumerate(batches):
                    batch_nums = list(range(i*4 + 1, i*4 + len(batch) + 1))
                    print(f"\n{'='*60}")
                    print(f"Tweet {i+1}/{len(batches)} - Images: {batch_nums[0]}-{batch_nums[-1]} ({len(batch)} files)")
                    print(f"{'='*60}")
                    
                    # Add tweet text for first tweet only
                    if i == 0:
                        try:
                            # Ensure we're on the correct tab
                            ensure_x_tab_active(driver)
                            
                            # Find the active text area in modal (tweet 0)
                            text_area = WebDriverWait(driver, 10).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="tweetTextarea_0"]'))
                            )
                            
                            # Click to ensure focus
                            move_to_element_naturally(driver, text_area)
                            driver.execute_script("arguments[0].click();", text_area)
                            human_delay(0.4, variance=0.5)
                            
                            # Filter out non-BMP characters (emoji and special Unicode) for EdgeDriver
                            # Keep only characters in the Basic Multilingual Plane (U+0000 to U+FFFF)
                            filtered_title = ''.join(char for char in post_title if ord(char) <= 0xFFFF)
                            
                            # Type with human-like delays between characters
                            print(f"  ⌨️  Typing title{'...' if not auto_mode else ' (with realistic typing)...'}")
                            human_type(text_area, filtered_title, min_delay=0.03, max_delay=0.12, with_typos=auto_mode)
                            
                            print(f"  ✅ Added title: {filtered_title[:50]}{'...' if len(filtered_title) > 50 else ''}")
                            human_delay(1.5, variance=0.4)  # Let text register properly
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
                human_delay(2.0, variance=0.4)
                
                # Try to post with retries and exponential backoff
                posted = False
                for attempt in range(POST_RETRY_ATTEMPTS):
                    if attempt > 0:
                        # Before retrying, check if previous attempt actually posted
                        print(f"  🔍 Checking if post was already published...")
                        if check_if_post_published(driver, post_title, timeout=3):
                            print(f"  ✅ Post found on page - previous attempt succeeded!")
                            posted = True
                            break
                        
                        base_wait = 3 * (attempt + 1)  # 3s, 6s, 9s, 12s, 15s
                        wait_time = base_wait + random.uniform(-0.5, 1.5)  # Add jitter
                        print(f"  🔄 Retry {attempt}/{POST_RETRY_ATTEMPTS-1} (waiting ~{base_wait}s)...", flush=True)
                        time.sleep(wait_time)
                    
                    if click_post_button_selenium(driver):
                        human_delay(3.0, variance=0.3)  # Wait for post to process
                        
                        # Check for duplicate post error first
                        if check_for_duplicate_post(driver):
                            print("  ⚠️  X says 'Already said that' - duplicate content detected")
                            print("  🚫 Closing composer and skipping to next post...")
                            # Close the composer
                            try:
                                from selenium.webdriver.common.action_chains import ActionChains
                                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                                human_delay(1.0, variance=0.3)
                            except:
                                pass
                            # Mark as skipped and break out of retry loop
                            posts_failed += 1
                            add_to_posted_urls(reddit_url, status='skipped')
                            reddit_urls.remove(reddit_url)
                            save_saved_posts(reddit_urls)
                            posted = None  # Signal to skip further processing
                            break
                        
                        # Check if post was published successfully
                        print(f"  🔍 Verifying post publication...")
                        if check_if_post_published(driver, post_title, timeout=5):
                            print(f"  ✅ Post verified on page!")
                            posted = True
                            break
                        
                        # Check if X showed an error
                        if check_for_x_error(driver):
                            print("  ⚠️  X returned an error after clicking Post")
                            continue
                        
                        # If no error but not verified, might need more time
                        print("  ⚠️  Post not verified yet, will retry...")
                
                # Skip to next post if duplicate detected
                if posted is None:
                    print("\n⏭️  Skipped duplicate post\n")
                    continue
                
                if not posted:
                    print(f"  ⚠️  Failed to auto-post thread after {POST_RETRY_ATTEMPTS} attempts.", flush=True)
                    print("  📋 Thread is ready in composer - you can post manually", flush=True)
                    print("\n  💡 Common issues:", flush=True)
                    print("     - X rate limit (try again later)", flush=True)
                    print("     - Media still processing (wait a bit longer)", flush=True)
                    print("     - X temporary error (refresh and try again)", flush=True)
                    print("     - Network connectivity issue\n", flush=True)
                    user_choice = input("  Choose: [p]ost manually and continue, [s]kip this post, or [q]uit: ").lower().strip()
                    
                    if user_choice == 'p':
                        print("  ⏳ Waiting for manual post...", flush=True)
                        input("     Press Enter after you post manually...")
                        # Archive as manually posted
                        add_to_posted_urls(reddit_url, status='manual')
                        reddit_urls.remove(reddit_url)
                        save_saved_posts(reddit_urls)
                    elif user_choice == 's':
                        print("  ⏭️  Skipping this post", flush=True)
                        posts_failed += 1
                        # Archive as skipped
                        add_to_posted_urls(reddit_url, status='skipped')
                        reddit_urls.remove(reddit_url)
                        save_saved_posts(reddit_urls)
                    elif user_choice == 'q':
                        print("  👋 Quitting...", flush=True)
                        raise KeyboardInterrupt()
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
                posts_processed += 1
                posts_since_profile_visit += 1
                
                # Archive successful post and remove from pending list
                add_to_posted_urls(reddit_url, status='success')
                reddit_urls.remove(reddit_url)
                save_saved_posts(reddit_urls)
                
                # Show progress
                remaining = len(reddit_urls)
                print(f"\n📊 Progress: {posts_processed} completed | {remaining} remaining")
                
                # Check if we should visit profile (human-like behavior)
                if auto_mode and posts_since_profile_visit >= next_profile_visit:
                    print(f"\n🤖 [AUTO MODE] Posted {posts_since_profile_visit} posts, simulating profile check...")
                    if visit_profile_and_scroll(driver):
                        posts_since_profile_visit = 0
                        next_profile_visit = random.randint(5, 10)
                        print(f"   Next profile visit in {next_profile_visit} posts\n")
                
                # Add delay between posts in auto mode (5-10 seconds per image)
                if auto_mode and idx < len(reddit_urls):
                    min_delay = len(image_urls) * 5
                    max_delay = len(image_urls) * 10
                    delay = random.uniform(min_delay, max_delay)
                    remaining = len(reddit_urls)
                    print(f"\n⏸️  [AUTO MODE] Waiting {delay:.0f}s before next post ({len(image_urls)} images × 5-10s)...")
                    print(f"   Progress: {posts_processed} completed | {remaining} remaining")
                    print("   (Press Ctrl+C to stop)\n")
                    time.sleep(delay)
                
            except Exception as e:
                print(f"❌ Error processing post: {e}", flush=True)
                import traceback
                traceback.print_exc()
                posts_failed += 1
                
                # Clear temp files
                try:
                    for filename in os.listdir(tmpdir):
                        file_path = os.path.join(tmpdir, filename)
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                except:
                    pass
                
                print("🔄 Ready for next post...\n", flush=True)
        
        # Print summary
        print("\n" + "="*60)
        print("📊 SUMMARY")
        print("="*60)
        print(f"✅ Posts processed: {posts_processed}")
        print(f"⏭️  Posts skipped: {posts_skipped}")
        print(f"❌ Posts failed: {posts_failed}")
        print(f"📋 Total posts: {total_posts}")
        print("="*60)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        print("\n" + "="*60)
        print("📊 SUMMARY")
        print("="*60)
        print(f"✅ Posts processed: {posts_processed}")
        print(f"⏭️  Posts skipped: {posts_skipped}")
        print(f"❌ Posts failed: {posts_failed}")
        print(f"📋 Total attempted: {posts_processed + posts_skipped + posts_failed}/{total_posts}")
        print("="*60)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            # Clean up temp directory
            if os.path.exists(tmpdir):
                shutil.rmtree(tmpdir)
            
            print("\n🔒 Closing browser...")
            driver.quit()
            print("✅ Done. Goodbye!")
        except:
            pass