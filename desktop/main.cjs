const { app, BrowserWindow, protocol, ipcMain, dialog, session } = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');

protocol.registerSchemesAsPrivileged([{ scheme: 'mixroom', privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true } }]);
const files = new Map([
  ['/', ['index.html', 'text/html; charset=utf-8']],
  ['/styles.css', ['styles.css', 'text/css; charset=utf-8']],
  ['/src/app.js', ['src/app.js', 'text/javascript; charset=utf-8']],
  ['/src/audio.js', ['src/audio.js', 'text/javascript; charset=utf-8']],
]);
let window;
function openWindow() {
  window = new BrowserWindow({
    width: 1380, height: 980, minWidth: 780, minHeight: 640,
    title: 'MIXROOM · 人声伴奏混音器', backgroundColor: '#161717', autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event, url) => { if (url !== 'mixroom://app/') event.preventDefault(); });
  window.loadURL('mixroom://app/');
}
app.whenReady().then(() => {
  protocol.handle('mixroom', async request => {
    const url = new URL(request.url);
    const entry = url.hostname === 'app' && request.method === 'GET' ? files.get(url.pathname) : null;
    if (!entry) return new Response('Not found', { status: 404 });
    try {
      return new Response(await fs.readFile(path.join(app.getAppPath(), entry[0])), { headers: {
        'Content-Type': entry[1],
        'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'self'",
      } });
    } catch { return new Response('Unable to load application', { status: 500 }); }
  });
  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  ipcMain.handle('save-wav', async (event, bytes, name) => {
    if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame || event.senderFrame.url !== 'mixroom://app/') throw new Error('Invalid sender');
    if (!(bytes instanceof ArrayBuffer) || bytes.byteLength < 44 || bytes.byteLength > 600 * 1024 * 1024) throw new Error('Invalid audio data');
    const data = Buffer.from(bytes);
    if (data.toString('ascii', 0, 4) !== 'RIFF' || data.toString('ascii', 8, 12) !== 'WAVE') throw new Error('Invalid WAV format');
    const filename = typeof name === 'string' && /^MIXROOM-[\w-]+\.wav$/.test(name) ? name : 'MIXROOM.wav';
    const result = await dialog.showSaveDialog(window, { title: '保存混音', defaultPath: path.join(app.getPath('downloads'), filename), filters: [{ name: 'WAV 音频', extensions: ['wav'] }] });
    if (result.canceled || !result.filePath) return { canceled: true };
    await fs.writeFile(result.filePath, data);
    return { canceled: false };
  });
  openWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) openWindow(); });
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
