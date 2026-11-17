// 몸에 맞추기 — 게임 옷에는 체형 셰이프가 없고, 몸을 어디까지 가릴지는 기하와 옷의 몸 자르는 고리(Mesh_BP_*)로 정한다.
// 다 뼈대를 기본(바인드) 자세로 둔 채 부른다 (rig.rest()) — 정점은 bakePose 로 스키닝한 월드 좌표를 쓴다.
//   transferShapes  몸 셰이프(Fat·Thin·Muscular)를 가까운 몸 정점 4개에서 옷 정점으로 옮긴다 (몸에서 멀수록 약하게).
//                   가까운 정점은 몸 정점 격자에서 칸 껍질을 넓혀 가며 찾는다 (다 훑는 것과 결과가 같다).
//                   월드에서 옮긴 차이를 옷 정점의 스킨 행렬로 되돌려 메시 자기 좌표 모프로 넣는다.
//   hideCovered     몸 정점에서 법선 방향 선분(안쪽 5cm ~ 바깥 10cm — 바지 위쪽처럼 옷 면이 몸 안으로 들어간 곳도 있다)이 옷 삼각형에 닿으면 덮인 것 — 세 꼭짓점이 다 덮인 삼각형은 숨긴다.
//                   옷의 피부 조각(Mesh_Skin_Body)도 가리는 면이다 — 같은 자리 몸과 겹쳐 그리면 깜빡인다 (몸은 깊이도 살짝 뒤로, Model.pushBack).
//                   옷의 몸 자르는 고리(Mesh_BP_*) 너머 몸도 숨긴다 — 고리마다 맡은 몸 구역(뼈로 나눈 골반·가슴·팔다리)이 있고,
//                   정점은 자기 구역을 맡은 고리를 모두 넘어 덮는 쪽에 있으면 숨는다 (반바지는 허리 아래이면서 밑단 위 허벅지만)
//                   옷의 피부 조각도 같은 식으로 — 다른 옷의 천(피부 조각은 빼고)에 덮인 곳을 숨긴다 (드레스 팔 피부 위에 낀 긴 장갑)
//                   옷끼리는 바깥 옷(cover.js outside)의 자르는 판(Mesh_SP_*) 너머 안쪽 옷을 같은 판정으로 숨긴다 — 목 긴 부츠 안의 바지 자락
//   soleLift        신발 바닥이 바닥(0)보다 내려가면 그만큼 몸을 띄운다 (굽)
import * as THREE from './vendor/three.module.min.js';
import { bakePose, keepTriangles, BODY_SHAPES } from './viewer.js';
import { outside, uncut, seamRule } from './cover.js';

const K = 4;
const NEAR_FULL = 0.04;   // 이 거리(m)까지는 몸 변화를 그대로
const NEAR_ZERO = 0.20;   // 여기서 0
// 덮인 몸 판정 — 몸 정점에서 법선을 따라 안쪽 RAY_IN ~ 바깥 RAY_OUT 사이에 옷 면이 있으면 덮인 것.
// 안쪽은 바지 위쪽처럼 몸 속으로 파고든 옷 면, 바깥은 몸에 붙은 옷(깜빡임 막기)만 본다. 바깥을 멀리(10cm) 보면
// 다리 사이에서 반대쪽 다리의 가터·앞으로 늘어진 치마까지 덮개로 잡아 허벅지에 구멍이 났다 (2026-11-16 카르메나 드레스).
// 헐렁한 옷 밑 몸은 옷의 몸 자르는 고리(Mesh_BP_*)가 맡는다.
const RAY_IN = 0.05;
const RAY_OUT = 0.03;
const CELL = 0.04;
const NEAR_CELL = 0.08;   // 가까운 몸 정점 찾기 격자 (재 보니 0.05~0.12 중 이게 빨랐다)
const NEAR_MAX = 25;      // 껍질 상한 (2m) — 그 안에 몸 정점이 K 개 없으면 찾은 것만 쓴다

