// 손 IK — 감정 표현 타임라인 IKControl (mabi/dress/fx.py ik). 위팔·아래팔 두 마디를 돌려 손을 옮긴다 (손은 아래팔에
// 붙은 채 따라간다).
//   disp  target 뼈가 dest 뼈에 닿게 (마시멜로·빨대를 입에) — target 이 그 손에 딸린 뼈가 아니면 손바닥을 그만큼 옮긴다
//   ref   손바닥을 target 뼈에 (다른 손이 든 소품 손잡이를 잡는다)
// 무게는 구간 begin·end 안에서 fin·fout 초 동안 0 ↔ 1 (게임 곡선 대신 곧은 선). 뼈대 루트(거울 x -1) 안 공간에서 푼다.
import * as THREE from './vendor/three.module.min.js';

const inv = new THREE.Matrix4();
const m = new THREE.Matrix4();
const _p = new THREE.Vector3(), _s = new THREE.Vector3();
const A = new THREE.Vector3(), B = new THREE.Vector3(), C = new THREE.Vector3(), T = new THREE.Vector3();
const u = new THREE.Vector3(), v = new THREE.Vector3(), axis = new THREE.Vector3();
const goal = new THREE.Vector3(), off = new THREE.Vector3(), tmp = new THREE.Vector3();
const q = new THREE.Quaternion(), pq = new THREE.Quaternion();
const ROUNDS = 3;   // 손이 돌면 손바닥·소품 자리가 조금 어긋난다 — 몇 번 다시 맞춘다

/** 구간 k 의 시각 t 무게 (0~1). */
export function weight(k, t) {
  if (t === null || t < k.begin || t >= k.end) return 0;
  let w = 1;
  if (k.fin > 0) w = Math.min(w, (t - k.begin) / k.fin);
  if (k.fout > 0) w = Math.min(w, (k.end - t) / k.fout);
  return Math.max(0, Math.min(1, w));
}

/** 시각 t 에 켜진 손 IK 를 뼈대에 — 자세(동작·몸 조절)를 다 얹은 뒤. 다른 손이 잡을 소품을 먼저 옮기게 disp 부터. */
export function solveIk(rig, list, t) {
  const on = list.map((k) => [k, weight(k, t)]).filter(([, w]) => w > 0);
  if (!on.length) return;
  on.sort((x, y) => (x[0].mode === 'disp' ? 0 : 1) - (y[0].mode === 'disp' ? 0 : 1));
  rig.root.updateMatrixWorld(true);
  inv.copy(rig.root.matrixWorld).invert();
  for (const [k, w] of on) reach(rig, k, w);
}

function reach(rig, k, w) {
  const palm = rig.find(k.bone), target = rig.find(k.target), dest = k.dest ? rig.find(k.dest) : null;
  const hand = palm && palm.parent, fore = hand && hand.parent, upper = fore && fore.parent;
  if (!target || !upper || upper === rig.root || (k.mode === 'disp' && !dest)) return;
  // 움직일 것(moving)이 갈 자리(goal) — 손에 딸리지 않은 target 이면 손바닥을 같은 만큼 옮긴다
  let moving = k.mode === 'disp' ? target : palm;
  pos(moving, goal).lerp(pos(k.mode === 'disp' ? dest : target, tmp), w);
  if (!under(moving, hand)) {
    goal.sub(pos(moving, tmp)).add(pos(palm, tmp));
    moving = palm;
  }
  for (let i = 0; i < ROUNDS; i++) {
    off.copy(goal).sub(pos(moving, tmp));
    if (off.lengthSq() < 1e-8) break;
    twoBone(upper, fore, hand, pos(hand, T).add(off));
  }
}

/** 뼈 b 가 p 이거나 그 밑인가. */
function under(b, p) {
  for (let x = b; x; x = x.parent) if (x === p) return true;
  return false;
}

/** 뼈의 뼈대 루트 공간 자리. */
function pos(b, out) {
  return out.setFromMatrixPosition(b.matrixWorld).applyMatrix4(inv);
}

/** 뼈를 뼈대 루트 공간의 회전 r 만큼 더 돌리고 그 밑 행렬을 갱신한다. */
function turn(b, r) {
  if (b.parent && b.parent.isBone) {
    m.multiplyMatrices(inv, b.parent.matrixWorld).decompose(_p, pq, _s);
  } else {
    pq.identity();
  }
  b.quaternion.premultiply(pq.clone().invert().multiply(r).multiply(pq));
  b.updateMatrixWorld(true);
}

/** 위팔(upper)·아래팔(fore)을 돌려 손(hand) 뿌리를 goal 쪽으로 — 팔꿈치 각을 맞추고 위팔을 돌린다. */
function twoBone(upper, fore, hand, to) {
  pos(upper, A); pos(fore, B); pos(hand, C);
  const a = A.distanceTo(B), b = B.distanceTo(C);
  if (a < 1e-6 || b < 1e-6) return;
  const d = Math.min(Math.max(A.distanceTo(to), Math.abs(a - b) + 1e-5), a + b - 1e-5);
  u.subVectors(A, B);
  v.subVectors(C, B);
  axis.crossVectors(u, v);
  if (axis.lengthSq() < 1e-12) axis.crossVectors(u, tmp.subVectors(to, A));   // 곧게 편 팔 — 목표 쪽으로 굽힌다
  if (axis.lengthSq() < 1e-12) axis.crossVectors(u, tmp.set(0, 0, 1));
  if (axis.lengthSq() > 1e-12) {
    const want = Math.acos(Math.min(1, Math.max(-1, (a * a + b * b - d * d) / (2 * a * b))));
    turn(fore, q.setFromAxisAngle(axis.normalize(), want - u.angleTo(v)));
    pos(hand, C);
  }
  u.subVectors(C, A).normalize();
  v.subVectors(to, A).normalize();
  turn(upper, q.setFromUnitVectors(u, v));
}
