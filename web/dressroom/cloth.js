// 옷·머리 흔들림 — 게임 Magica Cloth(1판) BoneCloth 의 설정·구속 자료(모델 json cloth, mabi/dress/cloth.py)로 흔드는 뼈를 움직인다.
// 값과 구속 짝(거리·뿌리 거리·회전 유지와 제한·삼각형 굽힘·파고들기 막기·부딪힘)은 게임 것을 그대로 쓰고,
// 계산식은 Magica 설정의 뜻에 맞춰 다시 짠 것이라 게임과 똑같지는 않다. 한 걸음 1/90초 (Magica 기본).
// 자료 중 굽힘의 쉼 각·방향과 파고들기 줄의 거리는 쓰지 않는다 — 굽힘은 이번 기본 자세의 각, 파고들기는 설정
// penetrationDistance 로 맞춘다 (자료의 값은 게임 쪽 계산 기준이라 이 식에 그대로 넣으면 어긋났다).
// 계산은 뼈대 루트 기준(모델 좌표 = Unity 좌표, 루트의 x 뒤집기 전)에서 하고, 루트가 움직이거나 돌면 그만큼
// 정점을 뒤에 남겨(worldMoveInfluence) 흔들리게 한다. 부르는 쪽은 자세(동작·시선 등)를 다 고친 뒤 update 를 부른다.
import * as THREE from './vendor/three.module.min.js';

export const STEP = 1 / 90;
const MAX_STEPS = 8;           // 한 프레임 최대 걸음 (느린 프레임에서 따라잡기 상한)
const DEG = Math.PI / 180;
const TELEPORT = 1;            // 한 프레임 루트 이동이 이보다 크면(모델 단위 m) 처음부터
const TELEPORT_ANGLE = 60 * DEG;
const BEND_EPS = 1e-5;         // 굽힘 각 기울기를 셀 때 점을 미는 양 (m)
const BEND_MAX = 0.5;          // 한 걸음에 고칠 굽힘 각 상한 (rad)

/** 설정 곡선 [시작, 끝, 끝 씀, 곡선, 곡선 씀] 을 깊이 t(0..1)에서 읽는다. 숫자면 그대로. */
export function curve(v, t) {
  if (!Array.isArray(v)) return v;
  const [a, b, useEnd, c, useCurve] = v;
  if (!useEnd) return a;
  let u = Math.min(1, Math.max(0, t));
  if (useCurve && c) {
    // 2차 베지어 (0,0)·(cx,cy)·(1,1) 의 x=t 에서 y — c>0 이면 앞에서 빨리, c<0 이면 늦게 바뀐다
    const cx = 0.5 - 0.5 * c, cy = 0.5 + 0.5 * c;
    const A = 1 - 2 * cx, B = 2 * cx;
    const s = Math.abs(A) < 1e-6 ? u / Math.max(B, 1e-6) : (-B + Math.sqrt(B * B + 4 * A * u)) / (2 * A);
    u = 2 * (1 - s) * s * cy + s * s;
  }
  return a + (b - a) * u;
}

const _v = new THREE.Vector3(), _w = new THREE.Vector3(), _a = new THREE.Vector3(), _b = new THREE.Vector3();
const _e = new THREE.Vector3(), _d = new THREE.Vector3(), _s = new THREE.Vector3();
const _q = new THREE.Quaternion(), _q2 = new THREE.Quaternion(), _qi = new THREE.Quaternion();
const _m = new THREE.Matrix4(), _m2 = new THREE.Matrix4(), _inv = new THREE.Matrix4();

/** 날개 a·b 가 모서리 e0-e1 둘레로 벌어진 각 (−π..π). */
function dihedral(P, a, b, e0, e1) {
  _e.subVectors(P[e1], P[e0]);
  const l = _e.length();
  if (l < 1e-9) return 0;
  _e.divideScalar(l);
  _a.subVectors(P[a], P[e0]);
  _a.addScaledVector(_e, -_a.dot(_e));
  _b.subVectors(P[b], P[e0]);
  _b.addScaledVector(_e, -_b.dot(_e));
  return Math.atan2(_v.crossVectors(_a, _b).dot(_e), _a.dot(_b));
}

