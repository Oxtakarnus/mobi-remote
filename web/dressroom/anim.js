// 동작 재생 — mabi/dress/anim.py 가 프레임마다 뽑아 둔 뼈 트랙(위치·회전·크기)을 공용 뼈대에 얹는다.

/** 회전 키 둘 사이 (d 의 p0·p1 에서 x,y,z,w) → out. 게임 곡선에서 뽑은 키는 길이가 정확히 1 이 아니어서
 *  three.js slerp 는 작은 각(내적 ≥ 1)을 같은 값으로 보고 건너뛴다 — 그러면 그 뼈만 키마다 계단(30fps)으로 움직여
 *  옆 뼈와 엇갈려 몸이 떨린다. 작은 각은 정규화 선형 보간, 큰 각은 slerp, 끝에 길이를 1 로. */
export function lerpQuat(out, d, p0, p1, a) {
  const x0 = d[p0], y0 = d[p0 + 1], z0 = d[p0 + 2], w0 = d[p0 + 3];
  let x1 = d[p1], y1 = d[p1 + 1], z1 = d[p1 + 2], w1 = d[p1 + 3];
  let dot = x0 * x1 + y0 * y1 + z0 * z1 + w0 * w1;
  if (dot < 0) { x1 = -x1; y1 = -y1; z1 = -z1; w1 = -w1; dot = -dot; }
  let k0 = 1 - a, k1 = a;
  const c = dot / (Math.hypot(x0, y0, z0, w0) * Math.hypot(x1, y1, z1, w1) || 1);
  if (c < 0.9995) {
    const th = Math.acos(Math.min(1, c)), sn = Math.sin(th);
    k0 = Math.sin((1 - a) * th) / sn;
    k1 = Math.sin(a * th) / sn;
  }
  return out.set(x0 * k0 + x1 * k1, y0 * k0 + y1 * k1, z0 * k0 + z1 * k1, w0 * k0 + w1 * k1).normalize();
}

export class Clip {
  constructor(meta, bin) {
    this.fps = meta.fps;
    this.frames = meta.frames;
    this.duration = meta.duration;
    this.tracks = meta.tracks.map((t) => {
      const w = t.kind === 'r' ? 4 : 3;
      return { path: t.path, kind: t.kind, n: t.n, w, data: new Float32Array(bin, t.off, t.n * w), rig: null, bone: null };
    });
  }

  /** 한 바퀴 길이(초) — 반복할 때 마지막 프레임이 첫 프레임에 이어진다. */
  get length() {
    return Math.max(0, this.frames - 1) / this.fps;
  }

  /** time(초) 자세를 뼈대에 — loop 면 반복, 아니면 끝 자세에서 멈춘다. */
  apply(rig, time, loop = true) {
    const last = this.frames - 1;
    const f = last <= 0 ? 0 : loop ? (time * this.fps) % last : Math.min(Math.max(time, 0) * this.fps, last);
    const i0 = Math.floor(f), a = f - i0;
    for (const t of this.tracks) {
      if (t.rig !== rig) { t.rig = rig; t.bone = rig.bones.get(t.path) || null; }
      const b = t.bone;
      if (!b) continue;
      const d = t.data, w = t.w;
      const p0 = t.n === 1 ? 0 : i0 * w;
      const p1 = t.n === 1 ? 0 : Math.min(i0 + 1, t.n - 1) * w;
      if (t.kind === 'r') {
        lerpQuat(b.quaternion, d, p0, p1, a);
      } else {
        const v = t.kind === 'p' ? b.position : b.scale;
        v.set(d[p0] + (d[p1] - d[p0]) * a, d[p0 + 1] + (d[p1 + 1] - d[p0 + 1]) * a, d[p0 + 2] + (d[p1 + 2] - d[p0 + 2]) * a);
      }
    }
  }
}

export async function loadClip(url) {
  const meta = await (await fetch(url)).json();
  const dir = url.slice(0, url.lastIndexOf('/') + 1);
  const bin = await (await fetch(dir + meta.bin)).arrayBuffer();
  return new Clip(meta, bin);
}