/** 몸 모델에서 체형 셰이프를 가진 메시. */
export function bodyMesh(model) {
  return model.meshes.find((o) => o.morphTargetDictionary && 'Fat' in o.morphTargetDictionary) || null;
}

/** 옷 모델 메시마다 몸 셰이프를 옮겨 모프로 넣는다 (자기 셰이프가 있는 메시는 그대로). */
export function transferShapes(bodyModel, model) {
  const b = bodyMesh(bodyModel);
  if (!b) return;
  const B = bakePose(b, true);
  const bn = B.P.length / 3;
  const names = BODY_SHAPES.filter((k) => k in b.morphTargetDictionary);
  // 몸 셰이프 차이 → 월드
  const WD = {};
  for (const k of names) {
    const d = b.geometry.morphAttributes.position[b.morphTargetDictionary[k]].array;
    const w = new Float32Array(d.length);
    for (let j = 0; j < bn; j++) {
      const L = B.L, o = j * 9, x = d[j * 3], y = d[j * 3 + 1], z = d[j * 3 + 2];
      w[j * 3] = L[o] * x + L[o + 3] * y + L[o + 6] * z;
      w[j * 3 + 1] = L[o + 1] * x + L[o + 4] * y + L[o + 7] * z;
      w[j * 3 + 2] = L[o + 2] * x + L[o + 5] * y + L[o + 8] * z;
    }
    WD[k] = w;
  }
  const grid = pointGrid(B.P, NEAR_CELL);
  const inv = new THREE.Matrix3();
  const v = new THREE.Vector3();
  for (const o of model.meshes) {
    if (o.morphTargetDictionary && Object.keys(o.morphTargetDictionary).length) continue;
    const C = bakePose(o, true);
    const n = C.P.length / 3;
    const out = Object.fromEntries(names.map((k) => [k, new Float32Array(n * 3)]));
    const bi = new Int32Array(K), bd = new Float64Array(K), w = new Float64Array(K);
    for (let i = 0; i < n; i++) {
      nearest(grid, B.P, C.P[i * 3], C.P[i * 3 + 1], C.P[i * 3 + 2], bi, bd);
      const fade = Math.min(1, Math.max(0, 1 - (Math.sqrt(bd[0]) - NEAR_FULL) / (NEAR_ZERO - NEAR_FULL)));
      if (!fade) continue;
      let ws = 0;
      for (let k = 0; k < K; k++) { w[k] = bi[k] < 0 ? 0 : 1 / (bd[k] + 1e-6); ws += w[k]; }
      inv.fromArray(C.L, i * 9);
      if (Math.abs(inv.determinant()) < 1e-9) continue;
      inv.invert();
      for (const name of names) {
        const s = WD[name];
        let ax = 0, ay = 0, az = 0;
        for (let k = 0; k < K; k++) {
          if (bi[k] < 0) continue;
          ax += w[k] * s[bi[k] * 3]; ay += w[k] * s[bi[k] * 3 + 1]; az += w[k] * s[bi[k] * 3 + 2];
        }
        v.set(ax, ay, az).multiplyScalar(fade / ws).applyMatrix3(inv).toArray(out[name], i * 3);
      }
    }
    o.geometry.morphAttributes.position = names.map((k) => {
      const a = new THREE.BufferAttribute(out[k], 3);
      a.name = k;
      return a;
    });
    o.geometry.morphTargetsRelative = true;
    o.updateMorphTargets();
  }
}

/** 칸 번호 (격자). */
function key(ix, iy, iz) { return (ix + 512) + (iy + 512) * 1024 + (iz + 512) * 1048576; }

/** 점 → 격자 (칸 번호 → 점 번호들). */
function pointGrid(P, cell) {
  const grid = new Map();
  for (let j = 0; j < P.length / 3; j++) {
    const k = key(Math.floor(P[j * 3] / cell), Math.floor(P[j * 3 + 1] / cell), Math.floor(P[j * 3 + 2] / cell));
    let l = grid.get(k);
    if (!l) grid.set(k, (l = []));
    l.push(j);
  }
  grid.cell = cell;
  return grid;
}

