const fs = require('fs');
const path = require('path');
const { stringify: csvStringifySync } = require('csv-stringify/sync');
const { SAVED_POSTS_FILE, POSTED_URLS_FILE } = require('./config');
const { extractUrlsFromHtml, parseCsvExport, sortPostsOldestFirst, extractSubreddit } = require('./parsers');

/**
 * Search for a supported input file.
 * Priority: resumable progress JSON (outputDir) > dated *_main/_secondary
 *           batch files (outputDir, .csv or .json, newest date first, csv
 *           preferred on a date tie) > saveddit4reddit.csv (dataDir) >
 *           reddit_export.html (dataDir).
 * Generated files live in outputDir (git-ignored); raw exports live in
 * dataDir (shared with the Python tooling).
 */
function findInputFile(dataDir, outputDir) {
  const progressPath = path.join(outputDir, SAVED_POSTS_FILE);
  if (fs.existsSync(progressPath)) {
    try {
      const data = JSON.parse(fs.readFileSync(progressPath, 'utf-8'));
      if (data.urls && data.urls.length) {
        return { filePath: progressPath, fileType: 'json', resumed: true };
      }
    } catch {
      /* ignore malformed progress file */
    }
  }

  const outputEntries = fs.existsSync(outputDir) ? fs.readdirSync(outputDir) : [];
  for (const suffix of ['_main', '_secondary']) {
    const batchMatch = findNewestBatchFile(outputEntries, suffix);
    if (batchMatch) return { filePath: path.join(outputDir, batchMatch.name), fileType: batchMatch.fileType };
  }

  const candidates = [
    ['saveddit4reddit.csv', 'csv'],
    ['reddit_export.html', 'html'],
  ];
  for (const [filename, ftype] of candidates) {
    const p = path.join(dataDir, filename);
    if (fs.existsSync(p)) return { filePath: p, fileType: ftype };
  }

  return null;
}

/** Find the newest `*_main.{csv,json}` / `*_secondary.{csv,json}` file, preferring csv on a date tie. */
function findNewestBatchFile(entries, suffix) {
  const pattern = new RegExp(`${suffix}\\.(csv|json)$`, 'i');
  const matches = entries
    .filter((f) => pattern.test(f))
    .map((f) => ({ name: f, fileType: f.toLowerCase().endsWith('.json') ? 'json' : 'csv' }))
    .sort((a, b) => {
      if (a.name === b.name) return 0;
      const cmp = a.name < b.name ? 1 : -1; // newest (lexicographically largest) first
      if (cmp !== 0) return cmp;
      return a.fileType === 'csv' ? -1 : 1;
    });
  return matches[0] || null;
}

/** Count URLs in a file without fully loading title/row caches — used to label buttons in the UI. */
function countUrlsInFile(filePath, fileType) {
  try {
    if (fileType === 'csv') return parseCsvExport(filePath).urls.length;
    if (fileType === 'html') return extractUrlsFromHtml(filePath).length;
    let content = fs.readFileSync(filePath, 'utf-8');
    content = content.replace(/,(\s*[}\]])/g, '$1');
    const data = JSON.parse(content);
    return (data.urls || []).length;
  } catch {
    return 0;
  }
}

/**
 * Report the newest Primary (*_main), Secondary (*_secondary) batch file in
 * outputDir, and an un-categorized raw export file in dataDir, so the UI
 * can offer explicit "Run Primary" / "Run Secondary" / "Categorize New
 * File" actions.
 */
function getFileStatus(dataDir, outputDir) {
  const outputEntries = fs.existsSync(outputDir) ? fs.readdirSync(outputDir) : [];

  const toInfo = (suffix) => {
    const match = findNewestBatchFile(outputEntries, suffix);
    if (!match) return null;
    const filePath = path.join(outputDir, match.name);
    return { filePath, fileName: match.name, fileType: match.fileType, count: countUrlsInFile(filePath, match.fileType) };
  };

  const main = toInfo('_main');
  const secondary = toInfo('_secondary');

  let unparsed = null;
  for (const [filename, ftype] of [['saveddit4reddit.csv', 'csv'], ['reddit_export.html', 'html']]) {
    const p = path.join(dataDir, filename);
    if (fs.existsSync(p)) {
      unparsed = { filePath: p, fileName: filename, fileType: ftype, count: countUrlsInFile(p, ftype) };
      break;
    }
  }

  const hasAnyBatchFiles = Boolean(main || secondary) || outputEntries.some((f) => /_ignored\.(csv|json)$/i.test(f));

  return { main, secondary, unparsed, hasAnyBatchFiles };
}

/** Delete all dated *_main/_secondary/_ignored batch files plus the progress snapshot from outputDir, so a fresh export can be re-categorized. */
function clearBatches(outputDir) {
  const entries = fs.existsSync(outputDir) ? fs.readdirSync(outputDir) : [];
  const pattern = /_(main|secondary|ignored)\.(csv|json)$/i;
  const deleted = [];

  for (const f of entries) {
    if (pattern.test(f)) {
      fs.unlinkSync(path.join(outputDir, f));
      deleted.push(f);
    }
  }

  const progressPath = path.join(outputDir, SAVED_POSTS_FILE);
  if (fs.existsSync(progressPath)) {
    fs.unlinkSync(progressPath);
    deleted.push(SAVED_POSTS_FILE);
  }

  return deleted;
}

/** Write current URL list to the progress JSON snapshot file in outputDir. */
function writeJsonSnapshot(urls, outputDir) {
  fs.mkdirSync(outputDir, { recursive: true });
  const out = path.join(outputDir, SAVED_POSTS_FILE);
  const data = {
    indexed_at: new Date().toISOString(),
    sort_order: 'oldest_to_newest',
    count: urls.length,
    urls,
  };
  fs.writeFileSync(out, JSON.stringify(data, null, 2), 'utf-8');
  return out;
}

