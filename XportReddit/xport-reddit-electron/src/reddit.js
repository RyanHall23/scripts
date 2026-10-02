const fs = require('fs');
const path = require('path');
const { DESKTOP_UA } = require('./config');

/** Extract image/video URLs and post title from a Reddit JSON payload. */
function parseRedditJson(data) {
  const post = data[0].data.children[0].data;
  const postTitle = post.title || 'Reddit Post';
  const imageUrls = [];

  if (post.is_gallery) {
    const mediaMetadata = post.media_metadata || {};
    for (const item of (post.gallery_data?.items || [])) {
      const meta = mediaMetadata[item.media_id] || {};
      if (meta.status === 'valid') {
        const s = meta.s || {};
        const imgUrl = s.u || s.gif || s.mp4 || s.url;
        if (imgUrl) imageUrls.push(imgUrl.replace(/&amp;/g, '&'));
      }
    }
  } else if (post.post_hint === 'image' && post.url) {
    imageUrls.push(post.url);
  } else if (post.post_hint === 'hosted:video' && post.media) {
    const rv = post.media.reddit_video || {};
    if (rv.fallback_url) imageUrls.push(rv.fallback_url);
  } else if (post.post_hint === 'rich:video' && post.preview) {
    const rvp = post.preview.reddit_video_preview || {};
    if (rvp.fallback_url) imageUrls.push(rvp.fallback_url);
  } else if (post.preview && post.preview.images) {
    for (const img of post.preview.images) {
      imageUrls.push(img.source.url.replace(/&amp;/g, '&'));
    }
  } else if ((post.url || '').includes('imgur.com')) {
    let url = post.url;
    if (!/\.(jpg|png|gif|mp4)$/i.test(url)) url += '.jpg';
    imageUrls.push(url);
  }

  return { imageUrls, postTitle };
}

/**
 * Fetch Reddit post images/title, trying several strategies in order since
 * Reddit's bot wall ("You've been blocked…") can reject any single one of
 * them: the embedded browser page on www. then old.reddit.com, then a
 * direct HTTP request (also www. then old.) with browser-like headers.
 * Always returns to x.com/home afterwards.
 */
async function getRedditImagesViaBrowser(page, postUrl) {
  const base = postUrl.replace(/\/$/, '');
  const oldBase = base.replace('www.reddit.com', 'old.reddit.com');

  const attempts = [
    () => fetchJsonFromPage(page, `${base}/.json`),
    () => fetchJsonFromPage(page, `${oldBase}/.json`),
    () => fetchJsonViaHttp(`${base}/.json`),
    () => fetchJsonViaHttp(`${oldBase}/.json`),
  ];

  let lastErr;
  try {
    for (const attempt of attempts) {
      try {
        const data = await attempt();
        return parseRedditJson(data);
      } catch (e) {
        lastErr = e;
      }
    }
    throw lastErr || new Error('All Reddit fetch strategies failed');
  } finally {
    try {
      await page.goto('https://x.com/home', { waitUntil: 'domcontentloaded', timeout: 15000 });
    } catch {
      /* best-effort return to X */
    }
  }
}

function looksBlocked(raw) {
  const trimmed = raw.trim();
  return !trimmed.startsWith('{') && !trimmed.startsWith('[');
}

/** Navigate the embedded browser page to a Reddit .json URL and parse the response. */
async function fetchJsonFromPage(page, jsonUrl) {
  await page.goto(jsonUrl, { waitUntil: 'domcontentloaded', timeout: 15000 });
  await page.waitForTimeout(1000);

  let raw = await page.evaluate(() => document.querySelector('pre')?.innerText || document.body.innerText);
  raw = raw.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');

  if (looksBlocked(raw)) {
    throw new Error(`Reddit blocked the request: ${raw.slice(0, 80).replace(/\s+/g, ' ')}`);
  }
  return JSON.parse(raw);
}

/** Fetch a Reddit .json URL directly over HTTP (bypasses the Electron-hosted page entirely). */
async function fetchJsonViaHttp(jsonUrl) {
  const res = await fetch(jsonUrl, {
    headers: {
      'User-Agent': DESKTOP_UA,
      Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
      'Accept-Language': 'en-US,en;q=0.5',
    },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} fetching ${jsonUrl}`);
  const raw = await res.text();
  if (looksBlocked(raw)) {
    throw new Error(`Reddit blocked the HTTP request: ${raw.slice(0, 80).replace(/\s+/g, ' ')}`);
  }
  return JSON.parse(raw);
}

/** Download a list of image/video URLs into folder. Returns local file paths. */
async function downloadImages(imageUrls, folder) {
  const filePaths = [];
  let i = 0;
  for (const url of imageUrls) {
    i += 1;
    const ext = url.split('.').pop().split('?')[0];
    const filePath = path.join(folder, `image_${i}.${ext}`);
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Failed to download ${url}: ${res.status}`);
    const buffer = Buffer.from(await res.arrayBuffer());
    fs.writeFileSync(filePath, buffer);
    filePaths.push(filePath);
  }
  return filePaths;
}

/** Split image paths into groups of <= batchSize for X threading. */
function batchImagesForX(imagePaths, batchSize = 4) {
  const batches = [];
  for (let i = 0; i < imagePaths.length; i += batchSize) {
    batches.push(imagePaths.slice(i, i + batchSize));
  }
  return batches;
}

module.exports = { parseRedditJson, getRedditImagesViaBrowser, downloadImages, batchImagesForX };
