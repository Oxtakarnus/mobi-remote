// 왼쪽 목록 — 탭 구성과 탭마다 칸 HTML (옷·머리·세트·얼굴 선택지·동작·저장한 코디). 화면 상태(S)·조립(Dresser)은
// 만들 때 받고, 얼굴·동작 표는 목록을 받은 뒤 바뀌므로 함수로 받는다. 그리기·이벤트는 main.js 가 한다.
import { esc } from './ui.js';
import { OPTIONAL } from './face.js';

// 왼쪽 탭 — 게임 꾸미기 화면처럼 외형(몸·얼굴·머리)과 의상을 나눈다 (동작은 동작 표가 있을 때만)
export const MODES = [['look', '외형'], ['wear', '의상'], ['motion', '동작'], ['looks', '내 코디']];
export const LOOK_SUBS = [['body', '체형'], ['hair', '헤어'], ['eye', '눈'], ['mouth', '입'], ['head', '얼굴형'],
  ['face', '얼굴꾸밈'], ['mark', '몸꾸밈']];
export const WEAR_SUBS = [['Helmet', '모자'], ['Top', '상의'], ['Bottom', '하의'], ['Gloves', '장갑'], ['Shoes', '신발'], ['Robe', '로브'],
  ['FaceDeco', '얼굴 장식'], ['EyeDeco', '눈 장식'], ['EarDeco', '귀 장식'], ['Weapon', '무기'],
  ['__sets', '세트'], ['__fav', '즐겨찾기'], ['__recent', '최근 입은 옷']];
export const CLOTHES = ['Helmet', 'Top', 'OnePiece', 'Bottom', 'Gloves', 'Shoes', 'Robe', 'FaceDeco', 'EyeDeco', 'EarDeco', 'Weapon'];   // 의상 탭 부위 (머리는 외형)
const LOOK_ITEMS = { hair: 'Hair' };   // 외형 하위 탭 중 목록 품목으로 고르는 것 → 부위
const SUB_PARTS = { Top: ['Top', 'OnePiece'] };   // 게임처럼 한 벌은 상의 탭에
export const FACE_SUB = { eye: ['eyes'], mouth: ['mouths'], head: ['heads'], face: ['beards', 'ftats'], mark: ['btats'] };
const FACE_NAME = { beards: '수염', ftats: '얼굴 문양' };

const EMPTY = '<div class="mute small empty">없음</div>';

/** 보여 줄 이름 — 게임 아이템 이름, 없으면 모델에서 만든 영어 이름. */
export const label = (i) => i.kor || i.name;

export function tip(i) {
  const lines = i.kor ? [i.kor, i.name + ' · ' + i.id] : [i.id];
  if (i.set) lines.push('세트: ' + i.set);
  if (i.alt && i.alt.length) lines.push('다른 이름: ' + i.alt.join(', '));
  return lines.join('\n');
}

export function matches(i, q) {
  return [i.kor, i.name, i.id, i.set, ...(i.alt || [])].some((x) => x && x.toLowerCase().includes(q));
}

export class ItemList {
  /**
   * ctx: { S (화면 상태 — cat·fav·recent·looks·moreOpen·motion·expr), D (Dresser), bad (못 읽은 모델 id Set),
   *        icons (icons.js IconLoader), ft() → 얼굴 표, mt() → 동작 표, face() → 지금 체형의 얼굴 고른 값 }.
   */
  constructor(ctx) {
    this.c = ctx;
    this.partNames = {};
  }

  /** 목록을 받은 뒤 — 부위 이름 표. */
  setCatalog(cat) {
    this.partNames = Object.fromEntries(cat.parts.map((p) => [p.id, p.name]));
  }

  get S() { return this.c.S; }
  get D() { return this.c.D; }

  /** 의상 탭에 나오는 옷인가 (이 체형이 입을 수 있는 의상 부위). */
  isClothes(i) {
    return this.D.fits(i) && CLOTHES.includes(i.part);
  }

  /** 세트 이름 → 이 체형이 입을 그 세트 의상. */
  setItems(name) {
    return this.S.cat.items.filter((i) => i.set === name && this.isClothes(i));
  }

