const $ = (id) => document.getElementById(id);

const state = {
  groups: [],
  assignments: {},
  autoMode: false,
  stopRequested: false,
  currentUrl: null,
  currentTitle: null,
};

function appendLog(message) {
  const panel = $('log-panel');
  const line = document.createElement('div');
  line.textContent = message;
  panel.appendChild(line);
  panel.scrollTop = panel.scrollHeight;
}
window.api.onLog(appendLog);

function show(id) { $(id).classList.remove('hidden'); }
function hide(id) { $(id).classList.add('hidden'); }

function showOnly(...ids) {
  ['load-section', 'error-section', 'categorize-section', 'account-switch-section', 'login-section', 'reddit-login-section', 'post-section', 'manual-section', 'summary-section']
    .forEach((id) => (ids.includes(id) ? show(id) : hide(id)));
}

// ---------------- Load posts ----------------

async function refreshFileStatus() {
  hide('run-choices');
  show('file-status-loading');
  $('load-status').textContent = '';

  const status = await window.api.getFileStatus();
  hide('file-status-loading');
  show('run-choices');

  const primaryBtn = $('run-primary-btn');
  const secondaryBtn = $('run-secondary-btn');
  const newFileBtn = $('categorize-new-btn');

  primaryBtn.disabled = !status.main;
  $('run-primary-detail').textContent = status.main ? `${status.main.fileName} — ${status.main.count} post(s)` : 'no Primary batch found';

  secondaryBtn.disabled = !status.secondary;
  $('run-secondary-detail').textContent = status.secondary ? `${status.secondary.fileName} — ${status.secondary.count} post(s)` : 'no Secondary batch found';

  newFileBtn.disabled = !status.unparsed;
  $('categorize-new-detail').textContent = status.unparsed ? `${status.unparsed.fileName} — ${status.unparsed.count} post(s)` : 'no new export found';

  if (status.hasAnyBatchFiles) {
    show('clear-all-btn');
  } else {
    hide('clear-all-btn');
  }
}
refreshFileStatus();

$('run-primary-btn').addEventListener('click', async () => {
  $('load-status').textContent = 'Loading Primary batch…';
  await handleLoadResult(await window.api.runPrimary());
});

$('run-secondary-btn').addEventListener('click', async () => {
  $('load-status').textContent = 'Loading Secondary batch…';
  await handleLoadResult(await window.api.runSecondary());
});

$('categorize-new-btn').addEventListener('click', async () => {
  $('load-status').textContent = 'Loading new export…';
  await handleLoadResult(await window.api.categorizeNewFile());
});

$('clear-all-btn').addEventListener('click', async () => {
  const { deleted } = await window.api.clearAll();
  appendLog(`🗑️ Cleared ${deleted.length} file(s): ${deleted.join(', ')}`);
  await refreshFileStatus();
});

$('pick-file-btn').addEventListener('click', async () => {
  const picked = await window.api.pickFile();
  if (picked.canceled) return;
  $('load-status').textContent = `Loading ${picked.filePath}…`;
  const result = await window.api.loadFromPath(picked.filePath);
  await handleLoadResult(result);
});

async function handleLoadResult(result) {
  if (!result.ok) {
    const messages = {
      'no-input-file': 'No input file found. Place a *_main.csv, saveddit4reddit.csv, reddit_export.html or reddit_saved_posts.json in the XportReddit folder.',
      empty: 'The input file contained no posts.',
      'ignored-file': `'${result.fileName}' is an ignored-batch file. Nothing to post.`,
    };
    $('error-message').textContent = messages[result.reason] || `Could not load posts (${result.reason}).`;
    showOnly('error-section');
    appendLog(`❌ ${messages[result.reason] || result.reason}`);
    return;
  }

  if (result.routing === 'sort') {
    appendLog(`📋 Loaded ${result.totalPosts} posts — categorization required.`);
    await renderCategorization();
    showOnly('categorize-section');
    return;
  }

  appendLog(`📋 Loaded ${result.totalPosts} posts, ready to post.`);
  $('load-status').textContent = `${result.totalPosts} post(s) ready.`;
  await beginBrowserFlow();
}

// ---------------- Categorization ----------------