function wrap(a) {
  while (a > Math.PI) a -= 2 * Math.PI;
  while (a < -Math.PI) a += 2 * Math.PI;
  return a;
}

/** 부딪힘 모양 하나 — {bone, t, r, s, kind, center, axis, length, r0, r1} (cloth.py collider), 붙을 뼈는 rig 에서. */
export class Collider {
  constructor(c, rig) {
    this.bone = rig.bones.get(c.bone) || null;
    this.local = new THREE.Matrix4().compose(new THREE.Vector3().fromArray(c.t || [0, 0, 0]),
      new THREE.Quaternion().fromArray(c.r || [0, 0, 0, 1]), new THREE.Vector3().fromArray(c.s || [1, 1, 1]));
    const ax = new THREE.Vector3(c.axis === 0 || c.axis == null ? 1 : 0, c.axis === 1 ? 1 : 0, c.axis === 2 ? 1 : 0);
    const len = c.kind === 'capsule' ? c.length || 0 : 0;
    this.l0 = new THREE.Vector3().fromArray(c.center || [0, 0, 0]).addScaledVector(ax, -len);   // r0 쪽
    this.l1 = new THREE.Vector3().fromArray(c.center || [0, 0, 0]).addScaledVector(ax, len);    // r1 쪽
    this.M = new THREE.Matrix4();   // 모델 좌표
    this.p0 = new THREE.Vector3();
    this.p1 = new THREE.Vector3();
    this.ra = c.r0 || 0;
    this.rb = c.r1 == null ? this.ra : c.r1;
    this.scale = 1;
  }

  /** 이번 자세의 모델 좌표 (inv = 뼈대 루트 월드 행렬의 역). */
  place(inv) {
    if (!this.bone) return;
    this.M.multiplyMatrices(inv, this.bone.matrixWorld).multiply(this.local);
    this.p0.copy(this.l0).applyMatrix4(this.M);
    this.p1.copy(this.l1).applyMatrix4(this.M);
    this.scale = this.M.getMaxScaleOnAxis();
  }

  /** 점 p(모델 좌표)를 반지름 r 만큼 밖으로 — 밀어낸 양을 out 에, 닿았으면 true. */
  push(out, p, r) {
    _d.subVectors(this.p1, this.p0);
    const dd = _d.lengthSq();
    const t = dd > 1e-12 ? Math.min(1, Math.max(0, _w.subVectors(p, this.p0).dot(_d) / dd)) : 0;
    _s.copy(this.p0).addScaledVector(_d, t);
    const min = (this.ra + (this.rb - this.ra) * t) * this.scale + r;
    out.subVectors(p, _s);
    const dist = out.length();
    if (dist >= min) return false;
    if (dist < 1e-9) out.set(0, 1, 0).multiplyScalar(min);
    else out.multiplyScalar(min / dist - 1);
    return true;
  }
}

