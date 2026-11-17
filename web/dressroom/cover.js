// 옷이 가리는 것 — 입은 옷들의 가림 규칙(모델 json rules, mabi/dress/cover.py)·후드 메시·모자 단계로
// 숨길 부위·머리 단계·후드 모양을 정한다. 참고한 웹 드레스룸의 판정을 옮겼다:
//   로브를 입으면 상의·하의·한 벌·백팩을 숨긴다 (로브 밑 옷은 그리지 않는다)
//   후드를 쓰면(후드 쓴 메시가 있는 옷일 때만) 모자를 숨기고 머리는 H5
//   옷마다 Hide<부위> 는 늘, Hide<부위>ByHelmetCover 는 투구 덮개를 닫았을 때만 숨긴다 — 자기 부위를 숨기라면 그 부위를
//   대신 차지한다 (가발: 투구 칸에 입지만 모델 정의 부위가 머리카락이고 HideHair — 원래 머리를 숨기고 자기는 보인다)
//   후드를 벗었을 때 지금 머리 단계에서 후드를 누르는 머리(press)면 눌린 모양, 아니면 벗은 모양
//   숨지 않은 장식 중 입 모양을 정하는 것(mouth — 풍선껌)이 있으면 입을 표정 표 그 칸으로
// 게임 부위 이름: Helmet·Hair·Head·Eye·LeftEye·RightEye·LeftEyebrow·RightEyebrow·Beard·Accessory0~2·AccessoryBody0(백팩)·
//   Top·Bottom·OnePiece·OnePieceWithShoes·Hand·Foot·Robe

/** 우리 부위 → 게임 부위 이름 (같으면 없음) — 모델 정의의 부위(fit.slot)가 없을 때. */
const GAME_SLOT = { FaceDeco: 'Accessory0', EyeDeco: 'Accessory1', EarDeco: 'Accessory2' };
/** 입은 옷의 게임 부위 — 모델 정의의 부위가 먼저 (백팩은 로브 칸에 입지만 AccessoryBody0), 없으면 우리 부위 이름으로. */
export const gameSlot = (part, fit) => (fit && fit.slot) || GAME_SLOT[part] || part;

const ROBE_HIDES = ['Top', 'Bottom', 'OnePiece', 'OnePieceWithShoes', 'AccessoryBody0'];
const HOOD_HAIR = 5;   // 후드 쓴 머리 단계

/**
 * parts: [{ slot: 게임 부위, rules: {hide, cap, press} | null, hoods: 가진 후드 모양 ['on'|'off'|'pressed'], cover: 모자 단계 }]
 * opt: { hood: 후드 쓰기, cap: 투구 덮개 닫기 }
 * → { hidden: Set(게임 부위), shown: [parts 마다 보이나], hair: 머리 단계, hood: 'on'|'pressed'|'off', canHood, canCap,
 *     mouth: 입 표정 칸 | 0 }
 */
export function coverage(parts, opt = {}) {
  const robe = parts.some((p) => p.slot === 'Robe');
  const list = robe ? parts.filter((p) => !ROBE_HIDES.includes(p.slot)) : parts;
  const canHood = list.some((p) => p.hoods.includes('on'));
  const hooded = !!opt.hood && canHood;
  const hidden = new Set(robe ? ROBE_HIDES : []);
  if (hooded) hidden.add('Helmet');
  const owner = new Map();   // 부위 → 그 부위를 대신 차지한 옷
  let level = 0;
  let canCap = false;
  for (const p of list) {
    if (hooded && p.slot === 'Helmet') continue;
    level = Math.max(level, p.cover || 0);
    const r = p.rules || {};
    if (r.cap && r.cap.length) canCap = true;
    for (const s of [...(r.hide || []), ...(opt.cap ? r.cap || [] : [])]) {
      if (s === p.slot) owner.set(s, p); else hidden.add(s);
    }
  }
  const visible = (p) => !hidden.has(p.slot) && (!owner.has(p.slot) || owner.get(p.slot) === p);
  const hair = hooded ? HOOD_HAIR : level;
  const pressed = !hooded && list.some((p) => p.hoods.includes('pressed')) && list.some((p) => {
    const pr = p.rules && p.rules.press;
    return pr && (pr === 'all' || pr.includes(hair)) && visible(p);
  });
  const mouthBy = list.find((p) => p.rules && p.rules.mouth && visible(p));
  return { hidden, shown: parts.map(visible), hair, hood: hooded ? 'on' : pressed ? 'pressed' : 'off', canHood, canCap,
    mouth: mouthBy ? mouthBy.rules.mouth : 0 };
}