async function renderCategorization() {
  state.groups = await window.api.getGroups();
  state.assignments = {};
  const list = $('group-list');
  list.innerHTML = '';

  state.groups.forEach((g) => {
    const row = document.createElement('div');
    row.className = 'group-row';
    row.dataset.subreddit = g.subreddit;

    const info = document.createElement('div');
    info.className = 'group-info';
    info.innerHTML = `<strong>r/${g.subreddit}</strong> (${g.count} post${g.count !== 1 ? 's' : ''})`
      + (g.samples.length ? `<div class="group-samples">${g.samples.map((s) => `• ${s.slice(0, 80)}`).join('<br/>')}</div>` : '');
    row.appendChild(info);

    const checkboxes = document.createElement('div');
    checkboxes.className = 'group-checkboxes';

    const makeCheckbox = (cat) => {
      const label = document.createElement('label');
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.dataset.cat = cat;
      input.addEventListener('change', () => {
        if (input.checked) {
          // Primary / Secondary are mutually exclusive — checking one unchecks the other.
          [...checkboxes.querySelectorAll('input')].forEach((other) => {
            if (other !== input) other.checked = false;
          });
          state.assignments[g.subreddit] = cat;
        } else if (state.assignments[g.subreddit] === cat) {
          delete state.assignments[g.subreddit];
        }
      });
      label.appendChild(input);
      return label;
    };

    checkboxes.appendChild(makeCheckbox('main'));
    checkboxes.appendChild(makeCheckbox('secondary'));
    row.appendChild(checkboxes);
    list.appendChild(row);
  });
}

document.querySelectorAll('[data-bulk]').forEach((btn) => {
  btn.addEventListener('click', () => {
    const cat = btn.dataset.bulk;
    state.groups.forEach((g) => {
      if (cat === 'ignored') delete state.assignments[g.subreddit];
      else state.assignments[g.subreddit] = cat;
    });
    document.querySelectorAll('.group-row').forEach((row) => {
      row.querySelectorAll('input[type="checkbox"]').forEach((input) => {
        input.checked = cat !== 'ignored' && input.dataset.cat === cat;
      });
    });
    appendLog(`→ '${cat}' applied to all ${state.groups.length} subreddit(s).`);
  });
});

$('submit-categorization').addEventListener('click', async () => {
  // Unassigned subreddits (both checkboxes left unchecked) are ignored.
  const result = await window.api.categorize(state.assignments);
  appendLog(`CATEGORIZATION SUMMARY — primary:${result.counts.main} secondary:${result.counts.secondary} ignored:${result.counts.ignored}`);
  Object.entries(result.files).forEach(([cat, name]) => appendLog(`💾 ${name}`));

  if (!result.ok) {
    $('error-message').textContent = "No subreddits assigned to Primary. Nothing to post in this run.";
    showOnly('error-section');
    return;
  }

  appendLog(`▶ Continuing with ${result.totalPosts} Primary post(s)…`);
  await beginBrowserFlow();
});

// ---------------- Browser / login ----------------

async function beginBrowserFlow() {
  showOnly('login-section');
  $('login-status').textContent = '🌐 Starting embedded browser…';
  appendLog('🌐 Starting embedded browser…');

  const { loggedIn } = await window.api.startBrowser();
  await promptAccountSwitch(loggedIn);
}

// Different batches (Primary / Secondary) may post to different X accounts, so ask before every run.
async function promptAccountSwitch(currentlyLoggedIn) {
  showOnly('account-switch-section');
  $('account-switch-status').textContent = currentlyLoggedIn
    ? '✅ Currently logged into X in the embedded panel.'
    : '⚠️ Not currently logged into X in the embedded panel.';
}

$('switch-account-yes').addEventListener('click', async () => {
  $('switch-account-yes').disabled = true;
  appendLog('🔄 Logging out of X — sign into the account you want for this run.');
  await window.api.switchAccount();
  $('switch-account-yes').disabled = false;
  await proceedToLoginCheck();
});

$('switch-account-no').addEventListener('click', async () => {
  await proceedToLoginCheck();
});

async function proceedToLoginCheck() {
  showOnly('login-section');
  $('login-status').textContent = '🔍 Checking X login…';
  const { loggedIn } = await window.api.confirmLogin();

  if (loggedIn) {
    appendLog('✅ X session active.');
    await beginRedditLoginFlow();
    return;
  }

  $('login-status').textContent = '⚠️ Please log in using the embedded browser panel on the right, then click continue.';
  show('confirm-login-btn');
}

