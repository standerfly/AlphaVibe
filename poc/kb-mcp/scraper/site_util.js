// investanchors scraper 的純函式輔助（可單獨用 node -e 測試）。

function normHost(h) {
  return String(h || '').toLowerCase().replace(/^www\./, '');
}

// investanchors.com 與 www.investanchors.com 視為同站（避免登入前就被誤判為被擋）。
function sameSite(a, b) {
  return normHost(a) === normHost(b);
}

module.exports = { normHost, sameSite };
