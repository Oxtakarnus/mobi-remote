// 얼굴 꾸미기 — 게임 캐릭터 만들기 선택지(mabi/dress/face.py 가 만든 표)로 얼굴형·눈·입·문신·수염을 고른다.
// 고른 값은 시트 id 다 (게임 패킷의 캐릭터 외형 값과 같다 — 눈·입은 그룹 id). 체형마다 따로 기억한다.
//   얼굴형·눈·수염   메시를 바꾼다 ('face:<부품 모델>' — 안 골랐으면 체형 기본 머리·눈)
//   입·문신         데칼 그림을 얼굴(입은 두 번째 UV)·몸 재질에 얹는다 ('decal:<부품 모델>')
// 입 모델은 얼굴형마다 다르다 — 얼굴형을 안 골랐으면 첫 얼굴형(계란형) 것을 쓴다.

export const KINDS = [['heads', '얼굴형'], ['eyes', '눈'], ['mouths', '입'], ['ftats', '얼굴 문신'], ['btats', '몸 문신'], ['beards', '수염']];
export const MESH = { heads: 1, eyes: 2, beards: 3 };      // 메시를 바꾸는 것 → 기본 모델 자리 (몸 0)
export const DECAL = { mouths: 'lips', ftats: 'face', btats: 'body' };   // 데칼 → 얹는 자리
export const OPTIONAL = new Set(['ftats', 'btats', 'beards']);   // '없음' 이 기본인 것 (나머지는 체형 기본)
const HEX = /^#[0-9A-Fa-f]{6}$/;

/** 얼굴 선택지 표 — 없으면(게임 시트를 못 읽음) ok 가 false 이고 모든 값이 기본으로 간다. */
export class FaceTable {
  constructor(t) {
    this.t = t && Array.isArray(t.heads) ? t : null;
    this.by = {};
    for (const [k] of KINDS) this.by[k] = new Map((this.t ? this.t[k] : []).map((e) => [e.id, e]));
  }

  get ok() { return !!this.t; }

  /** 얼굴형 열쇠 — 고른 것이 없으면 이 체형의 첫 얼굴형. */
  head(face, body) {
    const h = face.heads != null && this.by.heads.get(face.heads);
    if (h && h.m[body]) return h.id;
    const first = (this.t ? this.t.heads : []).find((e) => e.m[body]);
    return first ? first.id : null;
  }

  /** 체형(·얼굴형)에서 고를 수 있는 것들. age 보다 높은 나이 제한은 뺀다. */
  entries(kind, body, head, age) {
    return (this.t ? this.t[kind] : []).filter((e) => (age == null || e.age <= age) && !!this._model(e, kind, body, head));
  }

  _model(e, kind, body, head) {
    return kind === 'mouths' ? (e.m[String(head)] || {})[body] : e.m[body];
  }

  /** 고른 값 → 부품 모델 이름 (안 골랐거나 이 체형에 없으면 null). */
  model(kind, face, body) {
    const e = face[kind] != null && this.by[kind].get(face[kind]);
    return e ? this._model(e, kind, body, this.head(face, body)) || null : null;
  }

  part(model) { return (this.t && this.t.parts[model]) || null; }

  colors(set) { return (this.t && this.t.colors[set]) || []; }

  /** 색 표에서 id 로 (패킷 외형 값용). */
  color(set, id) { return this.colors(set).find((c) => c.id === id) || null; }
}

export function emptyFace() {
  return { heads: null, eyes: null, mouths: null, ftats: null, btats: null, beards: null, eye: null, tat: null };
}

/** 기억·파일에서 온 얼굴 → 쓸 수 있는 값만. 표에 없는 id 는 버린다 (표가 없으면 그대로 둔다). */
export function cleanFace(f, table) {
  const out = emptyFace();
  if (!f || typeof f !== 'object') return out;
  for (const [k] of KINDS) if (Number.isInteger(f[k]) && (!table.ok || table.by[k].has(f[k]))) out[k] = f[k];
  for (const k of ['eye', 'tat']) if (typeof f[k] === 'string' && HEX.test(f[k])) out[k] = f[k].toUpperCase();
  return out;
}
