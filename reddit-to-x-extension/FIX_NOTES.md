# Fix: Requests Not Reaching Server

## Problem
Browser extension requests weren't reaching the Flask server at `http://127.0.0.1:8765`.

## Root Cause
In **Manifest V3**, content scripts cannot directly make fetch requests to localhost/127.0.0.1 due to security restrictions and CORS policies. This is a known limitation in Chromium-based browsers (Chrome, Edge, etc.).

## Solution
Implemented **message passing** architecture:
1. Content script (`content.js`) sends message to background script
2. Background service worker (`background.js`) makes the fetch request to localhost
3. Background script sends response back to content script

This is the standard Manifest V3 pattern for accessing localhost from extensions.

## Changes Made

### 1. Added `background.js` 
- New service worker that handles localhost requests
- Listens for messages from content script
- Makes fetch calls to the Flask server

### 2. Updated `manifest.json` and `manifest-edge.json`
- Added `"background": { "service_worker": "background.js" }`

### 3. Updated `content.js`
- Replaced direct `fetch()` calls with `chrome.runtime.sendMessage()`
- Messages are handled by the background script

### 4. Firefox (`manifest-firefox.json`)
- Uses Manifest V2 which doesn't have this restriction
- No changes needed - direct fetch still works

## How to Apply the Fix

1. **Reload the extension** in your browser:
   - Go to `edge://extensions/` (or `chrome://extensions/`)
   - Find "Reddit to X Sharer"
   - Click the refresh/reload icon

2. **Restart the Flask server** (if not already running):
   ```bash
   python XportReddit.py
   ```

3. **Test the extension**:
   - Visit Reddit
   - Click the "📤 Share to X" button on any post
   - Check that it shows "✅ Queued!"

## Technical Details

**Why this happens:**
- Manifest V3 enforces stricter security policies
- Content scripts run in an isolated context
- Localhost access requires special permissions that only service workers have
- This prevents malicious websites from using extensions to scan local network

**Why this works:**
- Service workers (background scripts) have full extension privileges
- They can make requests to any URL listed in `host_permissions`
- Message passing is secure and sandboxed

## References
- [Chrome Extension Manifest V3 Migration](https://developer.chrome.com/docs/extensions/migrating/to-service-workers/)
- [Message Passing in Chrome Extensions](https://developer.chrome.com/docs/extensions/mv3/messaging/)