/** 흔들림 팀 하나 (BoneCloth 하나) — 정점 = 뼈. */
export class ClothTeam {
  /** data: 모델 json cloth 의 팀 (mabi/dress/cloth.py 꼴 — 다른 프로그램이 만든 같은 꼴도 된다). rig: 공용 뼈대 (viewer.js Rig). */
  constructor(data, rig) {
    this.data = data;
    this.rig = rig;
    const n = (this.n = data.verts.length);
    this.bones = data.verts.map((p) => rig.bones.get(p) || null);
    this.ok = n > 0 && this.bones.every(Boolean);
    if (!this.ok) return;
    const P = data.params || {};
    const algo2 = P.algorithm === 1;
    const dep = data.depth || new Array(n).fill(0);
    const at = (k, t, def = 0) => (P[k] == null ? def : curve(P[k], t));
    const per = (fn) => Float64Array.from(dep, fn);
    this.move = Uint8Array.from(data.sel, (s) => (s === 1 ? 1 : 0));
    this.parent = data.parent || new Array(n).fill(-1);
    this.mass = per((t) => Math.max(1e-3, at('mass', t, 1)));
    this.radius = per((t) => at('radius', t, 0.02));
    this.drag = per((t) => (P.useDrag ? at('drag', t) : 0));
    this.maxVel = per((t) => (P.useMaxVelocity ? at('maxVelocity', t, 3) : Infinity));
    this.gravity = per((t) => (P.useGravity ? at('gravity', t) : 0));
    this.stiff = per((t) => at('structDistanceStiffness', t, 0.5));
    this.restore = per((t) => (P.useRestoreRotation ? at(algo2 ? 'restoreRotation2' : 'restoreRotation', t) : 0));
    this.clamp = per((t) => (P.useClampRotation ? at(algo2 ? 'clampRotationAngle2' : 'clampRotationAngle', t) * DEG : -1));
    this.bendK = per((t) => (P.useTriangleBend ? at(algo2 ? 'triangleBend2' : 'triangleBend', t) : 0));
    this.penD = per((t) => (P.usePenetration ? at('penetrationDistance', t) : -1));
    this.inertia = per((t) => at('worldMoveInfluence', t, 1));
    this.gdir = new THREE.Vector3().fromArray(P.gravityDirection || [0, 1, 0]);
    this.massInf = P.massInfluence ?? 0.5;
    this.kDist = P.restoreDistanceVelocityInfluence ?? 1;
    this.kClampD = P.clampDistanceVelocityInfluence ?? 1;
    this.kRot = (algo2 ? P.restoreRotationVelocityInfluence2 : P.restoreRotationVelocityInfluence) ?? 1;
    this.ratio = P.useClampDistanceRatio ? [P.clampDistanceMinRatio ?? 0, P.clampDistanceMaxRatio ?? Infinity] : null;
    this.friction = P.friction ?? 0;
    this.collide = !!P.useCollision;
    this.maxMove = P.maxMoveSpeed ?? Infinity;
    this.maxTurn = (P.maxRotationSpeed ?? Infinity) * DEG;
    this.colliders = (data.colliders || []).map((c) => (c ? new Collider(c, rig) : null));
    // 부모가 먼저 오는 순서
    const done = new Uint8Array(n), order = [];
    const visit = (i) => {
      if (done[i]) return;
      done[i] = 1;
      if (this.parent[i] >= 0) visit(this.parent[i]);
      order.push(i);
    };
    for (let i = 0; i < n; i++) visit(i);
    this.order = order;
    this.kids = Array.from({ length: n }, () => []);
    this.parent.forEach((p, i) => { if (p >= 0) this.kids[p].push(i); });
    const vecs = () => Array.from({ length: n }, () => new THREE.Vector3());
    const quats = () => Array.from({ length: n }, () => new THREE.Quaternion());
    this.pos = vecs(); this.old = vecs(); this.vel = vecs();
    this.base = vecs(); this.prev = vecs(); this.baseRot = quats(); this.prevRot = quats(); this.rot = quats();
    this.lp = vecs(); this.lq = quats(); this.ls = vecs();   // 뼈의 이번 기본 로컬 자세 (뼈 쓰기)
    this.model = Array.from({ length: n }, () => new THREE.Matrix4());   // 쓴 뼈의 모델 행렬
    this.hit = new Uint8Array(n);
    this.bendRest = new Float64Array((data.bend || []).length / 6 | 0);   // 굽힘 쉼 각 — 프레임마다 기본 자세에서 (readBase)
    this.bendIds = [0, 0, 0, 0];
    this.bendG = Array.from({ length: 4 }, () => new THREE.Vector3());   // 굽힘 각의 점마다 기울기
    this.g = new THREE.Vector3();
    this.rootPrev = new THREE.Matrix4();
    this.acc = 0;
    this.fresh = true;
  }

  /** 다음 update 를 처음처럼 (정점을 기본 자세에 두고 멈춤). */
  reset() { this.fresh = true; }

