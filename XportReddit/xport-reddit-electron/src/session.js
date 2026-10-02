const fs = require('fs');
const path = require('path');
const {
  DATA_DIR, TMP_DIR, POST_RETRY_ATTEMPTS,
} = require('./config');
const store = require('./store');
const { extractSubreddit, sortPostsOldestFirst } = require('./parsers');
const { getRedditImagesViaBrowser, downloadImages, batchImagesForX } = require('./reddit');
const { startBrowser: launchBrowser, confirmLogin, checkRedditLogin, confirmRedditLogin } = require('./browser');
const {
  openXCompose, uploadImages, clickPostButton, clickAddButton,
  checkIfPostPublished, checkForXError, checkForDuplicatePost,
} = require('./xPoster');
const { humanDelay, humanType } = require('./humanize');

class Session {
  constructor(logFn, browserView) {
    this.log = logFn || (() => {});
    this.browserView = browserView;
    this.dataDir = DATA_DIR;
    this.titleCache = new Map();
    this.rowsCache = new Map();
    this.pendingUrls = [];
    this.queue = [];
    this.totalPosts = 0;
    this.routing = null;
    this.sourcePath = null;
    this.context = null;
    this.page = null;
    this.autoMode = false;
    this.counts = { processed: 0, skipped: 0, failed: 0 };
  }

  /** Load posts from the best available input file and determine routing. */
  init() {
    return this._applyLoadResult(store.loadSavedPosts(this.dataDir));
  }

  /** Load posts from a user-picked file path (csv / html / json, incl. raw *_main.json / *_secondary.json). */
  initFromPath(filePath) {
    return this._applyLoadResult(store.loadFromPath(filePath, this.dataDir));
  }

  /** Report the newest Primary/Secondary batch files and any un-categorized raw export, for the load screen. */
  getFileStatus() {
    return store.getFileStatus(this.dataDir);
  }

  /** Load and run the newest Primary (*_main) batch directly, skipping categorization. */
  initMain() {
    const status = store.getFileStatus(this.dataDir);
    if (!status.main) return { ok: false, reason: 'no-input-file' };
    return this._applyLoadResult(store.loadFromPath(status.main.filePath, this.dataDir));
  }

  /** Load and run the newest Secondary (*_secondary) batch directly, skipping categorization. */
  initSecondary() {
    const status = store.getFileStatus(this.dataDir);
    if (!status.secondary) return { ok: false, reason: 'no-input-file' };
    return this._applyLoadResult(store.loadFromPath(status.secondary.filePath, this.dataDir));
  }

  /** Load the raw/un-categorized export file and force the categorization step. */
  initNewFile() {
    const status = store.getFileStatus(this.dataDir);
    if (!status.unparsed) return { ok: false, reason: 'no-input-file' };
    return this._applyLoadResult(store.loadFromPath(status.unparsed.filePath, this.dataDir));
  }

  /** Delete completed Primary/Secondary/Ignored batch files so a fresh export can be re-categorized. */
  clearAll() {
    const deleted = store.clearBatches(this.dataDir);
    this.pendingUrls = [];
    this.queue = [];
    this.totalPosts = 0;
    this.routing = null;
    this.sourcePath = null;
    return { deleted };
  }

  _applyLoadResult(result) {
    if (result.error === 'not-found') {
      return { ok: false, reason: 'no-input-file' };
    }
    if (result.error) {
      return { ok: false, reason: result.error };
    }

    this.titleCache = result.titleCache;
    this.rowsCache = result.rowsCache;
    this.sourcePath = result.filePath;
    this.pendingUrls = result.urls;

    if (!this.pendingUrls.length) {
      return { ok: false, reason: 'empty' };
    }

    this.routing = store.checkFilenameRouting(this.sourcePath);

    if (this.routing === 'ignored') {
      return { ok: false, reason: 'ignored-file', fileName: path.basename(this.sourcePath) };
    }

    if (this.routing === 'direct') {
      this.queue = [...this.pendingUrls];
      this.totalPosts = this.queue.length;
      return { ok: true, routing: 'direct', totalPosts: this.totalPosts };
    }

    // routing === 'sort' -> renderer must call getSubredditGroups() + categorize()
    return { ok: true, routing: 'sort', totalPosts: this.pendingUrls.length };
  }