// 겹침 순서 — 참고한 웹 드레스룸의 판정 (게임 옷 맞춤 순서). 두 옷이 같은 이음새(허리·손목·발목)를 가지면(로브는 늘)
// 이음새 크기가 큰 옷이 바깥, 같으면 부위 순위(로브 > 장갑 > 상의·신발 > 하의·한 벌)가 높은 옷이 바깥.
const SIZE = { VeryLowest: -20, Lowest: -10, Medium: 0, Highest: 10, VeryHighest: 20 };
const SLOT_RANK = { Robe: 10, Hand: 9, Top: 8, Foot: 8, Bottom: 7, OnePiece: 7, OnePieceWithShoes: 7 };
const JUNCTIONS = ['WaistSize', 'WristSize', 'AnkleSize'];

// 겹침에 끼는 옷 — 이음새가 있거나 로브 (모자·머리·장식·백팩은 안 낀다)
const layered = (f) => !!f && (f.slot === 'Robe' || JUNCTIONS.some((k) => (f.junctions || {})[k] != null));

/** 옷 a 가 옷 b 바깥인가 — a·b 는 모델 json fit {slot, junctions} (mabi/dress/cover.py). 순서를 못 정하면 false. */
export function outside(a, b) {
  if (!layered(a) || !layered(b)) return false;
  const ja = a.junctions || {}, jb = b.junctions || {};
  const both = JUNCTIONS.filter((k) => ja[k] != null && jb[k] != null);
  if (a.slot !== 'Robe' && b.slot !== 'Robe' && !both.length) return false;
  for (const k of both) if (ja[k] !== jb[k]) return (SIZE[ja[k]] || 0) > (SIZE[jb[k]] || 0);
  return (SLOT_RANK[a.slot] || 0) > (SLOT_RANK[b.slot] || 0);
}

/** 안쪽 옷의 메시가 바깥 옷의 자르는 판을 안 받나 — 치마 메시는 신발이, 상의의 겉옷(outer) 메시는 하의·신발이 자르지 않는다
 *  (참고한 웹 드레스룸의 예외). inner·outer 는 게임 부위(fit.slot). */
export function uncut(meshName, inner, outer) {
  const n = (meshName || '').toLowerCase();
  if (inner === 'Top' && (outer === 'Bottom' || outer === 'Foot') && n.includes('outer')) return true;
  return outer === 'Foot' && ['Bottom', 'OnePiece', 'Robe'].includes(inner) && n.includes('skirt');
}

/**
 * 판(몸 자르는 고리·옷 자르는 판) 특례 — 잘리는 쪽 부위 inner(몸은 'Body')와 자르는 옷 부위 outer 로 (참고한 웹 드레스룸의 표).
 *   waistDown  허리 판이 종아리·발까지 맡고 혼자 넘어도 숨긴다 (신발이 몸을, 하의가 상의를 자를 때)
 *   waistUp    허리 판이 가슴까지 맡고 혼자 넘어도 숨긴다 (원피스·로브·상의가 몸을 자를 때)
 *   hipUp      엉덩이 판이 가슴까지 맡는다 (원피스·로브가 몸을 자를 때)
 *   dropTorso  허리·엉덩이 판이 없으면 골반·가슴을 통째로 숨긴다 (원피스·로브가 몸을 자를 때)
 */
export function seamRule(inner, outer) {
  const body = inner === 'Body';
  const wear = body && ['OnePiece', 'OnePieceWithShoes', 'Robe'].includes(outer);
  return {
    waistDown: (body && outer === 'Foot') || (inner === 'Top' && outer === 'Bottom'),
    waistUp: wear || (body && outer === 'Top'),
    hipUp: wear,
    dropTorso: wear,
  };
}

// 눈 모델 메시 이름
export const EYE_MESH = { left: /^Mesh_EyeBase_L(_|$)/, right: /^Mesh_EyeBase_R(_|$)/, ball: /^Mesh_Eye(Ball|High|Shade)(_|$)/,
  brow: /^Mesh_EyeBrow(_|$)/ };

/** 눈 모델 메시가 가린 눈 부위(hidden)에도 보이나 — 눈동자·하이라이트는 두 눈 다 가렸을 때만 숨긴다 (한 메시라). */
export function eyeVisible(name, hidden) {
  if (EYE_MESH.left.test(name)) return !hidden.has('LeftEye');
  if (EYE_MESH.right.test(name)) return !hidden.has('RightEye');
  if (EYE_MESH.ball.test(name)) return !(hidden.has('LeftEye') && hidden.has('RightEye'));
  if (EYE_MESH.brow.test(name)) return !(hidden.has('LeftEyebrow') && hidden.has('RightEyebrow'));
  return true;
}