  /** 한 프레임 — 뼈대 행렬이 이번 자세로 갱신된 뒤 부른다 (rig.root.updateMatrixWorld). 흔드는 뼈의 로컬 자세를 바꾼다. */
  update(dt) {
    if (!this.ok) return;
    const rootW = this.rig.root.matrixWorld;
    _inv.copy(rootW).invert();
    this.readBase(_inv);
    this.readBendRest();
    for (const c of this.colliders) if (c) c.place(_inv);
    // 중력 — 월드 방향을 모델 좌표로 (루트가 돌거나 뒤집혀도 아래는 아래)
    this.g.copy(this.gdir).transformDirection(_inv);
    if (!this.fresh) this.carry(dt);
    this.rootPrev.copy(rootW);
    if (this.fresh) this.start();
    this.acc = Math.min(this.acc + Math.max(0, dt), STEP * MAX_STEPS);
    const steps = Math.floor(this.acc / STEP + 1e-9);
    this.acc -= steps * STEP;
    for (let k = 0; k < steps; k++) this.step((k + 1) / steps);
    for (let i = 0; i < this.n; i++) { this.prev[i].copy(this.base[i]); this.prevRot[i].copy(this.baseRot[i]); }
    this.write();
  }

  readBase(inv) {
    for (let i = 0; i < this.n; i++) {
      const b = this.bones[i];
      this.lp[i].copy(b.position); this.lq[i].copy(b.quaternion); this.ls[i].copy(b.scale);
      _m.multiplyMatrices(inv, b.matrixWorld).decompose(this.base[i], this.baseRot[i], _s);
    }
  }

  start() {
    for (let i = 0; i < this.n; i++) {
      this.pos[i].copy(this.base[i]); this.old[i].copy(this.base[i]); this.vel[i].set(0, 0, 0);
      this.prev[i].copy(this.base[i]); this.prevRot[i].copy(this.baseRot[i]); this.rot[i].copy(this.baseRot[i]);
    }
    this.acc = 0;
    this.fresh = false;
  }

  /** 루트가 움직인 만큼 움직이는 정점을 뒤에 남긴다 — D = 이번 루트⁻¹ × 지난 루트 (월드에 멈춘 점의 모델 좌표 이동). */
  carry(dt) {
    _m2.multiplyMatrices(_inv, this.rootPrev);
    _m2.decompose(_v, _q, _s);
    const move = _v.length(), turn = 2 * Math.acos(Math.min(1, Math.abs(_q.w)));
    if (move > TELEPORT || turn > TELEPORT_ANGLE) { this.fresh = true; return; }
    if (move < 1e-7 && turn < 1e-7) return;
    let lim = 1;   // 너무 빠른 이동·회전은 그 속도까지만 남긴다 (maxMoveSpeed·maxRotationSpeed)
    if (dt > 0 && move > this.maxMove * dt) lim = Math.min(lim, (this.maxMove * dt) / move);
    if (dt > 0 && turn > this.maxTurn * dt) lim = Math.min(lim, (this.maxTurn * dt) / turn);
    for (let i = 0; i < this.n; i++) {
      if (!this.move[i]) continue;
      const k = this.inertia[i] * lim;
      this.pos[i].lerp(_w.copy(this.pos[i]).applyMatrix4(_m2), k);
      this.old[i].lerp(_w.copy(this.old[i]).applyMatrix4(_m2), k);
    }
  }

  /** 고친 양 dx 를 정점 i 에 — 속도에는 k 만큼만 남긴다 (Magica 의 …VelocityInfluence). */
  fix(i, dx, k) {
    this.pos[i].add(dx);
    if (k !== 1) this.old[i].addScaledVector(dx, 1 - k);
  }

  step(f) {
    const { n, pos, old, vel, move } = this;
    for (const i of this.order) {
      if (!move[i]) {
        old[i].copy(pos[i]);
        pos[i].lerpVectors(this.prev[i], this.base[i], f);
        this.rot[i].slerpQuaternions(this.prevRot[i], this.baseRot[i], f);
        continue;
      }
      const v = vel[i];
      v.multiplyScalar(Math.max(0, 1 - this.drag[i]));
      v.addScaledVector(this.g, this.gravity[i] * STEP);
      const sp = v.length();
      if (sp > this.maxVel[i]) v.multiplyScalar(this.maxVel[i] / sp);
      old[i].copy(pos[i]);
      pos[i].addScaledVector(v, STEP);
      this.hit[i] = 0;
    }
    this.composite();
    this.distance();
    this.bend();
    this.clampDistance();
    if (this.collide) this.collision();
    this.penetration();
    for (let i = 0; i < n; i++) {
      if (!move[i]) continue;
      vel[i].subVectors(pos[i], old[i]).divideScalar(STEP);
      if (this.hit[i]) vel[i].multiplyScalar(Math.max(0, 1 - this.friction));
    }
    this.frames();
  }