  /** Build subreddit groups for the categorization UI. */
  getSubredditGroups() {
    const subredditMap = new Map(); // subreddit -> urls[]
    for (const url of this.pendingUrls) {
      const row = this.rowsCache.get(url);
      const sub = row?.subreddit?.trim().replace(/^"|"$/g, '') || extractSubreddit(url);
      if (!subredditMap.has(sub)) subredditMap.set(sub, []);
      subredditMap.get(sub).push(url);
    }

    const groups = [];
    for (const [sub, urls] of subredditMap) {
      const samples = [];
      for (const url of urls) {
        if (samples.length >= 3) break;
        const row = this.rowsCache.get(url);
        const title = row?.title?.trim().replace(/^"|"$/g, '') || this.titleCache.get(url) || '';
        if (title) samples.push(title);
      }
      groups.push({ subreddit: sub, count: urls.length, samples });
    }
    return groups;
  }

  /**
   * Apply user-chosen categorization.
   * assignments: { [subreddit]: 'main' | 'secondary' | 'ignored' }
   */
  categorize(assignments) {
    const subredditMap = new Map();
    for (const url of this.pendingUrls) {
      const row = this.rowsCache.get(url);
      const sub = row?.subreddit?.trim().replace(/^"|"$/g, '') || extractSubreddit(url);
      if (!subredditMap.has(sub)) subredditMap.set(sub, []);
      subredditMap.get(sub).push(url);
    }

    const categorized = { main: [], secondary: [], ignored: [] };
    for (const [sub, urls] of subredditMap) {
      // No checkbox checked for a subreddit means ignored, not secondary.
      const cat = assignments[sub] || 'ignored';
      categorized[cat].push(...urls);
    }
    for (const cat of Object.keys(categorized)) {
      categorized[cat] = sortPostsOldestFirst(categorized[cat]);
    }

    const outDir = this.sourcePath ? path.dirname(this.sourcePath) : this.dataDir;
    const writtenFiles = store.writeCategorizedCsvs(categorized, this.titleCache, this.rowsCache, outDir);

    this.queue = categorized.main;
    this.totalPosts = this.queue.length;

    return {
      ok: this.queue.length > 0,
      totalPosts: this.totalPosts,
      counts: {
        main: categorized.main.length,
        secondary: categorized.secondary.length,
        ignored: categorized.ignored.length,
      },
      files: Object.fromEntries(Object.entries(writtenFiles).map(([k, v]) => [k, path.basename(v)])),
    };
  }

  /** Attach to the embedded browser panel and check X login state. */
  async startBrowser() {
    const { context, page, loggedIn } = await launchBrowser(this.browserView);
    this.context = context;
    this.page = page;
    return { loggedIn };
  }

  /** Re-check login after the user completes manual login in the embedded panel. */
  async confirmLogin() {
    const loggedIn = await confirmLogin(this.page);
    return { loggedIn };
  }

  /** Reddit's .json endpoint blocks logged-out requests, so check that separately from X. */
  async checkRedditLogin() {
    const loggedIn = await checkRedditLogin(this.page);
    return { loggedIn };
  }

  /** Re-check Reddit login after the user completes manual login in the embedded panel. */
  async confirmRedditLogin() {
    const loggedIn = await confirmRedditLogin(this.page);
    if (loggedIn) {
      try {
        await this.page.goto('https://x.com/home', { waitUntil: 'domcontentloaded' });
      } catch {
        /* best-effort return to X */
      }
    }
    return { loggedIn };
  }

  hasNext() {
    return this.queue.length > 0;
  }

