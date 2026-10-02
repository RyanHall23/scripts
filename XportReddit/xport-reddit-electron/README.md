# XportReddit Electron

A desktop (Electron + Playwright) port of `XportReddit2.py` — turns saved Reddit
posts into X/Twitter image threads, with a GUI instead of terminal prompts.

It reads/writes the **same files** as the Python tooling, from the parent
`XportReddit/` folder:

- `*_main.csv` / `*_secondary.csv` / `*_ignored.csv` (from `sort_saved_posts.py` /
  `parse_reddit_export.py`)
- `saveddit4reddit.csv`
- `reddit_export.html`
- `reddit_saved_posts.json` (progress/resume file)
- `reddit_posted_urls.json` (archive)

## Setup

```powershell
cd xport-reddit-electron
npm install
npx playwright install chromium
```

## Run

```powershell
npm start
```

## How it works

1. **Load Posts** — auto-detects the best input file (same priority order as
   the Python script) and loads it.
2. **Categorization** (only for generic/un-routed files) — assign each
   subreddit to `main` (post now), `secondary` (post later), or `ignored`.
   Writes dated `_main.csv` / `_secondary.csv` / `_ignored.csv` files.
3. **Browser login** — a mini browser panel is docked inside the app window
   itself (no separate window). It's Electron's own Chromium engine, driven
   by Playwright over the Chrome DevTools Protocol (`--remote-debugging-port`),
   and its login session persists via the `persist:xport-reddit` partition.
   First run requires a manual login in that embedded panel; it's reused
   afterwards.
4. **Posting loop** — for each post: fetches title/images from Reddit (via the
   logged-in browser session, to dodge 403s), downloads media, opens the X
   composer, types the title with human-like pacing, uploads images in
   batches of 4 as thread tweets, and clicks Post with retry/verification
   logic. You can choose to post one-by-one or switch to **Auto** mode.

## Known limitations vs. the Python version

- The embedded panel runs on Electron's bundled Chromium, not a standalone
  Microsoft Edge/Chrome process and not SeleniumBase's
  `undetected-chromedriver` — there is no built-in stealth/anti-detection
  layer, so bot-detection resistance is weaker than the original script.
- X/Reddit DOM selectors can change at any time; if posting stops working,
  the selectors in `src/xPoster.js` and `src/reddit.js` are the first place
  to check (same fragility existed in the Python script).
- The CDP debug port (`9222` by default, see `src/config.js`) is only bound
  to localhost, but any local process can attach to it while the app runs.