  age() {
    return this.D.fit ? this.D.fit.state.age : null;
  }

  /** 이 체형(·얼굴형·나이)에서 고를 얼굴 선택지가 있나. */
  hasKind(kind) {
    const ft = this.c.ft(), f = this.c.face(), body = this.D.body;
    return ft.entries(kind, body, ft.head(f, body), this.age()).length > 0;
  }

  /** 탭의 하위 탭 (외형은 이 체형에서 고를 것이 있는 것만). */
  subsOf(mode) {
    if (mode === 'wear') return WEAR_SUBS;
    if (mode === 'motion') return this.c.mt().cats();
    if (mode !== 'look') return [];
    return LOOK_SUBS.filter(([k]) => {
      if (k === 'body') return true;
      if (LOOK_ITEMS[k]) return this.S.cat.items.some((i) => i.part === LOOK_ITEMS[k] && this.D.fits(i));
      return this.c.ft().ok && FACE_SUB[k].some((kind) => this.hasKind(kind));
    });
  }

  /** 탭·하위 탭·검색어(소문자) → {html, n: 개수 (null 이면 얼굴 칸을 센다, -1 이면 안 보임), title}. */
  html(mode, k, q) {
    if (mode === 'looks') return { html: this.looksHtml(q), n: this.S.looks.length, title: '저장한 코디' };
    if (mode === 'look') return { ...this.lookHtml(k, q), title: (LOOK_SUBS.find(([x]) => x === k) || [, ''])[1] };
    if (mode === 'motion') return { ...this.motionHtml(k, q), title: q ? '찾기' : this.c.mt().catName(k) };
    return { ...this.wearHtml(k, q), title: q ? '찾기' : (WEAR_SUBS.find(([x]) => x === k) || [, ''])[1] };
  }

  /** 입은 표시(.on)·못 읽은 표시(.bad)만 다시 — 옷을 입고 벗을 때 (목록 전체를 다시 그리지 않는다). */
  markWorn(root) {
    const worn = new Set(Object.values(this.D.worn).map((w) => w.item.id));
    for (const el of root.querySelectorAll('[data-id]')) {
      el.classList.toggle('on', worn.has(el.dataset.id));
      el.classList.toggle('bad', this.c.bad.has(el.dataset.id));
    }
    for (const el of root.querySelectorAll('[data-set]')) el.classList.toggle('on', this.setItems(el.dataset.set).every((i) => worn.has(i.id)));
  }

  /**
   * 옷·머리 칸 HTML. badge(i) → 칸 위 작은 딱지 글자. all 이면 이름 없는 모델도 칸으로 (순서 그대로),
   * 아니면 이름 있는 것은 아이콘 칸, 이름 없는 모델은 아래 접힌 줄. star 면 즐겨찾기 단추.
   */
  itemsHtml(items, { badge = () => '', all = false, star = true } = {}) {
    const worn = new Set(Object.values(this.D.worn).map((w) => w.item.id));
    const fav = new Set(this.S.fav), bad = this.c.bad;
    const cls = (i) => (worn.has(i.id) ? ' on' : '') + (bad.has(i.id) ? ' bad' : '');
    const pt = (i) => { const b = badge(i); return b ? `<span class="pt">${esc(b)}</span>` : ''; };
    const named = all ? items : items.filter((i) => i.kor), rest = all ? [] : items.filter((i) => !i.kor);
    const tiles = named.map((i) => {
      const url = this.c.icons.get(i.id);
      const st = star ? `<button class="star${fav.has(i.id) ? ' on' : ''}" data-fav="${esc(i.id)}" title="즐겨찾기">${fav.has(i.id) ? '★' : '☆'}</button>` : '';
      return `<div class="tile${cls(i)}" data-id="${esc(i.id)}" data-part="${esc(i.part)}" data-icon="${esc(i.id)}" title="${esc(tip(i))}">`
        + `<div class="ic"><img alt=""${url ? ` src="${esc(url)}"` : ''}></div><div class="nm">${esc(label(i))}</div>${pt(i)}${st}</div>`;
    }).join('');
    const rows = rest.map((i) => `<div class="it${cls(i)}" data-id="${esc(i.id)}" data-part="${esc(i.part)}" title="${esc(tip(i))}">${pt(i)}${esc(i.name)}</div>`).join('');
    return (tiles ? `<div class="grid">${tiles}</div>` : '')
      + (rows ? `<details class="more"${this.S.moreOpen ? ' open' : ''}><summary title="게임 아이템 이름이 없는 모델 (NPC·미출시 옷 등)">이름 없는 모델 ${rest.length}개</summary>${rows}</details>` : '')
      + (items.length ? '' : EMPTY);
  }

