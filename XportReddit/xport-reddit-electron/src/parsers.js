const fs = require('fs');
const { parse: parseCsvSync } = require('csv-parse/sync');

/** Extract post URLs from a Reddit HTML export file. */
function extractUrlsFromHtml(htmlFile) {
  const html = fs.readFileSync(htmlFile, 'utf-8');
  const seen = new Set();
  const urls = [];

  const pattern1 = /<a\s+href=["']+(https:\/\/www\.reddit\.com\/r\/[^/]+\/comments\/[^"']+)["']>\s*THREAD\s*<\/a>/gis;
  const pattern2 = /href=["']+(https:\/\/www\.reddit\.com\/r\/[^/]+\/comments\/[^"']+)["']/g;

  const matches1 = [...html.matchAll(pattern1)].map((m) => m[1]);
  const matches2 = [...html.matchAll(pattern2)].map((m) => m[1]);
  const allMatches = matches1.length ? matches1 : matches2;

  for (const match of allMatches) {
    const url = match.split('?')[0].split('#')[0].replace(/\/$/, '');
    if (!seen.has(url)) {
      seen.add(url);
      urls.push(url);
    }
  }
  return urls;
}

/**
 * Parse a saveddit4reddit-style CSV export.
 * Header (semicolon-delimited, double-quoted fields):
 *   author;comments;created;id;image;score;subreddit;text;title;url
 *
 * Returns { urls, titleCache: Map<url,title>, rowsCache: Map<url,row> }
 */
function parseCsvExport(csvFile) {
  const content = fs.readFileSync(csvFile, 'utf-8');
  const records = parseCsvSync(content, {
    delimiter: ';',
    quote: '"',
    columns: true,
    relax_quotes: true,
    relax_column_count: true,
    skip_empty_lines: true,
  });

  const urls = [];
  const titleCache = new Map();
  const rowsCache = new Map();
  const seen = new Set();

  for (const row of records) {
    let url = (row.url || '').trim().replace(/^"|"$/g, '');
    const title = (row.title || '').trim().replace(/^"|"$/g, '');

    if (!url || !url.includes('reddit.com/r/') || !url.includes('/comments/')) continue;

    url = url.split('?')[0].split('#')[0].replace(/\/$/, '');

    if (!seen.has(url)) {
      seen.add(url);
      urls.push(url);
      if (title) titleCache.set(url, title);
      rowsCache.set(url, row);
    }
  }

  return { urls, titleCache, rowsCache };
}

/** Extract the base-36 post ID from a Reddit post URL. */
function extractPostId(url) {
  const match = url.match(/\/comments\/([a-z0-9]+)\//);
  return match ? match[1] : null;
}

/** Return urls sorted from oldest to newest post. */
function sortPostsOldestFirst(urls) {
  const withIds = urls.map((url) => {
    const postId = extractPostId(url);
    let n = 0;
    if (postId) {
      const parsed = parseInt(postId, 36);
      n = Number.isNaN(parsed) ? 0 : parsed;
    }
    return [n, url];
  });
  withIds.sort((a, b) => a[0] - b[0]);
  return withIds.map(([, url]) => url);
}

/** Extract subreddit name from a Reddit post URL. */
function extractSubreddit(url) {
  const match = url.match(/\/r\/([^/]+)\//);
  return match ? match[1] : 'unknown';
}

module.exports = {
  extractUrlsFromHtml,
  parseCsvExport,
  extractPostId,
  sortPostsOldestFirst,
  extractSubreddit,
};
