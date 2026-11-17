// 오른쪽 옷 카드 — 입은 옷마다 색 칸(1~6)·재질별 도달 딱지·기본색·염색 프리셋으로 보내기·벗기.
// 외형 탭 부위(머리)는 카드가 없다 — 색은 왼쪽 색 상자에서 (main.js).
import { esc, rpc, flash } from './ui.js';
import { label, tip } from './list.js';

export const LOOK_PARTS = ['Hair'];   // 외형 탭에서 입히는 부위
const REACH_MEMO_MAX = 500;

export class WornCards {
  /**
   * box: 카드 칸, empty: 빈 안내, D: Dresser.
   * hooks: { takeOff(part) — 벗기기 (화면 갱신·저장까지), colorsDone(w) — 색을 다 고른 뒤 (옷 색 기억·저장) }.
   */
  constructor(box, empty, D, hooks) {
    this.box = box;
    this.empty = empty;
    this.D = D;
    this.h = hooks;
    this.names = {};
    this.order = [];
    this.reachSeq = {};
    this.reachMemo = new Map();   // 색 목록 → 재질별 도달 판정 (Promise — 색에만 달려 있다)
    box.addEventListener('input', (e) => this.onDye(e, false));
    box.addEventListener('change', (e) => this.onDye(e, true));
    box.addEventListener('click', (e) => this.onClick(e));
  }

  /** 목록을 받은 뒤 — 부위 이름·순서. */
  setCatalog(cat) {
    this.names = Object.fromEntries(cat.parts.map((p) => [p.id, p.name]));
    this.order = cat.parts.map((p) => p.id);
  }

  /** 염색 불가 옷인가 (모델을 다 불러온 뒤에만 안다). */
  noDye(w) {
    return !!w.model && !this.D.defaultColors(w);
  }

  card(part) {
    return this.box.querySelector(`.card[data-part="${CSS.escape(part)}"]`);
  }

  paint() {
    const D = this.D;
    const parts = Object.keys(D.worn).filter((p) => !LOOK_PARTS.includes(p)).sort((a, b) => this.order.indexOf(a) - this.order.indexOf(b));
    this.empty.classList.toggle('hidden', parts.length > 0);
    this.box.innerHTML = parts.map((p) => {
      const w = D.worn[p];
      const cols = w.colors || [];
      const fixed = this.noDye(w);
      const rows = fixed ? '<div class="mute small" title="게임에서 염색할 수 없는 옷 — 그림 색 그대로">염색 불가</div>' : (cols.length ? cols : [null, null, null]).map((_, i) => `
        <div class="dye">
          <span class="dye-no">${i + 1}</span>
          <input type="color" data-dye="${i}" value="${(cols[i] || '#ffffff').toLowerCase()}" ${w.model ? '' : 'disabled'}>
          <span class="dye-hex">${esc(cols[i] || '')}</span>
          <span class="reach" data-reach="${i}"></span>
        </div>`).join('');
      return `<div class="card${w.model ? '' : ' load'}" data-part="${esc(p)}">
        <div class="card-head">
          <span class="card-part">${esc(this.names[p] || p)}</span>
          <span class="card-name" title="${esc(tip(w.item))}">${esc(label(w.item))}</span>
          <button class="btn-x" data-act="off" title="벗기">×</button>
        </div>
        ${rows}
        ${fixed ? '' : `<div class="card-foot">
          <button class="btn btn-sm" data-act="reset" title="이 옷의 기본 염색으로">기본색</button>
          <button class="btn btn-sm" data-act="preset" title="색을 염색 탭 프리셋으로 더한다 (앞 세 칸)">프리셋으로</button>
        </div>`}
      </div>`;
    }).join('');
    for (const p of parts) if (!this.noDye(D.worn[p])) this.paintReach(p);
  }

  /** 색마다 재질별로 팔레트에서 집을 수 있나 (염색 탭과 같은 판정) — 같은 색 목록은 한 번만 묻는다 (실패는 다음에 다시). */
  reach(colors) {
    const k = colors.join('|');
    if (!this.reachMemo.has(k)) {
      if (this.reachMemo.size >= REACH_MEMO_MAX) this.reachMemo.clear();
      const forget = (r) => { if (!r || r.error) this.reachMemo.delete(k); return r; };
      this.reachMemo.set(k, rpc('reach', colors).then(forget, () => forget(null)));
    }
    return this.reachMemo.get(k);
  }

  async paintReach(part) {
    const w = this.D.worn[part];
    if (!w || !w.colors) return;
    const seq = (this.reachSeq[part] = (this.reachSeq[part] || 0) + 1);
    const r = await this.reach(w.colors.slice());
    if (this.reachSeq[part] !== seq || this.D.worn[part] !== w) return;
    const card = this.card(part);
    if (!card) return;
    w.colors.forEach((_, i) => {
      const box = card.querySelector(`[data-reach="${i}"]`);
      if (!box) return;
      const rs = r && !r.error ? r.colors[i] : null;
      box.title = r && r.error ? r.error : '';
      box.innerHTML = (rs || []).map((x) => `<span class="tag lv-${esc(x.level)}" title="${esc(reachTip(x))}">${esc(x.name + ' ' + x.label)}</span>`).join('');
    });
  }

  /** 카드 색 칸 i 를 바꾼다 — done 이면 다 고른 것 (도달 딱지·기억·저장). */
  setColor(part, i, hex, done) {
    const w = this.D.setDye(part, i, hex);
    if (!w) return;
    const card = this.card(part);
    const lab = card && card.querySelectorAll('.dye-hex')[i];
    if (lab) lab.textContent = w.colors[i];
    const input = card && card.querySelector(`[data-dye="${i}"]`);
    if (input && input.value !== w.colors[i].toLowerCase()) input.value = w.colors[i].toLowerCase();
    if (done) { this.h.colorsDone(w); this.paintReach(part); }
  }

  onDye(e, done) {
    const card = e.target.closest('.card');
    if (card && e.target.dataset.dye) this.setColor(card.dataset.part, +e.target.dataset.dye, e.target.value, done);
  }

  async onClick(e) {
    const b = e.target.closest('[data-act]');
    const card = e.target.closest('.card');
    if (!b || !card) return;
    const part = card.dataset.part;
    const w = this.D.worn[part];
    if (!w) return;
    if (b.dataset.act === 'off') this.h.takeOff(part);
    else if (b.dataset.act === 'reset' && w.model) {
      this.D.setDyes(part, this.D.defaultColors(w) || w.colors);
      this.h.colorsDone(w);
      this.paint();
    } else if (b.dataset.act === 'preset' && w.colors) {
      b.disabled = true;
      try {
        const r = await rpc('to_preset', label(w.item), w.colors);
        flash(b, r && r.error ? '실패' : '넣음', r && r.error ? r.error : '');
      } catch (err) {
        flash(b, '실패', err.message);
      }
      setTimeout(() => { b.disabled = false; }, 1500);
    }
  }
}

function reachTip(x) {
  if (x.count) return '오차 안 텍셀 ' + x.count + '개';
  if (x.level === 'edge') return '텍셀 사이 섞인 자리에서만 · 가장 가까운 텍셀 ' + x.near + ' (차이 ' + x.diff + ')';
  return '가장 가까운 색 ' + x.near + ' (차이 ' + x.diff + ')';
}