/** (x,y,z) 에 가까운 점 K 개 → bi(번호)·bd(거리²), 가까운 순. 칸 껍질 r 을 다 본 뒤 남은 점은 r 칸보다 멀다.
 *  가장 가까운 점이 NEAR_ZERO 밖이면 거기서 멈춘다 (어차피 옮기지 않는다). */
export function nearest(grid, P, x, y, z, bi, bd) {
  const cell = grid.cell;
  const cx = Math.floor(x / cell), cy = Math.floor(y / cell), cz = Math.floor(z / cell);
  bd.fill(Infinity); bi.fill(-1);
  for (let r = 0; r <= NEAR_MAX; r++) {
    for (let ix = -r; ix <= r; ix++) {
      for (let iy = -r; iy <= r; iy++) {
        const side = Math.abs(ix) === r || Math.abs(iy) === r;
        for (let iz = -r; iz <= r; iz += side ? 1 : 2 * r) {
          const l = grid.get(key(cx + ix, cy + iy, cz + iz));
          if (!l) continue;
          for (const j of l) {
            const dx = P[j * 3] - x, dy = P[j * 3 + 1] - y, dz = P[j * 3 + 2] - z;
            const d = dx * dx + dy * dy + dz * dz;
            if (d >= bd[K - 1]) continue;
            let k = K - 1;
            while (k > 0 && bd[k - 1] > d) { bd[k] = bd[k - 1]; bi[k] = bi[k - 1]; k--; }
            bd[k] = d; bi[k] = j;
          }
        }
      }
    }
    const reach = r * cell;
    if (bd[K - 1] <= reach * reach) return;
    if (reach >= NEAR_ZERO && bd[0] >= NEAR_ZERO * NEAR_ZERO) return;
  }
}

/** 옷 삼각형(기본 자세 월드, 머리카락·숨긴 메시 빼고) → 격자. skin 이면 옷의 피부 조각도 넣는다.
 *  bit: 삼각형마다 그 옷 메시의 비트 (메시가 32개를 넘으면 비트를 나눠 쓴다 — 그만큼 너그럽게 숨긴다). */
function occluders(models, pose, skin = true) {
  const tris = [], bits = [];
  let k = 0;
  for (const m of models) {
    for (const o of m.meshes) {
      if (!o.visible || o.userData.flags.hair !== undefined) continue;
      const P = pose(o).P;
      const idx = o.geometry.index.array;
      const bit = 1 << (k++ % 32);
      for (const g of o.geometry.groups) {
        const mat = o.material[g.materialIndex];   // 옷의 피부 조각(Mesh_Skin_Body)도 — 그 밑 몸과 겹쳐 그리면 깜빡인다
        if (!mat || (!skin && mat.userData.info.skin)) continue;
        for (let t = g.start; t < g.start + g.count; t++) {
          const v = idx[t] * 3;
          tris.push(P[v], P[v + 1], P[v + 2]);
          if (t % 3 === 0) bits.push(bit);
        }
      }
    }
  }
  const T = new Float32Array(tris), bit = new Int32Array(bits);
  const grid = new Map();
  for (let t = 0; t < T.length / 9; t++) {
    let x0 = Infinity, y0 = Infinity, z0 = Infinity, x1 = -Infinity, y1 = -Infinity, z1 = -Infinity;
    for (let c = 0; c < 3; c++) {
      const x = T[t * 9 + c * 3], y = T[t * 9 + c * 3 + 1], z = T[t * 9 + c * 3 + 2];
      x0 = Math.min(x0, x); y0 = Math.min(y0, y); z0 = Math.min(z0, z);
      x1 = Math.max(x1, x); y1 = Math.max(y1, y); z1 = Math.max(z1, z);
    }
    for (let ix = Math.floor(x0 / CELL); ix <= Math.floor(x1 / CELL); ix++) {
      for (let iy = Math.floor(y0 / CELL); iy <= Math.floor(y1 / CELL); iy++) {
        for (let iz = Math.floor(z0 / CELL); iz <= Math.floor(z1 / CELL); iz++) {
          const k = key(ix, iy, iz);
          let l = grid.get(k);
          if (!l) grid.set(k, (l = []));
          l.push(t);
        }
      }
    }
  }
  return { T, bit, grid, n: T.length / 9 };
}

