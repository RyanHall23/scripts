import os
import requests
from tqdm import tqdm
import webbrowser
import tempfile
import shutil

def get_reddit_images(post_url):
    # Ensure .json endpoint
    if not post_url.endswith('.json'):
        if post_url.endswith('/'):
            post_url += '.json'
        else:
            post_url += '/.json'
    headers = {'User-Agent': 'Mozilla/5.0'}
    resp = requests.get(post_url, headers=headers)
    resp.raise_for_status()
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

def open_folder(folder):
    # Open the folder in the OS file explorer
    if os.name == 'nt':
        os.startfile(folder)
    elif os.name == 'posix':
        os.system(f'xdg-open "{folder}"')
    else:
        print(f"Please open {folder} manually.")

def open_x_composer(text):
    url = f"https://x.com/intent/tweet?text={requests.utils.quote(text)}"
    webbrowser.open(url)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmpdir:
        while True:
            reddit_url = input("Enter Reddit post URL (or just press Enter to quit): ").strip()
            if not reddit_url:
                print("Goodbye!")
                break

            image_urls, post_title = get_reddit_images(reddit_url)
            if not image_urls:
                print("No images found.")
                continue

            download_images(image_urls, tmpdir)
            open_folder(tmpdir)
            tweet_text = post_title
            open_x_composer(tweet_text)
            try:
                input("Upload images and post the tweet, then press Enter for the next URL (Ctrl+C to quit)...")
                # Clear temp directory after user presses Enter
                for filename in os.listdir(tmpdir):
                    file_path = os.path.join(tmpdir, filename)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
            except KeyboardInterrupt:
                print("\nExiting. Temporary files will be cleaned up.")
                break

            print("Done! All images processed for this post.\n")