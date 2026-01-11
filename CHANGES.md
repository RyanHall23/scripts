# XportReddit - Changes Summary

## What Changed

The script has been completely rewritten to use the **Reddit API** instead of the browser extension approach.

### Old Approach
- Used a browser extension to send Reddit URLs to the script
- Flask server received URLs from the extension
- Manual browsing required to share posts

### New Approach
- Uses Reddit API (PRAW library) to fetch saved posts
- Interactive command-line interface
- No browser extension needed
- Direct control over which posts to share

## New Features

### 1. Reddit API Integration
- Automatically fetches your saved Reddit posts
- No need to browse Reddit manually
- Access up to 100 saved posts at once

### 2. Interactive Post Selection
For each saved post, you get these options:
- **y** = Post with original title
- **r** = Reword title (AI-assisted) - *coming soon*
- **n** = Enter new title (custom title)
- **s** = Skip this post
- **q** = Quit the script

### 3. Progress Tracking
- Shows how many posts processed
- Counts skipped and failed posts
- Summary statistics at the end

### 4. Simplified Setup
- No browser extension required
- Single script execution
- All configuration in one place

## How It Works

1. **Script starts** → Connects to Reddit API
2. **Fetches saved posts** → Gets your list of saved posts
3. **For each post**:
   - Shows the post title
   - Asks what you want to do
   - Downloads media if you choose to post
   - Opens X compose in Edge
   - Uploads media and creates thread
4. **Summary** → Shows statistics when done

## Configuration Required

You must set up Reddit API credentials in the script:

```python
REDDIT_CLIENT_ID = "your_client_id"
REDDIT_CLIENT_SECRET = "your_client_secret"
REDDIT_USERNAME = "your_username"
REDDIT_PASSWORD = "your_password"
```

See `API_SETUP_GUIDE.md` for detailed setup instructions.

## Requirements

New dependencies:
```bash
pip install selenium praw
```

Removed dependencies:
- flask (no longer needed)
- flask-cors (no longer needed)

## Files Changed

- ✏️ `XportReddit.py` - Complete rewrite
- ➕ `API_SETUP_GUIDE.md` - New setup guide
- ➕ `CHANGES.md` - This file

## Migration Guide

If you were using the old version:

1. Uninstall Flask (optional):
   ```bash
   pip uninstall flask flask-cors
   ```

2. Install PRAW:
   ```bash
   pip install praw
   ```

3. Set up Reddit API credentials (see `API_SETUP_GUIDE.md`)

4. Run the new script:
   ```bash
   python XportReddit.py
   ```

The browser extension is no longer needed and can be removed.

## Benefits

✅ More control over which posts to share
✅ No need to manually browse Reddit
✅ Batch process multiple saved posts
✅ Custom titles for each post
✅ Simpler architecture (no Flask server)
✅ Better error handling
✅ Progress tracking

## Known Limitations

- Requires Reddit API setup (one-time)
- Only works with saved posts
- AI reword feature not yet implemented
- Requires Edge browser