/** 선분 o + d·t (0 ≤ t ≤ len) 이 삼각형 t 에 닿나 (Möller–Trumbore, 양면). */
function hit(T, t, ox, oy, oz, dx, dy, dz, len) {
  const a = t * 9;
  const e1x = T[a + 3] - T[a], e1y = T[a + 4] - T[a + 1], e1z = T[a + 5] - T[a + 2];
  const e2x = T[a + 6] - T[a], e2y = T[a + 7] - T[a + 1], e2z = T[a + 8] - T[a + 2];
  const px = dy * e2z - dz * e2y, py = dz * e2x - dx * e2z, pz = dx * e2y - dy * e2x;
  const det = e1x * px + e1y * py + e1z * pz;
  if (Math.abs(det) < 1e-12) return false;
  const inv = 1 / det;
  const sx = ox - T[a], sy = oy - T[a + 1], sz = oz - T[a + 2];
  const u = (sx * px + sy * py + sz * pz) * inv;
  if (u < 0 || u > 1) return false;
  const qx = sy * e1z - sz * e1y, qy = sz * e1x - sx * e1z, qz = sx * e1y - sy * e1x;
  const v = (dx * qx + dy * qy + dz * qz) * inv;
  if (v < 0 || u + v > 1) return false;
  const tt = (e2x * qx + e2y * qy + e2z * qz) * inv;
  return tt >= 0 && tt <= len;
}

const NO_OCC = { n: 0 };

/** 옷에 덮인 몸 삼각형을 숨긴다 (models 가 비면 다 보인다). 옷의 피부 조각은 다른 옷의 천에 덮인 곳을,
 *  안쪽 옷은 바깥 옷의 자르는 판 너머를. */
export function hideCovered(bodyModel, models) {
  const b = bodyMesh(bodyModel), pose = poseMemo();
  if (b) {
    const { P, N } = pose(b);
    hideUnder(b, P, N, occluders(models, pose), cutBody(b, P, models, pose));
  }
  const layers = layerCuts(models, pose);
  for (const m of models) {
    const skins = m.meshes.filter((o) => o.visible && o.material.every((x) => x && x.userData.info.skin));
    const occ = skins.length ? occluders(models.filter((x) => x !== m), pose, false) : NO_OCC;
    for (const o of m.meshes) {
      const f = o.userData.flags;
      if (f.cut || f.sep || !o.geometry.index) continue;
      const skin = skins.includes(o), cut = layers.get(o) || null;
      if (!skin && !cut && !o.userData.index0) continue;   // 자른 적 없는 천은 그대로
      const { P, N } = pose(o);
      hideUnder(o, P, N, skin ? occ : NO_OCC, cut);
    }
  }
}

/** 스킨 메시 정점 i 가 가장 크게 붙은 뼈를 돌려주는 함수. */
function ownerOf(o) {
  const bi = o.geometry.attributes.skinIndex.array, bw = o.geometry.attributes.skinWeight.array;
  return (i) => {
    let best = 0;
    for (let k = 1; k < 4; k++) if (bw[i * 4 + k] > bw[i * 4 + best]) best = k;
    return o.skeleton.bones[bi[i * 4 + best]];
  };
}