  /** 세트 칸 — 같은 세트 이름의 의상 둘 이상. 누르면 다 입는다 (data-set). */
  setsHtml(q) {
    const sets = new Map();
    for (const i of this.S.cat.items) {
      if (!i.set || !this.isClothes(i)) continue;
      if (!sets.has(i.set)) sets.set(i.set, []);
      sets.get(i.set).push(i);
    }
    const worn = new Set(Object.values(this.D.worn).map((w) => w.item.id));
    const rows = [...sets].filter(([n, a]) => a.length > 1 && (!q || n.toLowerCase().includes(q) || a.some((i) => matches(i, q))))
      .sort((a, b) => a[0].localeCompare(b[0], 'ko'));
    const tiles = rows.map(([n, a]) => {
      const first = a.find((i) => i.kor) || a[0];
      const url = this.c.icons.get(first.id);
      const on = a.every((i) => worn.has(i.id)) ? ' on' : '';
      return `<div class="tile${on}" data-set="${esc(n)}" data-icon="${esc(first.id)}" title="${esc(n + '\n' + a.map(label).join('\n'))}">`
        + `<div class="ic"><img alt=""${url ? ` src="${esc(url)}"` : ''}></div><div class="nm">${esc(n)}</div><span class="pt">${a.length}벌</span></div>`;
    }).join('');
    return { html: tiles ? `<div class="grid">${tiles}</div>` : EMPTY, n: rows.length };
  }

  /**
   * 얼굴 선택지 칸 HTML (아이콘·이름) — 칸은 data-fk(종류)·data-fid(id, 기본·없음은 '')·data-icon.
   * q: 검색어 (이름). 고를 것이 없으면 ''.
   */
  faceGrid(kind, q) {
    const ft = this.c.ft(), face = this.c.face(), body = this.D.body;
    const list = ft.entries(kind, body, ft.head(face, body), this.age()).filter((e) => !q || e.name.toLowerCase().includes(q));
    const optional = OPTIONAL.has(kind);
    const first = `<div class="tile${face[kind] == null ? ' on' : ''}" data-fk="${kind}" data-fid="" title="${optional ? '' : '체형 기본 모습'}">`
      + `<div class="ic"></div><div class="nm">${optional ? '없음' : '기본'}</div></div>`;
    const tiles = list.map((e) => {
      const ic = e.icon && e.icon[body] ? 'fi:' + e.icon[body] : '';
      const url = ic ? this.c.icons.get(ic) : null;
      const t = [e.name, ft.model(kind, { ...face, [kind]: e.id }, body)].filter(Boolean).join('\n');
      return `<div class="tile${face[kind] === e.id ? ' on' : ''}" data-fk="${kind}" data-fid="${e.id}"${ic ? ` data-icon="${esc(ic)}"` : ''} title="${esc(t)}">`
        + `<div class="ic"><img alt=""${url ? ` src="${esc(url)}"` : ''}></div><div class="nm">${esc(e.name)}</div></div>`;
    }).join('');
    return list.length || !q ? `<div class="grid">${q ? '' : first}${tiles}</div>` : '';
  }

  /** 외형 하위 탭 — {html, n (null 이면 칸을 센다)}. */
  lookHtml(k, q) {
    if (k === 'body') return { html: '', n: -1 };
    if (LOOK_ITEMS[k]) {
      const items = this.S.cat.items.filter((i) => i.part === LOOK_ITEMS[k] && this.D.fits(i) && (!q || matches(i, q)));
      const badge = k === 'hair' ? (i) => (this.D.twoTone(i.id) ? '투톤' : '') : undefined;
      return { html: this.itemsHtml(items, { star: false, badge }), n: items.length };
    }
    const kinds = FACE_SUB[k].filter((kind) => this.hasKind(kind));
    const html = kinds.map((kind) => {
      const g = this.faceGrid(kind, q);
      return g && kinds.length > 1 ? `<div class="sec">${FACE_NAME[kind] || ''}</div>${g}` : g;
    }).join('');
    return { html: html || EMPTY, n: null };
  }

