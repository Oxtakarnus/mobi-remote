'use strict';
// 첫 페인트 전에 테마를 붙인다 (리모콘과 같은 테마 — 창을 만들 때 파이썬이 __MM_INIT__ 로 심어 준다).
(function () {
  var t = (window.__MM_INIT__ && window.__MM_INIT__.theme) === 'light' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', t);
})();