// 몸 구역 — 뼈 이름(없으면 위 뼈)으로: 머리(_Neck 아래) · 가슴(_Spine1 아래) · 골반(_Spine·_Pelvis, 가운데 치마 뼈) ·
// 좌우 위팔(쇄골 포함)·아래팔·손 · 좌우 허벅지·종아리·발 (좌우 치마 뼈는 그쪽 다리)
const REGION_RX = [
  [/^_([LR])[ _](Foot|Toe|Sole)/, 'foot'], [/^_([LR])[ _](Calf|SkirtCalf)/, 'calf'],
  [/^_([LR])[ _](Thigh|Hip|SkirtThigh|SP Skirt)/, 'thigh'],
  [/^_([LR]) (Hand|Palm|Finger)/, 'hand'], [/^_([LR]) Forearm/, 'fore'], [/^_([LR]) (UpperArm|Deltoid|Clavicle)/, 'upper'],
];
const regionMemo = new WeakMap();
function region(bone) {
  if (regionMemo.has(bone)) return regionMemo.get(bone);
  let r = 'pelvis';
  for (let b = bone; b && b.isBone; b = b.parent) {
    if (/^_(Head|Neck)$/.test(b.name)) { r = 'head'; break; }
    const hit = REGION_RX.find(([rx]) => rx.test(b.name));
    if (hit) { r = hit[0].exec(b.name)[1] + hit[1]; break; }
    if (b.name === '_Spine1') { r = 'chest'; break; }
  }
  regionMemo.set(bone, r);
  return r;
}

// 판(Mesh_BP_<이름>·Mesh_SP_<이름>)이 맡은 몸 구역 — 참고한 웹 드레스룸의 이음새별 구역 표
// (허리 판은 골반·허벅지, 윗옷 밑단·목 판은 가슴·골반, 다리 판은 그 다리 전체…). 머리는 어느 판도 맡지 않는다.
const LEG = (s) => [s + 'thigh', s + 'calf', s + 'foot'];
const ARM = (s) => [s + 'upper', s + 'fore', s + 'hand'];
const SEP_REGIONS = {
  CenterBottom: ['pelvis', 'Lthigh', 'Rthigh'], CenterTop: ['chest', 'pelvis'], Neck: ['chest', 'pelvis'],
  LLeg: LEG('L'), LFoot: LEG('L'), RLeg: LEG('R'), RFoot: LEG('R'), Skirt: [...LEG('L'), ...LEG('R')],
  LArm: ARM('L'), LHand: ARM('L'), RArm: ARM('R'), RHand: ARM('R'),
  LHipJoint: ['pelvis', 'Lthigh'], RHipJoint: ['pelvis', 'Rthigh'],
};
const CALVES = ['Lcalf', 'Lfoot', 'Rcalf', 'Rfoot'];

/**
 * 옷 모델의 판 → {planes, drop} (판이 없으면 null). flag 는 'cut'(몸 자르는 고리 Mesh_BP_*) 또는 'sep'(옷 자르는 판 Mesh_SP_*).
 * 판마다 {c, d: 면 법선(그 옷이 덮는 쪽), regions: 맡은 몸 구역, main: 혼자 넘어도 숨기나}. 이름이 구역 표에 없는 판은 건너뛴다.
 * rule(cover.js seamRule)은 잘리는 쪽·자르는 옷 부위에 따른 특례 — 허리 판이 종아리·발이나 가슴까지 맡고 혼자 넘어도 숨기거나,
 * 엉덩이 판이 가슴까지 맡거나, 허리·엉덩이 판 없는 원피스·로브는 골반·가슴을 통째로 숨긴다(drop).
 */
function seamPlanes(model, flag, rule, pose) {
  const planes = [];
  let waist = false;
  for (const o of model.meshes) {
    if (!o.isSkinnedMesh || !o.userData.flags[flag]) continue;
    const name = o.name.replace(/^Mesh_[BS]P_/, '');
    if (!SEP_REGIONS[name]) continue;
    const regions = new Set(SEP_REGIONS[name]);
    let main = false;
    if (/HipJoint$/.test(name)) {
      waist = true;
      if (rule.hipUp) regions.add('chest');
    } else if (name === 'CenterBottom') {
      waist = true;
      if (rule.waistDown) { for (const r of CALVES) regions.add(r); main = true; }
      else if (rule.waistUp) { regions.add('chest'); main = true; }
    }
    const { P, N } = pose(o);
    const plane = ringPlane(P, N);
    if (plane) planes.push({ ...plane, regions, main });
  }
  if (!planes.length) return null;
  return { planes, drop: rule.dropTorso && !waist ? new Set(['pelvis', 'chest']) : null };
}

