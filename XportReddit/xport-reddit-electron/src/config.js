const path = require('path');

// Data directory = the XportReddit folder, so the app shares CSV/JSON state
// files with the existing Python tooling (parse_reddit_export.py, etc.)
const DATA_DIR = path.resolve(__dirname, '..', '..');

module.exports = {
  DATA_DIR,
  UPLOAD_TIMEOUT_MS: 90_000,
  POST_RETRY_ATTEMPTS: 5,
  SAVED_POSTS_FILE: 'reddit_saved_posts.json',
  POSTED_URLS_FILE: 'reddit_posted_urls.json',
  // Login persists via Electron's 'persist:xport-reddit' session partition, not a standalone profile dir.
  SESSION_PARTITION: 'persist:xport-reddit',
  CDP_PORT: 9222,
  CDP_URL: 'http://127.0.0.1:9222',
  // Electron appends an "Electron/x.y.z" token to its default UA, which trips Reddit's bot wall.
  DESKTOP_UA: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
  TMP_DIR: path.join(DATA_DIR, 'xport-reddit-electron', 'temp_downloads'),
};

