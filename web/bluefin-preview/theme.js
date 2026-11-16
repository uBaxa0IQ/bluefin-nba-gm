'use strict';

function applyTheme(theme) {
  const selected = ['light', 'dark', 'system'].includes(theme) ? theme : 'system';
  document.documentElement.dataset.theme = selected;
  return selected;
}

let savedTheme;
try {
  savedTheme = JSON.parse(localStorage.getItem('bluefin-ui') ?? '{}')?.theme;
} catch {}
applyTheme(savedTheme);
