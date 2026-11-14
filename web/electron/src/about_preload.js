// Narrow bridge for the bundled About window.

"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld(
  "omnigentAbout",
  Object.freeze({
    getInfo: () => ipcRenderer.invoke("omnigent:about-get-info"),
    getDesktopUpdateStatus: () => ipcRenderer.invoke("omnigent:about-get-desktop-update-status"),
    checkDesktopUpdates: () => ipcRenderer.invoke("omnigent:about-check-desktop"),
    downloadDesktopUpdate: () => ipcRenderer.invoke("omnigent:about-download-desktop-update"),
    installDesktopUpdate: () => ipcRenderer.invoke("omnigent:about-install-desktop-update"),
    // CORAL(S87): opens a shipped licence file (LICENSE, NOTICE) for the attribution buttons.
    openLegalFile: (name) => ipcRenderer.invoke("omnigent:about-open-legal-file", name),
    onDesktopUpdateStatus: (callback) => {
      const listener = (_event, status) => callback(status);
      ipcRenderer.on("omnigent:update-status", listener);
      return () => ipcRenderer.removeListener("omnigent:update-status", listener);
    },
    close: () => ipcRenderer.send("omnigent:about-close"),
  }),
);