  /** 회전 유지·제한 (알고리즘 2 CompositeRotation) — 부모 회전 기준 쉼 방향으로 restore 만큼 당기고 clamp 각 안으로. */
  composite() {
    const c = this.data.comp || [];
    for (let r = 0; r + 8 < c.length; r += 9) {
      const i = c[r], p = c[r + 1];
      if (!this.move[i]) continue;
      _a.set(c[r + 2], c[r + 3], c[r + 4]).applyQuaternion(this.rot[p]).normalize();   // 쉼 방향
      _b.subVectors(this.pos[i], this.pos[p]);
      const len = _b.length();
      if (len < 1e-9) continue;
      _b.divideScalar(len);
      if (this.restore[i] > 0) {
        _q.setFromUnitVectors(_b, _a);
        _qi.identity().slerp(_q, Math.min(1, this.restore[i]));
        _b.applyQuaternion(_qi);
      }
      const lim = this.clamp[i];
      if (lim >= 0) {
        const ang = _a.angleTo(_b);
        if (ang > lim) {
          _q.setFromUnitVectors(_a, _b);
          _qi.identity().slerp(_q, lim / ang);
          _b.copy(_a).applyQuaternion(_qi);
        }
      }
      _d.copy(this.pos[p]).addScaledVector(_b, len).sub(this.pos[i]);
      this.fix(i, _d, this.kRot);
    }
  }

  /** 거리 유지 — 정점 i 쪽에서 본 짝마다 (짝의 양쪽에 다 있다). 무게가 무거운 쪽이 덜 움직인다. */
  distance() {
    const c = this.data.struct || [], { pos, move, mass } = this;
    for (let r = 0; r + 2 < c.length; r += 3) {
      const i = c[r], j = c[r + 1], L = c[r + 2];
      if (!move[i]) continue;
      _d.subVectors(pos[j], pos[i]);
      const dist = _d.length();
      if (dist < 1e-9) continue;
      const w = move[j] ? 0.5 + (mass[j] / (mass[i] + mass[j]) - 0.5) * this.massInf : 1;
      _d.multiplyScalar(((dist - L) / dist) * this.stiff[i] * w);
      this.fix(i, _d, this.kDist);
    }
  }

  /** 삼각형 굽힘 — 모서리 둘레 날개 각을 기본 자세의 각으로 (굽힘 세기만큼). 네 점을 각의 기울기 방향으로
   *  무게(1/질량)만큼 옮긴다 (PBD — 기울기의 합이 0 이라 날개만 돌릴 때처럼 이웃 줄끼리 키워 가며 튀지 않는다).
   *  기울기는 수치로 (점마다 축 셋, BEND_EPS). */
  /** 굽힘 쉼 각 — 이번 프레임 기본 자세(base)의 날개 각 (한 프레임 동안 그대로라 걸음마다 다시 재지 않는다). */
  readBendRest() {
    const c = this.data.bend || [];
    for (let r = 0, j = 0; r + 5 < c.length; r += 6, j++) this.bendRest[j] = dihedral(this.base, c[r], c[r + 1], c[r + 2], c[r + 3]);
  }

