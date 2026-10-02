const { humanDelay, humanType } = require('./humanize');
const { UPLOAD_TIMEOUT_MS, POST_RETRY_ATTEMPTS } = require('./config');

const VIDEO_EXTS = ['.mp4', '.mov', '.avi', '.webm', '.mkv', '.flv', '.gif'];

/** Open the X compose modal. */
async function openXCompose(page, log) {
  log('📝 Opening compose modal…');
  try {
    if (!page.url().includes('x.com') && !page.url().includes('twitter.com')) {
      await page.goto('https://x.com/home', { waitUntil: 'domcontentloaded' });
      await humanDelay(3.0, 0.3);
    }

    const existing = await page.$('[data-testid="tweetTextarea_0"]');
    if (existing) {
      log('ℹ️  Compose already open, closing it…');
      await page.keyboard.press('Escape');
      await humanDelay(1.0, 0.5);
    }

    if (!page.url().includes('x.com/home')) {
      await page.goto('https://x.com/home', { waitUntil: 'domcontentloaded' });
      await humanDelay(3.0, 0.3);
    }

    try {
      const composeButton = await page.waitForSelector('a[data-testid="SideNav_NewTweet_Button"]', { timeout: 5000 });
      await composeButton.evaluate((el) => el.click());
      log('✅ Compose modal opened');
      await humanDelay(2.0, 0.4);
      return true;
    } catch {
      await page.keyboard.press('n');
      await humanDelay(2.0, 0.4);
      log('✅ Compose opened via keyboard');
      return true;
    }
  } catch (e) {
    log(`⚠️  Failed to open compose: ${e.message}`);
    return false;
  }
}

/** Upload image/video file paths to the active tweet's file input. */
async function uploadImages(page, imagePaths, tweetIndex, log) {
  try {
    log(`📤 Uploading ${imagePaths.length} file(s) to tweet ${tweetIndex + 1}…`);
    const hasVideo = imagePaths.some((p) => VIDEO_EXTS.some((ext) => p.toLowerCase().endsWith(ext)));

    const fileInput = await page.waitForSelector('input[data-testid="fileInput"]', { timeout: 10000 });
    await fileInput.setInputFiles(imagePaths);
    log('✅ Files sent to upload!');

    if (hasVideo) {
      log('ℹ️  Video detected, waiting for upload to complete…');
      await humanDelay(2.0, 0.3);
      await waitForUploadCompletion(page, 60000, log);
    } else {
      await humanDelay(2.0, 0.3);
      log('✅ Images ready!');
    }
    return true;
  } catch (e) {
    log(`⚠️  Upload failed: ${e.message}`);
    return false;
  }
}

/** Block until all media uploads finish or timeout is reached. */
async function waitForUploadCompletion(page, timeoutMs = UPLOAD_TIMEOUT_MS, log = () => {}) {
  log('⏳ Waiting for uploads to complete…');
  const start = Date.now();
  let lastButtonState = null;
  let lastStatusCheck = start;

  while (Date.now() - start < timeoutMs) {
    try {
      const buttonInfo = await page.evaluate(() => {
        const buttons = document.querySelectorAll(
          '[data-testid="tweetButton"], [data-testid="tweetButtonInline"]'
        );
        for (const btn of buttons) {
          const rect = btn.getBoundingClientRect();
          if (rect.width > 0 && rect.height > 0) {
            const disabled = btn.disabled || btn.getAttribute('aria-disabled') === 'true';
            return { found: true, enabled: !disabled };
          }
        }
        return { found: false, enabled: false };
      });

      if (buttonInfo.found) {
        const state = buttonInfo.enabled ? 'enabled' : 'disabled';
        if (lastButtonState !== state && Date.now() - start > 2000) {
          log(`🔘 Post button: ${state}`);
        }
        lastButtonState = state;
      }

      let hasUploadStatus = false;
      for (const keyword of ['Uploading', 'Processing', 'Encoding', 'Compressing', 'Preparing']) {
        const found = await page.locator(`text=${keyword}`).count();
        if (found > 0) {
          hasUploadStatus = true;
          if (Date.now() - lastStatusCheck > 3000) {
            log(`⏳ Media still ${keyword.toLowerCase()}…`);
            lastStatusCheck = Date.now();
          }
          break;
        }
      }

      if (buttonInfo.enabled && !hasUploadStatus) {
        log('✅ All uploads completed!');
        return true;
      }

      await humanDelay(1.0, 0.3);
    } catch (e) {
      log(`⚠️  Could not check upload status: ${e.message}`);
      await humanDelay(2.0, 0.3);
      return true;
    }
  }

  log(`⚠️  Upload check timed out after ${timeoutMs / 1000}s — continuing anyway`);
  return false;
}

