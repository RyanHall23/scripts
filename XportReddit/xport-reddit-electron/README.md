# XportReddit Electron

A desktop (Electron + Playwright) port of `XportReddit2.py` — turns saved Reddit
posts into X/Twitter image threads, with a GUI instead of terminal prompts.

It **reads** raw exports from the parent `XportReddit/` folder (shared with
the Python tooling), but **writes** everything it generates to its own
git-ignored `run-data/` folder instead, so a run can never modify or delete
files tracked in the repo:

- Read from `XportReddit/`: `saveddit4reddit.csv`, `reddit_export.html`
- Written to `xport-reddit-electron/run-data/` (git-ignored): dated
  `*_main.csv` / `*_secondary.csv` / `*_ignored.csv`, `reddit_saved_posts.json`
  (progress/resume file), `reddit_posted_urls.json` (archive)

You can also pick any of these files manually via **Choose File…**.

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

1. **Load Posts** — choose Run Primary / Run Secondary / Categorize New File
   (or Choose File…) from the load screen, which shows live file names and
   post counts. **Clear All Completed Batches** deletes the generated
   `run-data/` batch files once you're done with them.
2. **Categorization** (only for a new, un-categorized export) — check
   Primary or Secondary per subreddit; leaving both unchecked ignores it.
   Writes dated `_main.csv` / `_secondary.csv` / `_ignored.csv` files to
   `run-data/`.
3. **Browser login** — a mini browser panel is docked inside the app window
   itself (no separate window). It's Electron's own Chromium engine, driven
   by Playwright over the Chrome DevTools Protocol (`--remote-debugging-port`),
   and its login session persists via the `persist:xport-reddit` partition
   (stored in Electron's userData folder, entirely outside the repo).
4. **Account switch prompt** — before every run you're asked whether to
   switch X accounts (useful when Primary and Secondary post to different
   accounts). Choosing to switch logs out of X in the embedded panel so you
   can sign into the other account.
5. **Posting loop** — for each post: fetches title/images from Reddit (via the
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
