(function(){
  var btns = document.querySelectorAll('button[role="switch"]');
  var t = null;
  for (var i = 0; i < btns.length; i++) {
    var l = btns[i].getAttribute('aria-label') || '';
    if (/追蹤|track price/i.test(l)) { t = btns[i]; break; }
  }
  if (!t) {
    alert('找不到追蹤按鈕。\n\nGoogle Flights 的價格追蹤不支援「多城市」行程，四段票頁面沒有這個按鈕。請改用來回票頁面（台北↔目的地）。');
    return;
  }
  if (t.getAttribute('aria-checked') === 'true') {
    alert('這條航線已經在追蹤中了：\n\n' + t.getAttribute('aria-label'));
    return;
  }
  t.click();
  setTimeout(function(){
    var ok = t.getAttribute('aria-checked') === 'true';
    alert((ok ? '✓ 已開啟追蹤' : '點了但狀態沒變，可能需要先登入 Google 帳號') + '：\n\n' + t.getAttribute('aria-label'));
  }, 600);
})();