  bend() {
    const c = this.data.bend || [], { pos, move, mass, bendG: g, bendIds: ids } = this;
    for (let r = 0, row = 0; r + 5 < c.length; r += 6, row++) {
      ids[0] = c[r]; ids[1] = c[r + 1]; ids[2] = c[r + 2]; ids[3] = c[r + 3];
      if (!move[ids[0]] && !move[ids[1]] && !move[ids[2]] && !move[ids[3]]) continue;
      const k = (this.bendK[ids[0]] + this.bendK[ids[1]]) / 2;
      if (k <= 0) continue;
      const [a, b, e0, e1] = ids;
      const phi = dihedral(pos, a, b, e0, e1);
      let C = wrap(phi - this.bendRest[row]);
      if (Math.abs(C) < 1e-6) continue;
      C = Math.max(-BEND_MAX, Math.min(BEND_MAX, C));
      let sum = 0;
      for (let j = 0; j < 4; j++) {
        const i = ids[j];
        g[j].set(0, 0, 0);
        if (!move[i]) continue;
        const p = pos[i];
        for (let ax = 0; ax < 3; ax++) {
          const v = p.getComponent(ax);
          p.setComponent(ax, v + BEND_EPS);
          g[j].setComponent(ax, wrap(dihedral(pos, a, b, e0, e1) - phi) / BEND_EPS);
          p.setComponent(ax, v);
        }
        sum += g[j].lengthSq() / mass[i];
      }
      if (sum < 1e-12) continue;
      const s = (-C * k) / sum;
      for (let j = 0; j < 4; j++) {
        const i = ids[j];
        if (move[i]) this.fix(i, _d.copy(g[j]).multiplyScalar(s / mass[i]), 1);
      }
    }
  }

  /** 뿌리 거리 제한 — 기본 길이의 [min, max] 배 안으로. */
  clampDistance() {
    if (!this.ratio) return;
    const c = this.data.root || [], [lo, hi] = this.ratio, { pos, move } = this;
    for (let r = 0; r + 2 < c.length; r += 3) {
      const i = c[r], o = c[r + 1], L = c[r + 2];
      if (!move[i]) continue;
      _d.subVectors(pos[i], pos[o]);
      const dist = _d.length();
      if (dist < 1e-9) continue;
      const want = Math.min(L * hi, Math.max(L * lo, dist));
      if (want === dist) continue;
      _d.multiplyScalar(want / dist - 1);
      this.fix(i, _d, this.kClampD);
    }
  }

  collision() {
    const { pos, move } = this;
    for (let i = 0; i < this.n; i++) {
      if (!move[i]) continue;
      for (const c of this.colliders) {
        if (!c || !c.bone) continue;
        if (c.push(_d, pos[i], this.radius[i])) { this.fix(i, _d, 1); this.hit[i] = 1; }
      }
    }
  }

  /** 파고들기 막기 — 콜라이더 기준 점 P0 에서 바깥 방향 D 로 penetrationDistance 보다 안쪽이면 밀어낸다
   *  (자료의 거리는 기본 자세에서의 그 값 — 2026-11-17 로스트 문스케이프 예복으로 맞춰 봄). */
  penetration() {
    const c = this.data.pen || [], { pos, move } = this;
    for (let r = 0; r + 8 < c.length; r += 9) {
      const i = c[r], col = this.colliders[c[r + 1]];
      const min = this.penD[i];
      if (!move[i] || min < 0 || !col || !col.bone) continue;
      _a.set(c[r + 2], c[r + 3], c[r + 4]).applyMatrix4(col.M);
      _b.set(c[r + 5], c[r + 6], c[r + 7]).transformDirection(col.M);
      const d = _w.subVectors(pos[i], _a).dot(_b);
      if (d >= min) continue;
      this.fix(i, _d.copy(_b).multiplyScalar(min - d), 1);
    }
  }

  /** 정점 회전 — 움직이는 정점은 부모 회전에 (부모→자기) 방향이 기본에서 바뀐 만큼을 더한다. */
  frames() {
    const { pos, move, parent, base, baseRot, rot } = this;
    for (const i of this.order) {
      const p = parent[i];
      if (!move[i] || p < 0) continue;
      _q.copy(baseRot[p]).invert();
      _a.subVectors(base[i], base[p]).applyQuaternion(_q).applyQuaternion(rot[p]);   // 쉼 방향 (지금 부모 기준)
      _b.subVectors(pos[i], pos[p]);
      if (_a.lengthSq() < 1e-18 || _b.lengthSq() < 1e-18) { rot[i].copy(rot[p]).multiply(_q).multiply(baseRot[i]); continue; }
      _q2.setFromUnitVectors(_a.normalize(), _b.normalize());
      rot[i].copy(_q2).multiply(rot[p]).multiply(_q).multiply(baseRot[i]);
    }
  }

