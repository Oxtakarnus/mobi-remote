// 코디·기억 값 검사 — 파일·기억(설정 파일 'dressroom')에서 온 값 중 쓸 수 있는 것만 남긴다.
// 코디 저장·내보내기·불러오기와 창을 열 때 기억 되살리기(main.js)가 같은 판정을 쓴다.
import { cleanColors } from './dresser.js';
import { cleanFace } from './face.js';

export const SHAPES = [['', '기본'], ['Thin', '마름'], ['Fat', '통통'], ['Muscular', '근육']];
export const LOOK_MAX = 200;    // 저장해 두는 코디 수
const NAME_MAX = 40;
const HEX = /^#[0-9A-Fa-f]{6}$/;

export const cleanShape = (s) => (SHAPES.some(([k]) => k === s) ? s : '');
export const cleanSkin = (s) => (typeof s === 'string' && HEX.test(s) ? s.toUpperCase() : null);
export const okAge = (v) => Number.isInteger(v);
export const okHeight = (v) => typeof v === 'number' && v >= -1 && v <= 1;
export const cleanName = (s) => String(s || '').trim().slice(0, NAME_MAX);

/** 입은 것 {부위: {id, colors}} → 아는 부위·id 가 있는 칸만. 색은 꼴이 맞을 때만 (아니면 null = 모델 기본색). */
export function cleanWorn(w, parts) {
  const out = {};
  for (const [p, x] of Object.entries(w && typeof w === 'object' ? w : {})) {
    if (!parts.has(p) || !x || typeof x.id !== 'string') continue;
    out[p] = { id: x.id, colors: cleanColors(x.colors) };
  }
  return out;
}

/** 코디 하나 → 쓸 수 있는 값만 (모르는 체형이면 null). cat: 목록 (bodies·parts), ft: 얼굴 표 (face.js FaceTable). */
export function cleanLook(L, cat, ft) {
  if (!L || typeof L !== 'object' || !cat.bodies.some((b) => b.id === L.body)) return null;
  return {
    name: cleanName(L.name) || '코디',
    body: L.body,
    shape: cleanShape(L.shape),
    age: okAge(L.age) ? L.age : null,
    height: okHeight(L.height) ? L.height : 0,
    skin: cleanSkin(L.skin),
    face: L.face ? cleanFace(L.face, ft) : null,
    worn: cleanWorn(L.worn, new Set(cat.parts.map((p) => p.id))),
  };
}

/** 체형마다 둔 값 {체형: 값} → 아는 체형·ok(값) 인 것만. */
export function perBody(o, cat, ok) {
  return Object.fromEntries(Object.entries(o && typeof o === 'object' ? o : {})
    .filter(([b, v]) => cat.bodies.some((x) => x.id === b) && ok(v)));
}