$('confirm-login-btn').addEventListener('click', async () => {
  $('confirm-login-btn').disabled = true;
  $('login-status').textContent = '🔍 Checking…';
  const { loggedIn } = await window.api.confirmLogin();
  $('confirm-login-btn').disabled = false;

  if (loggedIn) {
    appendLog('✅ X login verified.');
    await beginRedditLoginFlow();
  } else {
    $('login-status').textContent = '⚠️ Still not logged in — finish logging in, then click continue again.';
  }
});

// Reddit's .json endpoint blocks logged-out requests ("You've been blocked…"),
// so a Reddit login (separate from X) is required before fetching posts.
async function beginRedditLoginFlow() {
  showOnly('reddit-login-section');
  $('reddit-login-status').textContent = '🔍 Checking Reddit login…';
  appendLog('🔍 Checking Reddit login…');

  const { loggedIn } = await window.api.checkRedditLogin();
  if (loggedIn) {
    appendLog('✅ Reddit session active.');
    await advanceToNextPost();
    return;
  }

  $('reddit-login-status').textContent = '⚠️ Please log into Reddit using the embedded browser panel on the right, then click continue.';
  show('confirm-reddit-login-btn');
}

$('confirm-reddit-login-btn').addEventListener('click', async () => {
  $('confirm-reddit-login-btn').disabled = true;
  $('reddit-login-status').textContent = '🔍 Checking…';
  const { loggedIn } = await window.api.confirmRedditLogin();
  $('confirm-reddit-login-btn').disabled = false;

  if (loggedIn) {
    appendLog('✅ Reddit login verified.');
    await advanceToNextPost();
  } else {
    $('reddit-login-status').textContent = '⚠️ Still not logged into Reddit — finish logging in, then click continue again.';
  }
});

// ---------------- Posting loop ----------------

async function advanceToNextPost() {
  if (state.stopRequested) return showSummary();

  const info = await window.api.peekNext();
  if (info.done) return showSummary();

  state.currentUrl = info.url;
  state.currentTitle = info.title;

  showOnly('post-section');
  hide('title-edit-row');
  hide('post-busy');
  $('post-progress').textContent = `POST ${info.index}/${info.total}`;
  $('post-title').textContent = info.title;
  $('post-url').textContent = info.url;

  if (state.autoMode) {
    await runPostAction('post', info.title);
  }
}

async function runPostAction(action, titleOverride) {
  show('post-busy');
  const result = await window.api.postAction(action === 'post' ? 'post' : action, titleOverride ?? state.currentTitle);
  hide('post-busy');

  if (result.quit || action === 'quit') {
    state.stopRequested = true;
    return showSummary();
  }

  if (result.status === 'manual-required') {
    showOnly('manual-section');
    return;
  }

  await advanceToNextPost();
}

$('action-post').addEventListener('click', () => runPostAction('post'));
$('action-skip').addEventListener('click', () => runPostAction('skip'));
$('action-quit').addEventListener('click', () => runPostAction('quit'));

$('action-auto').addEventListener('click', async () => {
  state.autoMode = true;
  await window.api.setAutoMode(true);
  appendLog('🤖 AUTO MODE ENABLED — posts will be processed automatically.');
  await runPostAction('post');
});

$('action-reword').addEventListener('click', () => {
  show('title-edit-row');
  $('title-edit-input').value = state.currentTitle;
  $('title-edit-input').focus();
});
$('action-newtitle').addEventListener('click', () => {
  show('title-edit-row');
  $('title-edit-input').value = '';
  $('title-edit-input').focus();
});
$('title-edit-cancel').addEventListener('click', () => hide('title-edit-row'));
$('title-edit-confirm').addEventListener('click', () => {
  const val = $('title-edit-input').value.trim();
  if (!val) return;
  hide('title-edit-row');
  runPostAction('post', val);
});

$('manual-posted').addEventListener('click', async () => {
  await window.api.resolveManual('manual-posted');
  await advanceToNextPost();
});
$('manual-skip').addEventListener('click', async () => {
  await window.api.resolveManual('manual-skipped');
  await advanceToNextPost();
});
$('manual-quit').addEventListener('click', () => {
  state.stopRequested = true;
  showSummary();
});

// ---------------- Summary ----------------

async function showSummary() {
  const counts = await window.api.getCounts();
  showOnly('summary-section');
  $('summary-text').textContent = `✅ Processed: ${counts.processed}   ⏭️ Skipped: ${counts.skipped}   ❌ Failed: ${counts.failed}`;
  appendLog('📊 SUMMARY — ' + $('summary-text').textContent);
}