  /** Fetch (or read cached) title for the next post in queue, without consuming it. */
  async peekNextPost() {
    if (!this.queue.length) return { done: true };
    const url = this.queue[0];
    const idx = this.totalPosts - this.queue.length + 1;

    let title = this.titleCache.get(url);
    if (!title) {
      try {
        const { postTitle } = await getRedditImagesViaBrowser(this.page, url);
        title = postTitle;
      } catch (e) {
        this.log(`⚠️  Could not fetch title via browser: ${e.message}`);
      }
    }
    if (!title) {
      const slug = url.replace(/\/$/, '').split('/').pop();
      title = slug.replace(/_/g, ' ').trim() || url;
    }

    return { done: false, url, title, index: idx, total: this.totalPosts };
  }

  /** Remove the current head of the queue, persist, and archive its status. */
  _finishCurrent(url, status) {
    store.addToPostedUrls(url, status, this.dataDir);
    this.queue.shift();
    store.saveSavedPosts(this.queue, this.dataDir);
  }

  /**
   * Handle the user's choice for the current post.
   * action: 'post' | 'skip' | 'quit'
   * postTitle: the (possibly custom) title to use when action === 'post'
   */
  async handlePostAction(action, postTitle) {
    if (!this.queue.length) return { done: true };
    const url = this.queue[0];

    if (action === 'quit') {
      return { quit: true };
    }

    if (action === 'skip') {
      this.counts.skipped += 1;
      this._finishCurrent(url, 'skipped');
      this.log('⏭️  Skipped');
      return { status: 'skipped', remaining: this.queue.length };
    }

    return this._postThread(url, postTitle);
  }