  /** 의상 하위 탭 — {html, n}. 검색어가 있으면 모든 부위에서 찾는다. */
  wearHtml(k, q) {
    const names = this.partNames;
    const partBadge = (i) => names[i.part] || i.part;
    if (q) {
      const items = this.S.cat.items.filter((i) => this.isClothes(i) && matches(i, q));
      return { html: this.itemsHtml(items, { badge: partBadge }), n: items.length };
    }
    if (k === '__sets') return this.setsHtml(q);
    if (k === '__fav' || k === '__recent') {
      const by = new Map(this.S.cat.items.filter((i) => this.isClothes(i)).map((i) => [i.id, i]));
      const items = (k === '__fav' ? this.S.fav : this.S.recent).map((id) => by.get(id)).filter(Boolean);
      const empty = k === '__fav' ? '의상 칸의 ☆ 를 누르면 여기에 모인다' : '목록에서 입은 의상이 차례로 남는다';
      return { html: items.length ? this.itemsHtml(items, { badge: partBadge, all: true }) : `<div class="mute small empty">${empty}</div>`, n: items.length };
    }
    const parts = SUB_PARTS[k] || [k];
    const items = this.S.cat.items.filter((i) => this.D.fits(i) && parts.includes(i.part));
    return { html: this.itemsHtml(items, { badge: (i) => (parts.length > 1 && i.part !== k ? names[i.part] : '') }), n: items.length };
  }

  /** 동작 탭 — {html, n}. 검색어가 있으면 모든 갈래에서 찾는다. */
  motionHtml(k, q) {
    const mt = this.c.mt();
    const list = mt.list(q ? null : k, this.D.folder(), q);
    const rows = list.map((e) => {
      const badge = q ? `<span class="pt">${esc(mt.catName(e.cat))}</span>` : '';
      const on = e.id === this.S.motion || e.id === this.S.expr ? ' on' : '';
      return `<div class="it${on}" data-motion="${esc(e.id)}" title="${esc(this.motionTip(e))}">${badge}${esc(e.name)}</div>`;
    }).join('');
    return { html: rows || EMPTY, n: list.length };
  }

  /** 동작 칸 풍선 — 단계 파일과 표정 여부. */
  motionTip(e) {
    const mt = this.c.mt(), folder = this.D.folder();
    if (mt.isFace(e.id)) return (mt.faceStem(e.id, folder) || '') + '\n얼굴만 — 지금 동작 위에 반복' + (e.id === this.S.expr ? '\n다시 누르면 끈다' : '');
    const st = mt.steps(e.id, folder, this.D.shape) || [];
    const lines = st.map((s, i) => (i === st.length - 1 ? '반복 ' : '한 번 ') + s.body + (s.face ? ' · 표정' : ''));
    if (e.id === this.S.motion) lines.push('다시 누르면 대기 동작으로');
    return lines.join('\n');
  }

  /** '내 코디' 탭 목록 — 최근 저장한 것이 위. 줄은 data-look(자리), 지우기는 data-del. */
  looksHtml(q) {
    const looks = this.S.looks;
    const names = Object.fromEntries(this.S.cat.bodies.map((b) => [b.id, b.name]));
    const rows = looks.map((L, i) => [L, i]).filter(([L]) => !q || L.name.toLowerCase().includes(q)).reverse();
    if (!rows.length) return `<div class="mute small empty">${looks.length ? '찾는 코디 없음' : '저장한 코디 없음'}</div>`;
    return rows.map(([L, i]) => `<div class="it look-row" data-look="${i}" title="눌러서 입히기">`
      + `<span class="pt">${esc(names[L.body] || L.body)}</span><span class="look-nm">${esc(L.name)}</span>`
      + `<button class="btn-x" data-del="${i}" title="지우기 (두 번 누른다)">×</button></div>`).join('');
  }
}
