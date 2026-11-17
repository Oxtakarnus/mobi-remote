// 외형 탭 색 상자 — 하위 탭(체형·헤어·눈·얼굴꾸밈·몸꾸밈)에 맞는 색 칸. 칸이 여럿이면 칸 단추로 하나씩 본다 (게임 꾸미기 화면처럼).
// 칸 하나 = { id, label, pal: 게임 색 표 이름(face.json colors — 없으면 직접 고르기만), two: 투톤 칸(두 색을 같이 고른다),
//          one: 한 색 줄만(두 번째 머리색), get(): 지금 색 }.

import { esc } from './ui.js';

const SWATCH_MAX = 400;   // 색 표가 이보다 길면 앞쪽만

export class ColorBox {
  /**
   * el: 상자 자리. onSet(id, hex, hex2, done): 색을 바꿀 때 — hex null 은 기본색, hex2 는 투톤 칸의 두 번째 색,
   * done 은 고르기를 마쳤을 때(저장).
   */
  constructor(el, onSet) {
    this.el = el;
    this.onSet = onSet;
    this.table = null;
    this.sets = [];
    this.sig = '';
    this.cur = null;   // 보고 있는 칸 id
    el.addEventListener('click', (e) => {
      const tab = e.target.closest('[data-cb-tab]');
      if (tab) { this.cur = tab.dataset.cbTab; this.render(); return; }
      const sw = e.target.closest('[data-c]');
      if (sw) {   // 투톤 칸은 한 색 칸을 골라도 두 번째 색을 같은 색으로 (게임처럼)
        const s = this.sets.find((x) => x.id === this.cur);
        this.onSet(this.cur, sw.dataset.c, s && s.two ? sw.dataset.c2 || sw.dataset.c : null, true);
        return;
      }
      if (e.target.closest('[data-cb-reset]')) this.onSet(this.cur, null, null, true);
    });
    el.addEventListener('input', (e) => {
      if (e.target.matches('[data-cb-pick]')) this.onSet(this.cur, e.target.value.toUpperCase(), null, false);
    });
    el.addEventListener('change', (e) => {
      if (e.target.matches('[data-cb-pick]')) this.onSet(this.cur, e.target.value.toUpperCase(), null, true);
    });
  }

  /** 게임 색 표 (FaceTable — 목록을 받은 뒤). */
  setTable(t) {
    this.table = t;
    this.sig = '';
  }

  /** 칸들을 보인다 (빈 배열이면 숨김). 칸 구성이 같으면 다시 그리지 않고 값만 맞춘다 — 색을 끄는 중에 불려도 고르기 창이 안 닫힌다. */
  show(sets) {
    this.sets = sets;
    const sig = sets.map((s) => s.id + ':' + (s.pal || '') + ':' + s.label).join('|');
    if (sig === this.sig) { this.refresh(); return; }
    this.sig = sig;
    this.render();
  }

  render() {
    const sets = this.sets;
    this.el.classList.toggle('hidden', !sets.length);
    if (!sets.length) { this.el.innerHTML = ''; return; }
    if (!sets.some((s) => s.id === this.cur)) this.cur = sets[0].id;
    const s = sets.find((x) => x.id === this.cur);
    const head = sets.length > 1
      ? `<div class="cb-tabs">${sets.map((x) => `<button type="button" data-cb-tab="${esc(x.id)}" class="${x.id === s.id ? 'on' : ''}">${esc(x.label)}</button>`).join('')}</div>`
      : `<b class="cb-title">${esc(s.label)}</b>`;
    this.el.innerHTML = `<div class="cb-head">${head}
        <input type="color" data-cb-pick title="직접 고르기">
        <span class="cb-hex mute small"></span>
        <button type="button" class="btn btn-sm" data-cb-reset title="기본색">기본</button>
      </div>${this.swatches(s)}`;
    for (const el of this.el.querySelectorAll('[data-bg]')) el.style.background = el.dataset.bg;   // CSP 가 style 속성을 막는다
    this.refresh();
  }

  /** 게임 색 표 칸들. 투톤 칸은 두 색 칸(대각선)도 보이고, one 이면 한 색 줄만 (피부 c2 는 손바닥이라 안 쓴다). */
  swatches(s) {
    const t = this.table;
    let cs = t && s.pal ? t.colors(s.pal) : [];
    if (!cs.length) return '';
    if (s.one) cs = cs.filter((c) => !c.c2 || c.c2 === c.c);
    const seen = new Set();
    const out = [];
    for (const c of cs) {
      const two = s.two && c.c2 && c.c2 !== c.c;
      const key = c.c + (two ? c.c2 : '');
      if (seen.has(key)) continue;
      seen.add(key);
      const bg = two ? `linear-gradient(135deg, ${c.c} 50%, ${c.c2} 50%)` : c.c;
      out.push(`<span class="sw" data-c="${esc(c.c)}"${two ? ` data-c2="${esc(c.c2)}"` : ''} data-bg="${esc(bg)}" title="${esc(c.name + ' ' + c.c + (two ? ' · ' + c.c2 : ''))}"></span>`);
      if (out.length >= SWATCH_MAX) break;
    }
    return `<div class="pal-row cb-sw">${out.join('')}</div>`;
  }

  /** 지금 색을 고르기 칸·글자·고른 색 표시에 맞춘다. */
  refresh() {
    const s = this.sets.find((x) => x.id === this.cur);
    if (!s) return;
    const v = (s.get() || '#FFFFFF').toUpperCase();
    const pick = this.el.querySelector('[data-cb-pick]');
    if (pick && pick.value.toUpperCase() !== v) pick.value = v.toLowerCase();
    const hex = this.el.querySelector('.cb-hex');
    if (hex) hex.textContent = v;
    for (const el of this.el.querySelectorAll('.sw')) el.classList.toggle('on', el.dataset.c.toUpperCase() === v);
  }
}
