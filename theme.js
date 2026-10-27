'use strict';
// Runs before the page draws so a saved light or dark choice never flashes the other theme.
(() => {
  const THEMES = ['auto', 'light', 'dark'];
  const read = () => { try { return localStorage.getItem('to.theme'); } catch (_) { return null; } };
  const apply = theme => {
    if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
  };
  let theme = THEMES.includes(read()) ? read() : 'auto';
  apply(theme);
  document.addEventListener('DOMContentLoaded', () => {
    const button = document.getElementById('themeButton');
    if (!button) return;
    const label = () => { button.textContent = `Theme: ${theme[0].toUpperCase()}${theme.slice(1)}`; };
    label();
    button.addEventListener('click', () => {
      theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
      try { localStorage.setItem('to.theme', theme); } catch (_) { /* Private windows: the choice lasts this visit. */ }
      apply(theme);
      label();
    });
  });
})();
