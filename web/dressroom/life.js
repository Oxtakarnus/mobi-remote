// 살아 있는 움직임 — 카메라 쪽 보기(척추·목·머리·눈알 뼈를 나눠 돌림)와 눈 깜빡임.
// 값과 나누는 방식은 참고한 웹 드레스룸(게임 꾸미기 화면 설정 값으로 보임)을 따른다.
//   - 좌우는 뼈마다 한계 비율대로 나누고(척추·목 20°, 머리 40°, 눈 39°), 나머지를 눈이 맡는다.
//   - 위아래는 머리가 먼저(-19~28°), 남은 만큼 눈(±2°).
//   - 뼈는 자기 축으로 돌린다 — 바인드 자세에서 위(+y)·앞(+z)에 가장 가까운 축. 그래서 고개를 들어도 눈은 얼굴 따라 옆으로만 간다.
//   - 눈알 뼈는 눈 뒤 먼 곳(_EyeBall_Scale 거리)을 축으로 돈다 → 각도를 눈 반지름/그 거리 만큼 줄여야 눈동자가 흰자 안에 남는다.
//   - 카메라가 등 뒤(90° 넘게)로 가면 시선을 서서히 거둔다.
// 계산은 뼈대 루트의 x 뒤집기를 되돌린 Unity 공간에서 한다.
import * as THREE from './vendor/three.module.min.js';

const GAZE = {
  ease: 1.175,       // 이 시간(초)이면 목표를 거의 다 따라간다
  maxAngle: 90,      // 카메라가 이보다 뒤로 가면 시선을 거둔다 (돌아올 때는 2° 안쪽에서)
  fade: 0.4,         // 거두고 돌아오는 시간(초)
  eyeRadius: 0.02,   // 눈알 반지름(m)
  eyeRatio: 0.57,    // _EyeBall_Scale 뼈가 없을 때 쓰는 각도 비율
  eyeYaw: 39,
  eyePitch: [-2, 2],
  // [뼈, 좌우 한계°, 위아래 한계°(아래, 위)]
  bones: [['_Spine', 20, 0, 0], ['_Spine1', 20, 0, 0], ['_Neck', 20, 0, 0], ['_Head', 40, -19, 28]],
  eyes: ['_EyeBallRot_L', '_EyeBallRot_R'],
};
const BLINK = 0.16;         // 한 번 깜빡이는 시간(초)
const D = Math.PI / 180;
const UP = new THREE.Vector3(0, 1, 0);
const FWD = new THREE.Vector3(0, 0, 1);
const AXES = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]].map((a) => new THREE.Vector3(...a));
const _q = new THREE.Quaternion();
const _v = new THREE.Vector3();
const _hp = new THREE.Vector3();

const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));

/** 바인드 자세에서 뼈의 (Unity) 월드 회전. */
function bindQ(b) {
  const q = b.userData.rest[1].clone();
  for (let p = b.parent; p && p.isBone; p = p.parent) q.premultiply(p.userData.rest[1]);
  return q;
}

/** 뼈의 위·옆 축 (뼈 자기 좌표) — 바인드 자세에서 앞·위에 가장 가까운 축. 한 번 구해 둔다. */
function frame(b) {
  if (b.userData.gaze) return b.userData.gaze;
  const q = bindQ(b);
  const pick = (want, skip) => {
    let best = null, bd = -1;
    for (const a of AXES) {
      if (skip && Math.abs(a.dot(skip)) > 0.5) continue;
      const d = _v.copy(a).applyQuaternion(q).dot(want);
      if (Math.abs(d) > bd) { bd = Math.abs(d); best = a.clone().multiplyScalar(d < 0 ? -1 : 1); }
    }
    return best;
  };
  const forward = pick(FWD), up = pick(UP, forward);
  b.userData.gaze = { up, right: new THREE.Vector3().crossVectors(up, forward).normalize() };
  return b.userData.gaze;
}

/** 뼈를 자기 위축으로 yaw, 이어서 옆축으로 pitch(+ 가 위) 만큼 더 돌린다. */
function turn(b, yaw, pitch) {
  const f = frame(b);
  if (yaw) b.quaternion.multiply(_q.setFromAxisAngle(f.up, yaw));
  if (pitch) b.quaternion.multiply(_q.setFromAxisAngle(f.right, -pitch));
  b.quaternion.normalize();
}