/** Click the Post / Post all button. */
async function clickPostButton(page, log) {
  try {
    log('📤 Clicking \'Post\' button…');
    let postButton = null;
    for (const selector of ['[data-testid="tweetButton"]', '[data-testid="tweetButtonInline"]']) {
      const el = await page.$(selector);
      if (el && (await el.isVisible())) {
        postButton = el;
        break;
      }
    }
    if (!postButton) throw new Error('Could not find any Post button');

    await postButton.evaluate((el) => el.click());
    log('✅ Post button clicked!');
    await humanDelay(2.0, 0.4);
    return true;
  } catch (e) {
    log(`⚠️  Failed to click Post button: ${e.message}`);
    return false;
  }
}

/** Click the + button to add another tweet to the thread. */
async function clickAddButton(page, log) {
  try {
    log('➕ Adding new tweet to thread…');
    const addButton = await page.waitForSelector('[data-testid="addButton"]', { timeout: 10000 });
    await addButton.evaluate((el) => el.click());
    log('✅ New tweet added to thread!');
    await humanDelay(3.0, 0.4);
    return true;
  } catch (e) {
    log(`⚠️  Failed to click add button: ${e.message}`);
    return false;
  }
}

/** Return true if the compose modal closed and the post appears published. */
async function checkIfPostPublished(page, postTitle, timeoutMs = 5000) {
  const start = Date.now();
  const initialUrl = page.url();
  const end = Date.now() + timeoutMs;
  let modalClosed = false;

  while (Date.now() < end) {
    try {
      const modal = await page.$('[aria-labelledby="modal-header"]');
      modalClosed = !modal || !(await modal.isVisible());
    } catch {
      modalClosed = true;
    }

    const urlChanged = page.url() !== initialUrl && page.url().includes('status');

    if (modalClosed) {
      const filteredTitle = [...postTitle].filter((c) => c.codePointAt(0) <= 0xffff).join('');
      const body = await page.content();
      if (body.includes(filteredTitle.slice(0, 50)) || urlChanged) {
        if (Date.now() - start > 2000) return true;
      }
    }

    await humanDelay(0.5, 0.4);
  }

  return modalClosed;
}

async function textExists(page, msg) {
  const count = await page.locator(`text=${msg}`).count();
  return count > 0;
}

/** Return true if X is showing a known error message. */
async function checkForXError(page) {
  const messages = [
    'Something went wrong', 'Try again', 'Error',
    "didn't go through", 'You are over the daily limit', 'rate limit',
  ];
  for (const msg of messages) {
    if (await textExists(page, msg)) return true;
  }
  return false;
}

/** Return true if X is showing an 'Already said that' duplicate error. */
async function checkForDuplicatePost(page) {
  for (const msg of ['Already said that', 'You already said that', 'already posted']) {
    if (await textExists(page, msg)) return true;
  }
  return false;
}

module.exports = {
  openXCompose,
  uploadImages,
  waitForUploadCompletion,
  clickPostButton,
  clickAddButton,
  checkIfPostPublished,
  checkForXError,
  checkForDuplicatePost,
  POST_RETRY_ATTEMPTS,
};
