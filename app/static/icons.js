/* Ícones de traço fino, inline, sem dependência externa.
   O catálogo entrega uma chave semântica (gpu, ram, ...) e a interface troca
   pela forma correspondente. O fallback é um chip genérico — nunca um emoji. */
(() => {
  const shapes = {
    chip: `
      <rect x="7" y="7" width="10" height="10" rx="1.5"/>
      <path d="M9 3v4M15 3v4M9 17v4M15 17v4M3 9h4M3 15h4M17 9h4M17 15h4"/>`,
    gpu: `
      <rect x="3" y="6" width="18" height="12" rx="2"/>
      <circle cx="8.5" cy="12" r="2.2"/>
      <circle cx="15.5" cy="12" r="2.2"/>
      <path d="M7 18v2M17 18v2M7 4v2M17 4v2"/>`,
    ram: `
      <rect x="3" y="7" width="18" height="10" rx="1.5"/>
      <path d="M7 10v4M10.5 10v4M14 10v4M17.5 10v4M5 17v2M9 17v2M13 17v2M17 17v2M19 17v2"/>`,
    storage: `
      <rect x="4" y="4" width="16" height="16" rx="2"/>
      <path d="M7 8h10M7 12h10M7 16h6"/>
      <circle cx="17" cy="16.5" r="1"/>`,
    cpu: `
      <rect x="6" y="6" width="12" height="12" rx="1.5"/>
      <rect x="9" y="9" width="6" height="6" rx="0.5"/>
      <path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/>`,
    motherboard: `
      <rect x="4" y="4" width="16" height="16" rx="1.5"/>
      <rect x="7" y="7" width="4" height="4" rx="0.5"/>
      <path d="M14 7h3M14 10h3M7 14h10M7 17h6"/>
      <circle cx="17" cy="17" r="1"/>`,
    psu: `
      <path d="M13 3 6 14h5l-1 7 8-11h-5l1-7Z"/>`,
    smartphone: `
      <rect x="7" y="3" width="10" height="18" rx="2"/>
      <path d="M10 6h4M11 18h2"/>`,
    notebook: `
      <rect x="5" y="5" width="14" height="10" rx="1"/>
      <path d="M3 18h18l-2-3H5l-2 3Z"/>`,
    monitor: `
      <rect x="3" y="5" width="18" height="12" rx="1.5"/>
      <path d="M9 21h6M12 17v4"/>`,
    console: `
      <path d="M7 8h10a4 4 0 0 1 4 4v3a2 2 0 0 1-3.6 1.2L16 15H8l-1.4 1.2A2 2 0 0 1 3 15v-3a4 4 0 0 1 4-4Z"/>
      <path d="M9 11v3M7.5 12.5h3M15 12h.01M17 14h.01"/>`,
  };

  function svg(name, size = 18) {
    const key = Object.prototype.hasOwnProperty.call(shapes, name) ? name : 'chip';
    const px = Number.isFinite(size) ? Math.max(12, Math.min(40, size)) : 18;
    return `<svg class="icon icon-${key}" width="${px}" height="${px}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${shapes[key]}</svg>`;
  }

  window.Icons = { svg, names: Object.keys(shapes) };
})();
