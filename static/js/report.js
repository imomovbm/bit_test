// Brauzerdagi kutilmagan xatolar serverga (POST /api/client-errors): faqat xabar, skript fayli va qator raqami —
// shaxsiy ma'lumotsiz; sahifaga ko'pi bilan 5 ta (server ham IP bo'yicha cheklaydi). Jurnal va /metrics da ko'rinadi.
const MAX_REPORTS = 5;

export function reportErrors(page) {
  let left = MAX_REPORTS;
  const send = (message, source, line) => {
    if (left <= 0) return;
    left -= 1;
    try {
      fetch('/api/client-errors', {
        method: 'POST',
        keepalive: true,
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          m: String(message || '').slice(0, 300),
          s: String(source || '').split(/[?#]/)[0].slice(-160),
          l: Number.isInteger(line) ? line : 0,
          p: page,
        }),
      }).catch(() => {});
    } catch {
      /* hisobot yuborilmasa ham sahifa ishlayveradi */
    }
  };
  window.addEventListener('error', (e) => send(e.message, e.filename, e.lineno));
  window.addEventListener('unhandledrejection', (e) => {
    const r = e.reason;
    send(r && r.message ? `${r.name || 'Error'}: ${r.message}` : String(r), '', 0);
  });
}
