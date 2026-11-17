// 표정 키 — 표정 짝 클립에 딸린 얼굴 재질·눈 메시 보이기·눈꺼풀 모프 (mabi/dress/xaf.py 가 프레임마다 편 값).
// 뼈 클립(anim.js Clip)과 같은 시간으로 돈다. 값은 열쇠(아래)로 한 Map 에 모아 얼굴 모델에 얹는다 (viewer.js Model.setFace).
//   Mesh_Skin_Head/_MouthShowType                     0.5 넘으면 입을 표정 표 칸으로 (아니면 평소 입)
//   Mesh_Skin_Head/_EmotionMouthMapAtlasSize.z·w      입 표 칸(1부터)·회전°
//   Mesh_Skin_Head/_EmotionMouthMapScalePosition.x~w  입 칸 크기·자리
//   Mesh_EyeBall/_BaseMapAtlasSize.z                  눈동자 표 칸
//   Mesh_EyeBasePlane/_EyeballIndexFromOne            표정 눈 그림 칸 (4×8, 1부터)
//   <메시>/Visibility                                 0.5 넘으면 보인다 (표정 눈 판을 켜고 보통 눈을 끈다)
//   morph/<모프>                                      눈꺼풀 모프 0~1

/** 프레임 사이를 섞지 않는 값 (그림 칸·입 켜기 — 섞으면 사이 칸이 한 번 비친다). 보이기도 그렇다. */
const STEP = new Set(['_MouthShowType', '_EmotionMouthMapAtlasSize.z', '_BaseMapAtlasSize.z', '_EyeballIndexFromOne']);

export const MOUTH = 'Mesh_Skin_Head/';
export const IRIS_CELL = 'Mesh_EyeBall/_BaseMapAtlasSize.z';
export const EYE_CELL = 'Mesh_EyeBasePlane/_EyeballIndexFromOne';
export const MORPH = 'morph/';
export const VIS = '/Visibility';

export class FaceKeys {
  constructor(d) {
    this.fps = d.fps || 30;
    this.frames = d.frames || 1;
    this.tracks = (d.tracks || []).map((t) => ({
      key: t.t === 'morph' ? MORPH + t.p : t.o + '/' + t.p,
      step: t.t === 'vis' || STEP.has(t.p),
      v: t.v,
    }));
  }

  /** time(초) 값을 out(Map)에 — loop 면 반복, 아니면 끝 값에서 멈춘다 (anim.js Clip.apply 와 같은 시간 셈). */
  sample(time, loop, out) {
    const last = this.frames - 1;
    const f = last <= 0 ? 0 : loop ? (Math.max(time, 0) * this.fps) % last : Math.min(Math.max(time, 0) * this.fps, last);
    const i0 = Math.floor(f), a = f - i0;
    for (const t of this.tracks) {
      const v = t.v, n = v.length;
      const x0 = v[Math.min(i0, n - 1)];
      out.set(t.key, t.step || n === 1 ? x0 : x0 + (v[Math.min(i0 + 1, n - 1)] - x0) * a);
    }
    return out;
  }
}

/** 눈꺼풀 모프를 정하나 — 그동안 저절로 깜빡이기(life.js)는 쉰다. */
export function hasMorph(vals) {
  if (!vals) return false;
  for (const k of vals.keys()) if (k.startsWith(MORPH)) return true;
  return false;
}