  async _postThread(url, postTitle) {
    const log = this.log;
    fs.mkdirSync(TMP_DIR, { recursive: true });

    try {
      log('📥 Fetching media from Reddit…');
      let imageUrls = [];
      try {
        const result = await getRedditImagesViaBrowser(this.page, url);
        imageUrls = result.imageUrls;
        if (!imageUrls.length) throw new Error('No images returned');
        log(`✅ Got ${imageUrls.length} image(s) via browser`);
      } catch (e) {
        log(`⚠️  Browser fetch failed: ${e.message}`);
        const row = this.rowsCache.get(url);
        const cachedImg = row?.image?.trim().replace(/^"|"$/g, '');
        if (cachedImg) {
          log('ℹ️  Using cached preview image from CSV');
          imageUrls = [cachedImg];
        } else {
          log('❌ No fallback image — skipping post');
          this.counts.failed += 1;
          this._finishCurrent(url, 'failed-no-image');
          return { status: 'failed', reason: 'no-image', remaining: this.queue.length };
        }
      }

      const filePaths = await downloadImages(imageUrls, TMP_DIR);
      const batches = batchImagesForX(filePaths);
      log(`📊 Found ${imageUrls.length} image(s) -> ${batches.length} tweet(s) in thread`);

      log('🧵 Setting up X compose…');
      if (!this.page.url().includes('x.com') && !this.page.url().includes('twitter.com')) {
        await this.page.goto('https://x.com/home', { waitUntil: 'domcontentloaded' });
      }
      await openXCompose(this.page, log);

      try {
        await this.page.waitForSelector('[data-testid="tweetTextarea_0"]', { timeout: 15000 });
        await this.page.waitForSelector('input[data-testid="fileInput"]', { timeout: 5000 });
        log('✅ Compose ready!');
        await humanDelay(2.0, 0.3);
      } catch (e) {
        log(`❌ Compose not ready: ${e.message}`);
        this._cleanTmp();
        this.counts.failed += 1;
        this._finishCurrent(url, 'failed-compose');
        return { status: 'failed', reason: 'compose-not-ready', remaining: this.queue.length };
      }

      for (let i = 0; i < batches.length; i += 1) {
        const batch = batches[i];
        log(`Tweet ${i + 1}/${batches.length} (${batch.length} file(s))`);

        if (i === 0) {
          try {
            const textArea = await this.page.waitForSelector('[data-testid="tweetTextarea_0"]', { timeout: 10000 });
            await textArea.click();
            await humanDelay(0.4, 0.5);
            const filteredTitle = [...postTitle].filter((c) => c.codePointAt(0) <= 0xffff).join('');
            log('⌨️  Typing title…');
            await humanType(this.page, filteredTitle, { minDelay: 0.03, maxDelay: 0.12, withTypos: this.autoMode });
            log(`✅ Added title: ${filteredTitle.slice(0, 50)}${filteredTitle.length > 50 ? '…' : ''}`);
            await humanDelay(1.5, 0.4);
          } catch (e) {
            log(`⚠️  Could not add title: ${e.message}`);
          }
        }

        const uploaded = await uploadImages(this.page, batch, i, log);
        if (!uploaded) {
          log('⚠️  Upload failed. Skipping this batch…');
          continue;
        }

        if (i < batches.length - 1) {
          const added = await clickAddButton(this.page, log);
          if (!added) {
            log('⚠️  Failed to add tweet to thread.');
            break;
          }
        }
      }

      log('📤 Posting entire thread…');
      await humanDelay(2.0, 0.4);

      let posted = false;
      let duplicate = false;
      for (let attempt = 0; attempt < POST_RETRY_ATTEMPTS; attempt += 1) {
        if (attempt > 0) {
          if (await checkIfPostPublished(this.page, postTitle, 3000)) {
            log('✅ Post found on page — previous attempt succeeded!');
            posted = true;
            break;
          }
          const baseWait = 3 * (attempt + 1);
          log(`🔄 Retry ${attempt}/${POST_RETRY_ATTEMPTS - 1} (waiting ~${baseWait}s)…`);
          await humanDelay(baseWait, 0.2);
        }

        if (await clickPostButton(this.page, log)) {
          await humanDelay(3.0, 0.3);

          if (await checkForDuplicatePost(this.page)) {
            log("⚠️  X says 'Already said that' — duplicate detected");
            await this.page.keyboard.press('Escape');
            await humanDelay(1.0, 0.3);
            duplicate = true;
            break;
          }

          if (await checkIfPostPublished(this.page, postTitle, 5000)) {
            log('✅ Post verified on page!');
            posted = true;
            break;
          }

          if (await checkForXError(this.page)) {
            log('⚠️  X returned an error after clicking Post');
            continue;
          }
          log('⚠️  Post not verified yet, will retry…');
        }
      }

      this._cleanTmp();

      if (duplicate) {
        this.counts.failed += 1;
        this._finishCurrent(url, 'skipped-duplicate');
        return { status: 'duplicate', remaining: this.queue.length };
      }

      if (!posted) {
        log(`⚠️  Failed to auto-post after ${POST_RETRY_ATTEMPTS} attempts.`);
        return { status: 'manual-required', remaining: this.queue.length };
      }

      log('🎉 Thread complete!');
      this.counts.processed += 1;
      this._finishCurrent(url, 'success');
      return { status: 'success', remaining: this.queue.length };
    } catch (e) {
      log(`❌ Error processing post: ${e.message}`);
      this._cleanTmp();
      this.counts.failed += 1;
      return { status: 'error', message: e.message, remaining: this.queue.length };
    }
  }

  /** Called after a 'manual-required' result if the user posted it themselves. */
  resolveManual(status) {
    const url = this.queue[0];
    if (status === 'manual-posted') {
      this._finishCurrent(url, 'manual');
    } else if (status === 'manual-skipped') {
      this.counts.failed += 1;
      this._finishCurrent(url, 'skipped');
    }
    return { remaining: this.queue.length };
  }

  _cleanTmp() {
    try {
      for (const fname of fs.readdirSync(TMP_DIR)) {
        const fpath = path.join(TMP_DIR, fname);
        if (fs.statSync(fpath).isFile()) fs.unlinkSync(fpath);
      }
    } catch {
      /* best-effort cleanup */
    }
  }

  setAutoMode(value) {
    this.autoMode = value;
  }

  async close() {
    try {
      if (fs.existsSync(TMP_DIR)) fs.rmSync(TMP_DIR, { recursive: true, force: true });
      if (this.context) await this.context.close();
    } catch {
      /* ignore cleanup errors on shutdown */
    }
  }
}

module.exports = Session;
