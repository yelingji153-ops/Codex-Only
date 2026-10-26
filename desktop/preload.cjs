const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('mixroomDesktop', {
  saveWav: (bytes, filename) => ipcRenderer.invoke('save-wav', bytes, filename),
});