/** 정점 i(P 의 월드 좌표, 몸 구역 where)가 판들 너머(덮이는 쪽)인가 — 그 구역을 맡은 판을 모두 넘거나(교집합), 혼자 넘어도 되는 판(main)을 넘거나, 통째로 숨길 구역이면. */
function beyond({ planes, drop }, P, i, where) {
  if (drop && drop.has(where)) return true;
  let hit = false, miss = false;
  for (const { c, d, regions, main } of planes) {
    if (!regions.has(where)) continue;
    const s = (P[i * 3] - c[0]) * d[0] + (P[i * 3 + 1] - c[1]) * d[1] + (P[i * 3 + 2] - c[2]) * d[2];
    if (s > CUT_EPS) { if (main) return true; hit = true; } else miss = true;
  }
  return hit && !miss;
}

/** 메시 o(기본 자세 월드 P)의 정점 중 seams 너머인 것을 marks 에 표시한다 (marks 가 없으면 처음 표시할 때 만든다). 표시가 없으면 null. */
function markBeyond(o, P, seams, marks) {
  const own = ownerOf(o), n = P.length / 3;
  for (let i = 0; i < n; i++) {
    if (marks && marks[i]) continue;
    if (!beyond(seams, P, i, region(own(i)))) continue;
    if (!marks) marks = new Uint8Array(n);
    marks[i] = 1;
  }
  return marks;
}

/** 같은 hideCovered 안에서 메시 자세를 한 번만 굽는다. */
function poseMemo() {
  const baked = new Map();
  return (o) => { if (!baked.has(o)) baked.set(o, bakePose(o)); return baked.get(o); };
}

/**
 * 몸 정점 중 옷의 몸 자르는 고리(Mesh_BP_*) 너머 표시 (없으면 null) — 신발 고리 너머 발, 소매 고리 너머 위팔,
 * 반바지 허리 아래이면서 밑단 위 허벅지. 모든 옷의 고리를 본다 (몸은 늘 안쪽).
 */
function cutBody(b, P, models, pose) {
  let marks = null;
  for (const m of models) {
    const seams = seamPlanes(m, 'cut', seamRule('Body', m.fit && m.fit.slot), pose);
    if (seams) marks = markBeyond(b, P, seams, marks);
  }
  return marks;
}

/**
 * 옷끼리 겹친 곳 — 바깥 옷(cover.js outside)의 자르는 판(Mesh_SP_*) 너머 안쪽 옷 정점 표시. Map(메시 → Uint8Array).
 * 목 긴 부츠 안의 바지 자락처럼. 판정은 몸과 같다 (seamPlanes·beyond). 치마·겉옷 메시 예외는 cover.js uncut.
 */
function layerCuts(models, pose) {
  const out = new Map();
  const cloth = (m) => m.meshes.filter((o) => o.visible && o.isSkinnedMesh && !o.userData.flags.cut && !o.userData.flags.sep);
  for (const outer of models) {
    for (const m of models) {
      if (m === outer || !outside(outer.fit, m.fit)) continue;
      const seams = seamPlanes(outer, 'sep', seamRule(m.fit.slot, outer.fit.slot), pose);
      if (!seams) continue;
      for (const o of cloth(m)) {
        if (uncut(o.name, m.fit.slot, outer.fit.slot)) continue;
        const marks = markBeyond(o, pose(o).P, seams, out.get(o) || null);
        if (marks) out.set(o, marks);
      }
    }
  }
  return out;
}

/**
 * 메시 b 의 정점(기본 자세 월드 P·법선 N) 중 덮인 것만으로 이뤄진 삼각형을 숨긴다. 정점마다 덮은 옷 메시를 비트로 모으고
 * (cut 표시 정점은 모든 옷), 세 꼭짓점을 같은 옷 메시가 덮어야 숨긴다 — 몸 메시는 성겨서, 아래 꼭짓점은 가터 띠·위 꼭짓점은
 * 치마 밑단에 덮이고 그 사이 살은 드러난 삼각형까지 숨기던 것 (2026-11-16 카르메나 드레스 허벅지).
 */
