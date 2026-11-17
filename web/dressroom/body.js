// 몸 조절 — 체형(셰이프)·키에 따라 뼈 크기·위치를 바꾼다. 자료는 게임 BDC (mabi/dress/body.py, 'bdc:<체형>').
// 자료는 두 꼴이다: 드레스룸 캐시 것은 줄마다 age 가 있고 화면이 그 값으로 고른다. 기준 한 줄의 크기·체형만 담은 자료
// (다른 프로그램용)는 age 칸이 없다 — 그때는 셰이프·키만 보고 머리 모프는 늘 0.
// 방식은 참고한 웹 드레스룸 것을 따른다.
//   - 키 조절값 -1..0..1 은 Short → Medium → Tall 사이를 선형으로.
//   - 뼈 크기는 뼈 scale 로 주지 않는다(자식에게 물려주면 안 된다) — 스킨 메시 boneInverses 앞에 (목표/기준) 크기를 곱한다.
//     자료에 없는 뼈(손가락 끝·옷 뼈 등)는 부모 크기를 따른다.
//   - 위치: 자료에 있는 뼈는 목표 p × 부모 크기 − 휴식 p 를 더하고, 없는 뼈는 휴식 p × (부모 목표/부모 기준 − 1).
//     _COM 은 크기 비율만큼 위치를 늘리고, 발 최저 높이가 기본 자세와 같도록 올리고 내린다.
//   - 캐시 자료만: 머리 Adolescent 모프 무게 = |age − base_age| / |반대 끝 − base_age|.
import * as THREE from './vendor/three.module.min.js';

const lerp = (a, b, t) => a.map((x, i) => x + (b[i] - x) * t);
const ONE = [1, 1, 1];
const FEET = /^_[LR] (Foot|Toe0)$/;
const _v = new THREE.Vector3();

/** 줄을 고르는 값(캐시 자료만, 기준 한 줄 자료는 무시)·체형('Default'|'Thin'|'Fat'|'Muscular')·키 조절값(-1..1)
 *  → {age, body, bones{p,s}, cm, adolescent}. 기준 한 줄 자료면 age 는 null, adolescent 는 0. */
export function stateAt(d, age, body = 'Default', height = 0) {
  const rows = d.min_age != null;
  age = rows ? Math.max(d.min_age, Math.min(d.max_age, Math.round(Number(age) || d.base_age))) : null;
  const st = rows ? d.states.find((s) => s.age === age && s.body === body) || d.states.find((s) => s.age === age)
    : d.states.find((s) => s.body === body) || d.states.find((s) => s.body === 'Default');
  const h = Math.max(-1, Math.min(1, Number(height) || 0));
  const [a, b, t] = h <= 0 ? ['Short', 'Medium', h + 1] : ['Medium', 'Tall', h];
  const pa = st.points[a], pb = st.points[b];
  const bones = {};
  for (const [n, v] of Object.entries(pa.bones)) bones[n] = { p: lerp(v.p, pb.bones[n].p, t), s: lerp(v.s, pb.bones[n].s, t) };
  const [zero, full] = rows ? d.adolescent : [0, 0];
  return {
    age, body: st.body, bones,
    cm: pa.height_hint + (pb.height_hint - pa.height_hint) * t,
    adolescent: full === zero ? 0 : Math.abs(age - zero) / Math.abs(full - zero),
  };
}

export class BodyFit {
  constructor(rig, data) {
    this.rig = rig;
    this.data = data;
    this.ref = data.states.find((s) => (data.min_age == null || s.age === data.base_age) && s.body === 'Default').points.Medium.bones;
    this.state = null;
    this.ratio = new Map();    // Bone → [x,y,z] 목표/기준 크기
    this.offset = new Map();   // Bone → Vector3 (로컬 위치에 더할 값)
    this.com = null;           // {bone, k} — _COM 은 위치를 k 배 + 바닥 맞춤
    this.ground = 0;
  }

  get minAge() { return this.data.min_age; }
  get maxAge() { return this.data.max_age; }

  set(age, body, height) {
    this.state = stateAt(this.data, age, body, height);
    this.build();
  }

  /** 뼈마다 크기 비율·위치 보정을 다시 잰다 — 옷이 뼈를 보태면(rig.add) 다시 부른다. 끝나면 기본 자세(행렬 갱신)다. */
  build() {
    if (!this.state) return;
    const st = this.state.bones, ref = this.ref;
    this.ratio.clear();
    this.offset.clear();
    this.com = null;
    const walk = (bone, ps, prs) => {
      const n = bone.name;
      const s = st[n] ? st[n].s : ps, rs = ref[n] ? ref[n].s : prs;
      this.ratio.set(bone, s.map((v, i) => v / rs[i]));
      const rest = bone.userData.rest[0];
      if (n === '_COM' && st[n] && ref[n]) this.com = { bone, k: st[n].s[0] / ref[n].s[0] };
      else if (st[n] && ref[n]) this.offset.set(bone, new THREE.Vector3(...st[n].p.map((v, i) => v * ps[0] - rest.getComponent(i))));
      else if (ps[0] !== prs[0]) this.offset.set(bone, rest.clone().multiplyScalar(ps[0] / prs[0] - 1));
      for (const c of bone.children) if (c.isBone) walk(c, s, rs);
    };
    for (const c of this.rig.root.children) if (c.isBone) walk(c, ONE, ONE);
    this.ground = 0;
    const feet = [...this.rig.bones.values()].filter((b) => FEET.test(b.name));
    if (feet.length) {
      const low = () => {
        this.rig.root.updateMatrixWorld(true);
        return Math.min(...feet.map((b) => b.getWorldPosition(_v).y));
      };
      this.rig.rest(false);
      const y0 = low();
      this.apply();
      this.ground = y0 - low();
    }
    this.rig.rest();
  }

  /** 동작을 얹은 뒤(clip.apply 다음) — 위치 보정만 (회전·뼈 scale 은 그대로). */
  apply() {
    if (!this.state) return;
    for (const [b, o] of this.offset) b.position.add(o);
    if (this.com) {
      const p = this.com.bone.position;
      p.multiplyScalar(this.com.k);
      p.y += this.ground;
    }
  }

  /** 스킨 메시의 boneInverses 앞에 크기 비율을 곱한다. 처음 값은 메시에 기억해 두고 매번 거기서 다시 만든다. */
  skin(meshes) {
    for (const o of meshes) {
      if (!o.isSkinnedMesh) continue;
      const sk = o.skeleton;
      if (!o.userData.inv0) o.userData.inv0 = sk.boneInverses.map((m) => m.clone());
      sk.bones.forEach((b, i) => {
        const r = this.ratio.get(b) || ONE;
        sk.boneInverses[i].makeScale(r[0], r[1], r[2]).multiply(o.userData.inv0[i]);
      });
    }
  }
}
