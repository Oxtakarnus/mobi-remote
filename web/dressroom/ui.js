// 화면 도우미 — 요소 찾기·HTML 이스케이프·파이썬 호출·단추 결과 표시. 드레스룸 화면 모듈(main·view·colors·list·cards)이 같이 쓴다.
// 다른 프로그램이 가져가는 조립 모듈(dresser.js 쪽)은 이 파일을 쓰지 않는다.

export const $ = (s) => document.querySelector(s);
export const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ── 파이썬 호출 (gui_app/dressroom.py DressApi — QWebChannel 'backend', web/bridge.js 와 같은 방식) ──
let channel = null;
let seq = 0;
const pending = new Map();

function backend() {
  if (!channel) {
    channel = new Promise((resolve) => {
      new QWebChannel(qt.webChannelTransport, (ch) => {
        const be = ch.objects.backend;
        be.reply.connect((id, json) => {
          const p = pending.get(id);
          if (!p) return;
          pending.delete(id);
          let v = null;
          try { v = JSON.parse(json); } catch (_) { /* 빈 응답 */ }
          if (v && v.__error) p.reject(new Error(v.__error)); else p.resolve(v);
        });
        resolve(be);
      });
    });
  }
  return channel;
}

/** 파이썬 메서드를 부른다 → 그 답 (Promise). */
export function rpc(method, ...args) {
  return backend().then((be) => new Promise((resolve, reject) => {
    const id = ++seq;
    pending.set(id, { resolve, reject });
    be.call(id, method, JSON.stringify(args));
  }));
}

/** 단추 글자를 잠깐 바꿔 결과를 보인다 (tip 을 주면 그동안 풍선도) — 1.5초 뒤 원래 글자·풍선으로. */
export function flash(b, text, tip = '') {
  const text0 = b.dataset.text ?? (b.dataset.text = b.textContent);
  const tip0 = b.dataset.tip ?? (b.dataset.tip = b.title);
  b.textContent = text;
  b.title = tip || tip0;
  clearTimeout(b._t);
  b._t = setTimeout(() => { b.textContent = text0; b.title = tip0; }, 1500);
}
