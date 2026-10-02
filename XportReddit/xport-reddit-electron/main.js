const { app, BrowserWindow, BrowserView, ipcMain, dialog, session: electronSession } = require('electron');
const path = require('path');
const Session = require('./src/session');
const { DATA_DIR, CDP_PORT, SESSION_PARTITION, DESKTOP_UA } = require('./src/config');

// Must be set before 'ready' — lets Playwright attach to Electron's own
// Chromium engine over CDP so the embedded browser panel can be automated.
app.commandLine.appendSwitch('remote-debugging-port', String(CDP_PORT));

const SIDEBAR_WIDTH = 560;

let mainWindow;
let browserView;
let session;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  browserView = new BrowserView({
    webPreferences: { partition: SESSION_PARTITION },
  });
  // Drop Electron's default "Electron/x.y.z" UA token — Reddit's bot wall blocks on it.
  electronSession.fromPartition(SESSION_PARTITION).setUserAgent(DESKTOP_UA);
  browserView.webContents.setUserAgent(DESKTOP_UA);
  mainWindow.setBrowserView(browserView);
  layoutBrowserView();
  browserView.webContents.loadURL('about:blank');

  mainWindow.on('resize', layoutBrowserView);
}

function layoutBrowserView() {
  if (!mainWindow || !browserView) return;
  const { width, height } = mainWindow.getContentBounds();
  browserView.setBounds({
    x: SIDEBAR_WIDTH,
    y: 0,
    width: Math.max(width - SIDEBAR_WIDTH, 0),
    height,
  });
}

function log(message) {
  if (mainWindow) mainWindow.webContents.send('session:log', message);
}

app.whenReady().then(() => {
  createWindow();
  session = new Session(log, browserView);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', async () => {
  if (session) await session.close();
  if (process.platform !== 'darwin') app.quit();
});

ipcMain.handle('session:init', () => session.init());
ipcMain.handle('session:file-status', () => session.getFileStatus());
ipcMain.handle('session:init-main', () => session.initMain());
ipcMain.handle('session:init-secondary', () => session.initSecondary());
ipcMain.handle('session:init-new-file', () => session.initNewFile());
ipcMain.handle('session:clear-all', () => session.clearAll());
ipcMain.handle('session:pick-file', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Select a Reddit export / batch file',
    defaultPath: DATA_DIR,
    properties: ['openFile'],
    filters: [
      { name: 'All supported', extensions: ['csv', 'html', 'htm', 'json'] },
      { name: 'CSV batch files', extensions: ['csv'] },
      { name: 'Raw JSON batch files', extensions: ['json'] },
      { name: 'Reddit HTML export', extensions: ['html', 'htm'] },
    ],
  });
  if (result.canceled || !result.filePaths.length) return { canceled: true };
  return { canceled: false, filePath: result.filePaths[0] };
});
ipcMain.handle('session:init-from-path', (_e, filePath) => session.initFromPath(filePath));
ipcMain.handle('session:groups', () => session.getSubredditGroups());
ipcMain.handle('session:categorize', (_e, assignments) => session.categorize(assignments));
ipcMain.handle('session:start-browser', () => session.startBrowser());
ipcMain.handle('session:confirm-login', () => session.confirmLogin());
ipcMain.handle('session:switch-account', () => session.switchAccount());
ipcMain.handle('session:check-reddit-login', () => session.checkRedditLogin());
ipcMain.handle('session:confirm-reddit-login', () => session.confirmRedditLogin());
ipcMain.handle('session:peek-next', () => session.peekNextPost());
ipcMain.handle('session:post-action', (_e, { action, postTitle }) => session.handlePostAction(action, postTitle));
ipcMain.handle('session:resolve-manual', (_e, status) => session.resolveManual(status));
ipcMain.handle('session:set-auto-mode', (_e, value) => session.setAutoMode(value));
ipcMain.handle('session:counts', () => session.counts);
ipcMain.handle('session:close', async () => {
  await session.close();
  return true;
});