/** Overwrite the JSON progress file in outputDir with the current URL list. */
function saveSavedPosts(urls, outputDir) {
  fs.mkdirSync(outputDir, { recursive: true });
  const out = path.join(outputDir, SAVED_POSTS_FILE);
  fs.writeFileSync(out, JSON.stringify({ urls }, null, 2), 'utf-8');
}

/** Append a processed URL to the posted-URLs archive in outputDir. */
function addToPostedUrls(url, status, outputDir) {
  fs.mkdirSync(outputDir, { recursive: true });
  const out = path.join(outputDir, POSTED_URLS_FILE);
  let posted = { urls: [] };
  if (fs.existsSync(out)) {
    try {
      posted = JSON.parse(fs.readFileSync(out, 'utf-8'));
    } catch {
      posted = { urls: [] };
    }
  }
  posted.urls.push({ url, status, posted_at: new Date().toISOString() });
  fs.writeFileSync(out, JSON.stringify(posted, null, 2), 'utf-8');
}

/**
 * Inspect the source filename to determine routing:
 *   'direct'  -> *_main / *_secondary / progress file -> skip categorization
 *   'ignored' -> *_ignored file -> nothing to post
 *   'sort'    -> generic file -> run interactive categorization
 */
function checkFilenameRouting(filePath) {
  if (!filePath) return 'sort';
  const name = path.basename(filePath, path.extname(filePath)).toLowerCase();
  if (name.includes('ignored')) return 'ignored';
  if (name.includes('main') || name.includes('secondary') || name === 'reddit_saved_posts') return 'direct';
  return 'sort';
}

/** Detect and load saved posts from the best available input file. */
function loadSavedPosts(dataDir, outputDir) {
  const found = findInputFile(dataDir, outputDir);
  if (!found) {
    return { urls: [], titleCache: new Map(), rowsCache: new Map(), filePath: null, fileType: null, error: 'not-found' };
  }
  return loadFile(found.filePath, found.fileType, outputDir);
}

/** Load posts from a user-picked file path (csv / html / json, incl. raw *_main.json / *_secondary.json). */
function loadFromPath(filePath, outputDir) {
  if (!fs.existsSync(filePath)) {
    return { urls: [], titleCache: new Map(), rowsCache: new Map(), filePath, fileType: null, error: 'not-found' };
  }
  const ext = path.extname(filePath).toLowerCase();
  const fileType = ext === '.csv' ? 'csv' : ext === '.html' || ext === '.htm' ? 'html' : ext === '.json' ? 'json' : null;
  if (!fileType) {
    return { urls: [], titleCache: new Map(), rowsCache: new Map(), filePath, fileType: null, error: `unsupported-extension:${ext}` };
  }
  return loadFile(filePath, fileType, outputDir);
}

/** Parse the given file (known type) into {urls, titleCache, rowsCache, filePath, fileType}. Writes the progress snapshot to outputDir. */
function loadFile(filePath, fileType, outputDir) {
  if (fileType === 'csv') {
    const { urls: rawUrls, titleCache, rowsCache } = parseCsvExport(filePath);
    const urls = sortPostsOldestFirst(rawUrls);
    writeJsonSnapshot(urls, outputDir);
    return { urls, titleCache, rowsCache, filePath, fileType };
  }

  if (fileType === 'html') {
    const urls = sortPostsOldestFirst(extractUrlsFromHtml(filePath));
    writeJsonSnapshot(urls, outputDir);
    return { urls, titleCache: new Map(), rowsCache: new Map(), filePath, fileType };
  }

  // JSON — covers reddit_saved_posts.json as well as raw *_main.json / *_secondary.json exports
  try {
    let content = fs.readFileSync(filePath, 'utf-8');
    content = content.replace(/,(\s*[}\]])/g, '$1'); // tolerate trailing commas
    const data = JSON.parse(content);
    return { urls: data.urls || [], titleCache: new Map(), rowsCache: new Map(), filePath, fileType };
  } catch (e) {
    return { urls: [], titleCache: new Map(), rowsCache: new Map(), filePath, fileType, error: String(e) };
  }
}

/** Write main / secondary / ignored URL lists to dated CSV files in outDir (the git-ignored output folder). */
function writeCategorizedCsvs(categorized, titleCache, rowsCache, outDir) {
  fs.mkdirSync(outDir, { recursive: true });
  const dateStr = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const outputPaths = {};

  for (const category of Object.keys(categorized)) {
    const urls = categorized[category];
    if (!urls.length) continue;

    const rows = [['subreddit', 'title', 'url', 'image']];
    for (const url of urls) {
      let subreddit = extractSubreddit(url);
      let title = titleCache.get(url) || '';
      let image = '';
      const row = rowsCache.get(url);
      if (row) {
        subreddit = (row.subreddit || subreddit).trim().replace(/^"|"$/g, '');
        title = (row.title || title).trim().replace(/^"|"$/g, '');
        image = (row.image || '').trim().replace(/^"|"$/g, '');
      }
      rows.push([subreddit, title, url, image]);
    }

    const outFile = path.join(outDir, `${dateStr}_${category}.csv`);
    const csvText = csvStringifySync(rows, { delimiter: ';', quoted: true });
    fs.writeFileSync(outFile, csvText, 'utf-8');
    outputPaths[category] = outFile;
  }

  return outputPaths;
}

module.exports = {
  findInputFile,
  getFileStatus,
  clearBatches,
  writeJsonSnapshot,
  saveSavedPosts,
  addToPostedUrls,
  checkFilenameRouting,
  loadSavedPosts,
  loadFromPath,
  writeCategorizedCsvs,
};
