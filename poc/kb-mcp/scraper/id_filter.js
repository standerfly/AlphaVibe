/**
 * 回補「延後」判定的瀏覽器端實作（010 T043）。**不含任何時間換算常數**：
 * 三個整數門檻全由 Python（article_id_time.defer_thresholds）算好傳入，Python 是唯一權威。
 * 規則只有一句：ID 是 14 位純數字字串、數值在 [valid_id_min, valid_id_max]、且 < defer_below_id → 延後（不開啟）；
 * 其餘一律照常處理。與 Python 的逐筆一致性由 tests/fixtures/id_time_corpus.json 守門。
 */
function shouldDefer(id, th) {
  if (!th) return false;
  const s = String(id);
  if (!/^[0-9]{14}$/.test(s)) return false;
  const n = Number(s);
  return n >= th.valid_id_min && n <= th.valid_id_max && n < th.defer_below_id;
}

function thresholdsFrom(cfg) {
  if (cfg == null || cfg.defer_below_id == null) return null;
  const th = {
    defer_below_id: Number(cfg.defer_below_id),
    valid_id_min: Number(cfg.valid_id_min),
    valid_id_max: Number(cfg.valid_id_max),
  };
  return Object.values(th).every(Number.isFinite) ? th : null;
}

module.exports = { shouldDefer, thresholdsFrom };