/** 눈알 각도 비율 — 눈 반지름 / 눈알 뼈에서 눈까지 거리. 뼈대마다 한 번 (눈 모델이 늦게 붙으면 그때). */
function eyeRatio(rig) {
  if (rig.gazeEyeRatio != null) return rig.gazeEyeRatio;
  const s = rig.find('_EyeBall_Scale_L') || rig.find('_EyeBall_Scale_R');
  const len = s ? s.userData.rest[0].length() : 0;
  if (len <= 1e-4) return GAZE.eyeRatio;
  rig.gazeEyeRatio = clamp(GAZE.eyeRadius / len, 0, 1);
  return rig.gazeEyeRatio;
}

export class Life {
  constructor() {
    this.gaze = true;
    this.yaw = 0;
    this.pitch = 0;
    this.weight = 0;
    this.behind = false;
    this.started = false;
    this.blinkWait = 2;
    this.blinkAt = -1;
  }

  /** 동작을 얹은 다음, 그리기 전에 부른다. */
  update(dt, rig, camera, eye) {
    this._look(dt, rig, camera);
    this._blink(dt, eye);
  }

  _look(dt, rig, camera) {
    const head = rig.find('_Head');
    if (!head) return;
    head.updateWorldMatrix(true, false);   // 동작을 얹은 머리 위치 — 조상만 갱신, 나머지는 그리기가 한다
    _hp.setFromMatrixPosition(head.matrixWorld);
    const dx = -(camera.position.x - _hp.x), dy = camera.position.y - _hp.y, dz = camera.position.z - _hp.z;
    const ty = Math.atan2(dx, dz), tp = Math.atan2(dy, Math.hypot(dx, dz));
    const deg = Math.abs(ty) / D;
    if (deg > GAZE.maxAngle) this.behind = true;
    else if (deg < GAZE.maxAngle - 2) this.behind = false;
    const on = this.gaze && !this.behind;
    this.weight = clamp(this.weight + (on ? dt : -dt) / GAZE.fade, 0, 1);
    if (this.weight <= 1e-6) { this.started = false; return; }
    const max = GAZE.maxAngle * D;
    if (!this.started) {
      this.yaw = clamp(ty, -max, max);
      this.pitch = tp;
      this.started = true;
    } else if (!this.behind) {
      const k = dt > 0 ? 1 - Math.exp(-9.21 * dt / GAZE.ease) : 1;
      this.yaw = wrap(this.yaw + wrap(ty - this.yaw) * k);
      this.pitch += (tp - this.pitch) * k;
    }
    const w = this.weight;
    const total = GAZE.eyeYaw + GAZE.bones.reduce((a, x) => a + x[1], 0);
    let used = 0, left = this.pitch;
    for (const [name, ymax, pmin, pmax] of GAZE.bones) {
      const b = rig.find(name);
      if (!b) continue;
      const y = clamp(this.yaw * ymax / total, -ymax * D, ymax * D);
      const p = clamp(left, pmin * D, pmax * D);
      left -= p;
      used += y;
      turn(b, y * w, p * w);
    }
    const r = eyeRatio(rig);
    const ey = clamp((this.yaw - used) * w * r, -GAZE.eyeYaw * D, GAZE.eyeYaw * D);
    const ep = clamp(left * w * r, GAZE.eyePitch[0] * D, GAZE.eyePitch[1] * D);
    for (const name of GAZE.eyes) {
      const b = rig.find(name);
      if (b) turn(b, ey, ep);
    }
  }

  _blink(dt, eye) {
    if (!eye) return;
    if (this.blinkAt < 0) {
      this.blinkWait -= dt;
      if (this.blinkWait <= 0) this.blinkAt = 0;
      return;
    }
    this.blinkAt += dt;
    const h = BLINK / 2;
    let v = this.blinkAt < h ? this.blinkAt / h : 1 - (this.blinkAt - h) / h;
    if (this.blinkAt >= BLINK) {
      v = 0;
      this.blinkAt = -1;
      this.blinkWait = 2 + Math.random() * 3.5;
    }
    eye.setMorph('MT_BlinkDown_L', clamp(v, 0, 1));
    eye.setMorph('MT_BlinkDown_R', clamp(v, 0, 1));
  }
}