  /** 뼈 쓰기 — 움직이는 뼈를 정점 위치로 옮기고 자식(들) 쪽을 가리키게 돌린다 (useLineAvarageRotation: 자식들 평균). */
  write() {
    const { bones, pos, move, kids, parent } = this;
    for (const i of this.order) {
      if (!move[i]) continue;
      const b = bones[i];
      const p = parent[i];
      // 부모 뼈의 모델 행렬 — 이 팀이 쓴 뼈면 쓴 값, 아니면 지금 행렬
      if (p >= 0 && move[p]) _m.copy(this.model[p]);
      else _m.multiplyMatrices(_inv, b.parent.matrixWorld);
      _m.decompose(_v, _q, _s);
      _q.multiply(this.lq[i]);   // 기본 로컬 회전을 얹은 모양
      const ks = kids[i];
      if (ks.length) {
        _qi.identity();
        let k = 0;
        for (const c of ks) {
          _a.copy(this.lp[c]).multiply(this.ls[i]).applyQuaternion(_q);
          _b.subVectors(pos[c], pos[i]);
          if (_a.lengthSq() < 1e-18 || _b.lengthSq() < 1e-18) continue;
          _q2.setFromUnitVectors(_a.normalize(), _b.normalize());
          _qi.slerp(_q2, 1 / ++k);
        }
        _q.premultiply(_qi);
      }
      this.model[i].compose(pos[i], _q, _s.multiply(this.ls[i]));
      // 로컬로 — 부모 모델 행렬의 역 × 이 뼈 모델 행렬
      _m2.copy(_m).invert().multiply(this.model[i]);
      _m2.decompose(b.position, b.quaternion, _w);
    }
  }
}

/** 한 뼈대의 흔들림 전부 — 모델 json cloth 팀들과 바깥에서 더한 팀. */
export class ClothSet {
  constructor() {
    this.extra = [];             // 바깥에서 더한 팀 [ClothTeam]
    this.byModel = new WeakMap();   // 모델 → {rig, teams} (그 모델 json cloth 로 만든 팀)
    this.teams = [];             // 지난 update 에서 돌린 팀 전부
  }

  /** 모델 하나의 팀 (아직 안 돌렸거나 흔들림이 없으면 []). */
  teamsOf(m) {
    const e = this.byModel.get(m);
    return e ? e.teams : [];
  }

  /** 팀 자료(cloth.py 꼴)를 바깥에서 더한다 — 돌려받은 것을 remove 에 주면 뺀다. */
  add(data, rig) {
    const t = new ClothTeam(data, rig);
    this.extra.push(t);
    return t;
  }

  remove(t) {
    this.extra = this.extra.filter((x) => x !== t);
  }

  /** models: 지금 그 뼈대에 붙은 모델 (viewer.js Model — meta.cloth 를 읽는다). 뼈대가 바뀐 팀은 새로 만든다. */
  update(dt, rig, models) {
    const teams = this.teams;
    teams.length = 0;
    for (const m of models) {
      const list = m && m.meta && m.meta.cloth;
      if (!list || !list.length) continue;
      let e = this.byModel.get(m);
      if (!e || e.rig !== rig) this.byModel.set(m, (e = { rig, teams: list.map((d) => new ClothTeam(d, rig)) }));
      for (const t of e.teams) teams.push(t);
    }
    if (this.extra.some((t) => t.rig !== rig)) this.extra = this.extra.filter((t) => t.rig === rig);
    for (const t of this.extra) teams.push(t);
    if (!teams.length) return 0;
    rig.root.updateMatrixWorld(true);
    for (const t of teams) t.update(dt);
    return teams.length;
  }

  /** 다음 걸음을 처음처럼 — models 를 주면 그 모델의 팀만 (무기를 꺼내고 넣어 뿌리가 옮겨 갈 때), 안 주면 전부. */
  reset(models = null) {
    if (!models) {
      for (const t of this.teams) t.reset();
      for (const t of this.extra) t.reset();
      return;
    }
    for (const m of models) for (const t of this.teamsOf(m)) t.reset();
  }
}