function hideUnder(b, pos, nrm, occ, cut) {
  if (!occ.n && !cut) {
    keepTriangles(b);
    return;
  }
  const n = pos.length / 3;
  const by = new Int32Array(n);   // 정점을 덮은 옷 메시 비트
  const seen = new Int32Array(occ.n).fill(-1);
  const len = RAY_IN + RAY_OUT;
  for (let i = 0; i < n; i++) {
    if (cut && cut[i]) { by[i] = -1; continue; }
    if (!occ.n) continue;
    const dx = nrm[i * 3], dy = nrm[i * 3 + 1], dz = nrm[i * 3 + 2];
    const ox = pos[i * 3] - dx * RAY_IN, oy = pos[i * 3 + 1] - dy * RAY_IN, oz = pos[i * 3 + 2] - dz * RAY_IN;
    let m = 0;
    for (let s = 0; s <= len + 1e-9; s += CELL / 2) {
      const l = occ.grid.get(key(Math.floor((ox + dx * s) / CELL), Math.floor((oy + dy * s) / CELL), Math.floor((oz + dz * s) / CELL)));
      if (!l) continue;
      for (const t of l) {
        if (seen[t] === i || (m & occ.bit[t])) continue;
        seen[t] = i;
        if (hit(occ.T, t, ox, oy, oz, dx, dy, dz, len)) m |= occ.bit[t];
      }
    }
    by[i] = m;
  }
  keepTriangles(b, (a, bb, c) => (by[a] & by[bb] & by[c]) !== 0);
}

const CUT_EPS = 0.003;   // 판 면에서 이만큼(m) 너머부터 숨긴다

/** 판 정점(월드 P·법선 N) → {c: 가운데, d: 면 법선}. 면은 서로 먼 세 점으로 잡고, 방향은 정점 법선의 합(그 옷이 덮는 쪽)에 맞춘다. 점이 모자라거나 한 줄이면 null. */
function ringPlane(P, N) {
  const n = P.length / 3;
  if (n < 3) return null;
  const c = [0, 0, 0];
  for (let i = 0; i < n; i++) for (let k = 0; k < 3; k++) c[k] += P[i * 3 + k] / n;
  const at = (i) => [P[i * 3], P[i * 3 + 1], P[i * 3 + 2]];
  const sub = (a, q) => [a[0] - q[0], a[1] - q[1], a[2] - q[2]];
  const len2 = (a) => a[0] * a[0] + a[1] * a[1] + a[2] * a[2];
  const cross = (a, q) => [a[1] * q[2] - a[2] * q[1], a[2] * q[0] - a[0] * q[2], a[0] * q[1] - a[1] * q[0]];
  const p0 = at(0);
  let p1 = p0, best = 0;
  for (let i = 1; i < n; i++) { const l = len2(sub(at(i), p0)); if (l > best) { best = l; p1 = at(i); } }
  const e = sub(p1, p0);
  let d = null;
  best = 0;
  for (let i = 1; i < n; i++) { const x = cross(e, sub(at(i), p0)), l = len2(x); if (l > best) { best = l; d = x; } }
  if (!d || best < 1e-12) return null;
  const l = Math.sqrt(best);
  d = d.map((v) => v / l);
  const toward = [0, 0, 0];
  for (let i = 0; i < N.length; i++) toward[i % 3] += N[i];
  if (toward[0] * d[0] + toward[1] * d[1] + toward[2] * d[2] < 0) d = d.map((v) => -v);
  return { c, d };
}

/** 신발 모델의 가장 낮은 곳이 바닥(0)보다 얼마나 내려갔나 (m, 띄울 높이 — 안 내려가면 0). 뼈대 루트는 0 에 두고 잰다. */
export function soleLift(model) {
  let low = Infinity;
  for (const o of model.meshes) {
    if (!o.visible) continue;
    const P = bakePose(o).P;
    for (let i = 1; i < P.length; i += 3) if (P[i] < low) low = P[i];
  }
  return Number.isFinite(low) && low < 0 ? -low : 0;
}
