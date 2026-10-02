const { chromium } = require('playwright');
const { CDP_URL } = require('./config');
const { humanDelay } = require('./humanize');

/**
 * Attaches Playwright to the Electron app's own Chromium engine over CDP and
 * drives the embedded BrowserView panel (view.webContents) instead of
 * launching a separate browser window.
 * Returns { context, page, loggedIn } — if loggedIn is false, the caller
 * must prompt the user to log in manually in the embedded panel, then call
 * confirmLogin(page).
 */
async function startBrowser(view) {
  await view.webContents.loadURL('https://x.com');

  const browser = await chromium.connectOverCDP(CDP_URL);
  const page = await findViewPage(browser, view);
  if (!page) throw new Error('Could not attach to the embedded browser view over CDP');

  const loggedIn = await isLoggedIn(page);
  return { context: browser, page, loggedIn };
}

/** Locate the Playwright page matching the Electron BrowserView's own target (not the app's own UI window). */
async function findViewPage(browser, view, retries = 10) {
  const targetUrl = view.webContents.getURL();
  for (let attempt = 0; attempt < retries; attempt += 1) {
    for (const ctx of browser.contexts()) {
      for (const page of ctx.pages()) {
        const url = page.url();
        if (url && !url.startsWith('file://') && (url === targetUrl || url.includes('x.com') || url.includes('twitter.com'))) {
          return page;
        }
      }
    }
    await humanDelay(0.3, 0.1);
  }
  return null;
}

async function isLoggedIn(page) {
  try {
    await page.waitForSelector('[data-testid="AppTabBar_Home_Link"]', { timeout: 7000 });
    return true;
  } catch {
    return false;
  }
}

/** Re-check login state after the user has completed a manual login. */
async function confirmLogin(page) {
  await page.goto('https://x.com/home', { waitUntil: 'domcontentloaded' });
  await humanDelay(1.5, 0.3);
  return isLoggedIn(page);
}

/**
 * Reddit's .json endpoint returns a bot-wall page ("You've been blocked…")
 * for logged-out requests, so a Reddit login is required too. Navigates to
 * reddit.com and reports whether the user is logged in.
 */
async function checkRedditLogin(page) {
  await page.goto('https://www.reddit.com', { waitUntil: 'domcontentloaded', timeout: 20000 });
  await humanDelay(1.0, 0.3);
  return isRedditLoggedIn(page);
}

async function isRedditLoggedIn(page) {
  try {
    const loginLinks = await page.locator("text=/^Log ?[Ii]n$/").count();
    return loginLinks === 0;
  } catch {
    return false;
  }
}

/** Re-check Reddit login state after the user has completed a manual login. */
async function confirmRedditLogin(page) {
  await page.goto('https://www.reddit.com', { waitUntil: 'domcontentloaded', timeout: 20000 });
  await humanDelay(1.0, 0.3);
  return isRedditLoggedIn(page);
}

module.exports = {
  startBrowser, isLoggedIn, confirmLogin, checkRedditLogin, confirmRedditLogin,
};
