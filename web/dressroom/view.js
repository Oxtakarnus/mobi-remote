// 화면 설정 판 — 전체 화면·시선·원근·무대·조명·탭 카메라·메시 보기·성능(해상도·프레임·계단 줄이기·그림자·바닥 반사·다른 창이면 멈춤).
// 값은 드레스룸 기억(save_prefs 'view')에 둔다. 계단 줄이기(MSAA)는 3D 화면을 만들 때만 정해져서 바꾸면 화면을 다시 연다.

import { SCENES, LIGHTS } from './backdrop.js';
import { esc } from './ui.js';

export const FOV = { rebirth: 50, field: 23.2 };   // 원근 — 게임 환생(꾸미기) 창 · 인게임 카메라 (도)
export const VIEW_DEFAULT = { fov: 'rebirth', tabCam: true, wire: false, scale: 1, fps: 'auto', aa: true, pauseBlur: false, shadow: 1024,
  scene: 'rebirth', light: 'rebirth', reflect: true };

const SCALES = [['0.5', '최저'], ['0.75', '낮음'], ['1', '보통'], ['1.5', '높음']];
const FPS = [['auto', '자동'], ['30', '30'], ['60', '60']];
const SHADOWS = [['0', '끄기'], ['512', '낮음'], ['1024', '보통'], ['2048', '높음']];   // 바닥 그림자 맵 크기

// 시선 단추 풍선 — 툴바 '시선' 과 이 판의 '나를 보기' 가 같이 쓴다
export const GAZE_TIP = '카메라 쪽을 본다 (대기 자세에서만)';
export const GAZE_REST = '동작 중엔 꺼짐 — 대기 자세에서만';

/** 기억에서 온 값 → 쓸 수 있는 값만 (모르는 값은 기본). */
export function cleanView(v) {
  const o = v && typeof v === 'object' ? v : {};
  const d = { ...VIEW_DEFAULT };
  if (o.fov in FOV) d.fov = o.fov;
  for (const k of ['tabCam', 'wire', 'aa', 'pauseBlur', 'reflect']) if (typeof o[k] === 'boolean') d[k] = o[k];
  if (SCENES.some(([x]) => x === o.scene)) d.scene = o.scene;
  if (LIGHTS.some(([x]) => x === o.light)) d.light = o.light;
  if (SCALES.some(([x]) => +x === o.scale)) d.scale = o.scale;
  if (FPS.some(([x]) => x === String(o.fps))) d.fps = String(o.fps);
  if (SHADOWS.some(([x]) => +x === o.shadow)) d.shadow = o.shadow;
  return d;
}

/**
 * 판 하나. host: 판을 그릴 칸, hooks:
 *   get() → 지금 값, set(바뀐 값) — 적용·기억은 부른 쪽이 한다,
 *   gaze() → 시선 켜짐, gazeRest() → 시선이 쉬는 중(고른 동작), setGaze(on), fullscreen() — 켜고 끄기, isFull() → 켜짐.
 *   시선·전체 화면을 바꾼 뒤 다시 그리기는 부르는 쪽이 한다 (툴바와 같이).
 */
export class ViewPanel {
  constructor(host, hooks) {
    this.host = host;
    this.h = hooks;
    host.addEventListener('click', (e) => this.click(e));
  }

  get open() { return !this.host.classList.contains('hidden'); }

  toggle(on = !this.open) {
    this.host.classList.toggle('hidden', !on);
    if (on) this.paint();
  }

  paint() {
    const v = this.h.get();
    const rest = !!(this.h.gazeRest && this.h.gazeRest());   // 고른 동작 중엔 시선이 쉰다
    const seg = (key, opts, cur, tip = '') => `<div class="seg seg-sm"${tip ? ` title="${esc(tip)}"` : ''}>${opts.map(([val, name]) =>
      `<button data-set="${key}" data-val="${esc(val)}" class="${String(cur) === String(val) ? 'on' : ''}">${esc(name)}</button>`).join('')}</div>`;
    const field = (label, body) => `<div class="vp-field"><span class="lbl">${label}</span>${body}</div>`;
    const sw = (key, label, on, tip = '') => `<button class="vp-sw${on ? ' on' : ''}" data-flip="${key}"${tip ? ` title="${esc(tip)}"` : ''}><span>${label}</span><i></i></button>`;
    this.host.innerHTML = `
      <div class="vp-head"><b>옵션</b><button class="btn-x" data-act="close" title="닫기">×</button></div>
      <div class="seg vp-quick">
        <button data-act="full" class="${this.h.isFull() ? 'on' : ''}" title="창을 화면 가득 (Esc 로 돌아온다)">전체 화면</button>
        <button data-act="gaze" class="${this.h.gaze() && !rest ? 'on' : ''}"${rest ? ' disabled' : ''} title="${rest ? GAZE_REST : GAZE_TIP}">나를 보기</button>
      </div>
      ${field('원근', seg('fov', [['rebirth', '환생창'], ['field', '인게임']], v.fov, '환생창 50° · 인게임 23°'))}
      ${field('무대', seg('scene', SCENES, v.scene, '환생 무대: 게임 꾸미기 화면의 바닥·그릇·별 하늘'))}
      ${field('조명', seg('light', LIGHTS, v.light, '한낮·밤: 시작 마을 하루 빛'))}
      <div class="vp-sws">
        ${sw('tabCam', '탭 전환 시 카메라 이동', v.tabCam, '얼굴·상반신·발 쪽으로 옮긴다')}
        ${sw('wire', '메시 보기', v.wire)}
      </div>
      <div class="vp-sub">성능</div>
      ${field('해상도', seg('scale', SCALES, v.scale))}
      ${field('프레임', seg('fps', FPS, v.fps, '자동: 60, 다른 창을 보면 30'))}
      ${field('MSAA', seg('aa', [['false', '끄기'], ['true', '켜기']], v.aa, '바꾸면 3D 화면을 다시 불러온다'))}
      ${field('그림자', seg('shadow', SHADOWS, v.shadow, '바닥에 떨어지는 캐릭터 그림자'))}
      ${field('바닥 반사', seg('reflect', [['false', '끄기'], ['true', '켜기']], v.reflect, '환생 무대 바닥에 캐릭터를 비춘다 — 켜면 캐릭터를 두 번 그린다'))}
      <div class="vp-sws">${sw('pauseBlur', '다른 창을 보면 멈추기', v.pauseBlur)}</div>`;
  }

  async click(e) {
    const b = e.target.closest('button');
    if (!b) return;
    const v = this.h.get();
    if (b.dataset.act === 'close') { this.toggle(false); return; }
    if (b.dataset.act === 'gaze') { this.h.setGaze(!this.h.gaze()); return; }
    if (b.dataset.act === 'full') { await this.h.fullscreen(); return; }
    if (b.dataset.flip) this.h.set({ [b.dataset.flip]: !v[b.dataset.flip] });
    else if (b.dataset.set) {
      const k = b.dataset.set, raw = b.dataset.val;
      const val = k === 'scale' || k === 'shadow' ? +raw : k === 'aa' || k === 'reflect' ? raw === 'true' : raw;
      if (val === v[k]) return;
      this.h.set({ [k]: val });
    } else return;
    this.paint();
  }
}
