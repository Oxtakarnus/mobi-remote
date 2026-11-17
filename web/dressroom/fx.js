// 의상 이펙트 — 모델 json 의 fx (mabi/dress/fx.py) 를 파티클로 흉내 낸다.
//
// 트랙마다 FX prefab 하나를 뼈(이펙트 소켓)에 붙이고, prefab 의 파티클 시스템을 CPU 로 돌린다. 그릴 때는 시스템마다
// 정점을 월드 좌표로 다 계산해 한 메시로 그린다 (입자 수가 적어 셰이더 쪽 빌보드보다 단순하다).
// 좌표는 Unity 그대로 — 뼈 행렬에 뼈대 루트의 x 뒤집기가 들어 있어 위치·방향은 저절로 맞고, 카메라를 보는 사각형만
// 카메라 공간에서 펼친다 (뒤집기가 안 걸린다). 사각형 굴리기는 화면에서 시계 방향 (Unity 빌보드).
//
// 흉내 내는 것: 방출(초당·버스트)·모양(구·반구·원뿔·원뿔 부피·상자)·시작 값(수명·속도·크기·회전·색, 상수·두 값·곡선)·
// 중력·수명 동안 속도(+궤도·방사)·속도 제한·크기·회전·색·그림 칸 넘기기·사용자 값(디졸브)·로컬/월드 공간·미리 돌리기.
// 빼는 것: 하위 방출·속도 물려받기·소프트 파티클·거리 방출·충돌·정점 흔들기(vertexoffset 의 날갯짓).
// 반복하지 않는 시스템은 끝나면 다시 튼다 — 옷 이펙트 구간은 끝이 없다 (타임라인 IsInfinite).
//
// 셰이더는 게임 FX 셰이더(재질 값 이름)를 참고한 웹 드레스룸의 역산 식에 맞춰 근사한다 — default·vertexoffset·
// dissolve·fresnel·addnoise, 덧그리기의 horn(뿔 불꽃). vTex = (uv, 사용자 값 2개), vExtra = 다음 사용자 값 4개.
import * as THREE from './vendor/three.module.min.js';

const N = 16;   // 곡선 표본 칸 (mabi/dress/fx.py N)
const MAX_PARTS = 400;   // 시스템마다 입자 상한 (게임 값이 1000 이어도 화면에 그만큼 쌓이지 않는다)
const PREWARM_STEP = 1 / 20;

// ── 값 읽기 ──
function sample(arr, t) {
  const x = Math.min(1, Math.max(0, t)) * N, i = Math.min(N - 1, Math.floor(x)), f = x - i;
  return arr[i] + (arr[i + 1] - arr[i]) * f;
}

/** 곡선 값 — 상수 | [작은, 큰] | {c} | {c, c2}. t: 0~1 (수명·주기 비율), r: 입자마다 0~1 (두 값 사이). */
export function curve(v, t, r = 0) {
  if (v === undefined || v === null) return 0;
  if (typeof v === 'number') return v;
  if (Array.isArray(v)) return v[0] + (v[1] - v[0]) * r;
  const hi = sample(v.c, t);
  if (!v.c2) return hi;
  const lo = sample(v.c2, t);
  return lo + (hi - lo) * r;
}

function sampleColor(arr, t, out) {
  const x = Math.min(1, Math.max(0, t)) * N, i = Math.min(N - 1, Math.floor(x)), f = x - i;
  for (let k = 0; k < 4; k++) out[k] = arr[i][k] + (arr[i + 1][k] - arr[i][k]) * f;
  return out;
}

const _c2 = [0, 0, 0, 0];
/** 색 값 — [r,g,b,a] | {g} | {c: [작은, 큰]} | {g, g2} | {r: 그 안에서 아무 색}. out 에 넣는다. */
export function color(v, t, r, out) {
  if (!v) { out[0] = out[1] = out[2] = out[3] = 1; return out; }
  if (Array.isArray(v)) { for (let k = 0; k < 4; k++) out[k] = v[k]; return out; }
  if (v.r) return sampleColor(v.r, r, out);
  if (v.c) { for (let k = 0; k < 4; k++) out[k] = v.c[0][k] + (v.c[1][k] - v.c[0][k]) * r; return out; }
  sampleColor(v.g, t, out);
  if (v.g2) {
    sampleColor(v.g2, t, _c2);
    for (let k = 0; k < 4; k++) out[k] = _c2[k] + (out[k] - _c2[k]) * r;
  }
  return out;
}

/** 시드 고정 무작위 (mulberry32) — 같은 옷은 같은 모양으로 시작한다. */
export function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hash(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

// Unity BlendMode → three
const BLEND = [THREE.ZeroFactor, THREE.OneFactor, THREE.DstColorFactor, THREE.SrcColorFactor, THREE.OneMinusDstColorFactor,
  THREE.SrcAlphaFactor, THREE.OneMinusSrcColorFactor, THREE.DstAlphaFactor, THREE.OneMinusDstAlphaFactor,
  THREE.SrcAlphaSaturateFactor, THREE.OneMinusSrcAlphaFactor];
// 정점 흐름 (Unity ParticleSystemVertexStreams) 의 성분 수 — 0~3(위치·법선·접선·색)은 texcoord 에 싣지 않는다.
// UV(4) 가 texcoord0.xy, 그 뒤 흐름이 차례로 texcoord0.zw → texcoord1.xyzw 를 채운다
const STREAM_N = { 4: 2, 5: 2, 6: 2, 7: 2, 8: 1, 9: 1, 10: 3, 11: 1, 12: 1, 13: 2, 14: 3, 15: 1, 16: 3, 17: 1, 18: 3,
  19: 3, 20: 1, 21: 1, 22: 1, 23: 1, 24: 2, 25: 3, 26: 4, 27: 1, 28: 2, 29: 3, 30: 4,
  31: 1, 32: 2, 33: 3, 34: 4, 35: 1, 36: 2, 37: 3, 38: 4 };

// ── 셰이더 ──
const MAPS = ['_MainTex', '_NoiseTex', '_AddNoiseTex', '_AlphaTex', '_MaskTex', '_FlameNoiseMap'];
const COMMON = `
uniform float fxTime;
varying vec4 vTex;
varying vec4 vExtra;
varying vec4 vColor;
varying vec3 vWorld;
varying vec3 vNormal;
${MAPS.map((m) => `uniform sampler2D ${m}; uniform vec4 ${m}_ST; uniform float ${m}_sRGB;`).join('\n')}
vec4 fxSample(sampler2D map, vec2 uv, float srgb) {
  vec4 t = texture2D(map, uv);
  if (srgb > 0.5) t.rgb = mix(t.rgb / 12.92, pow((t.rgb + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), t.rgb));
  return t;
}
`;
const PARTICLE_VERT = `
attribute vec4 color4;
attribute vec2 tex2;
attribute vec4 extra;
varying vec4 vTex;
varying vec4 vExtra;
varying vec4 vColor;
varying vec3 vWorld;
varying vec3 vNormal;
void main() {
  vTex = vec4(uv, tex2);
  vExtra = extra;
  vColor = color4;
  vWorld = position;
  vNormal = normal;
  gl_Position = projectionMatrix * viewMatrix * vec4(position, 1.0);
}`;
const TIME = 'float fxTimeWrap = mod(fxTime, 1000.0);';
const BODY = {
  default: `
  vec4 m = fxSample(_MainTex, vTex.xy * _MainTex_ST.xy + _MainTex_ST.zw, _MainTex_sRGB);
  rgb = mix(m.rgb * vColor.rgb, vColor.rgb, _Use_G_Channel_Alpha) * _Intensity_Color;
  a = clamp(mix(m.a, m.g, _Use_G_Channel_Alpha) * _Intensity_Alpha * vColor.a * _Color.a, 0.0, 1.0) * clamp(_EffectAlpha, 0.0, 1.0);`,
  vertexoffset: `
  vec4 m = fxSample(_MainTex, vTex.xy * _MainTex_ST.xy + _MainTex_ST.zw, _MainTex_sRGB);
  vec3 tinted = mix(m.rgb * vColor.rgb, vColor.rgb, _Use_G_Channel_Alpha) * _Intensity_Color * _Color.rgb;
  rgb = mix(tinted, m.rgb * _Color.rgb * _Intensity_Color, _Use_VretexColor);
  a = clamp(mix(m.a, m.g, _Use_G_Channel_Alpha) * _Intensity_Alpha * vColor.a, 0.0, 1.0) * clamp(_EffectAlpha, 0.0, 1.0);`,
  dissolve: `
  ${TIME}
  vec2 centred = vTex.xy - 0.5;
  float radius = 2.0 * length(centred), turn = atan(centred.y, centred.x) * 0.159155;
  vec2 mainUv = mix(vTex.xy * _MainTex_ST.xy + _MainTex_ST.zw, vec2(_MainTex_ST.x * radius + _MainTex_ST.z, turn * _MainTex_ST.y + _MainTex_ST.w), _UVType);
  vec4 m = fxSample(_MainTex, mainUv, _MainTex_sRGB);
  vec2 flat_ = vTex.xy * _NoiseTex_ST.xy + _NoiseTex_ST.zw;
  flat_.y += flat_.x * _Twist;
  vec2 noiseUv = mix(flat_, vec2(_NoiseTex_ST.x * radius + _NoiseTex_ST.z, turn * _NoiseTex_ST.y + _NoiseTex_ST.w), _UVType)
    + fxTimeWrap * vec2(_Noise_X_Speed, _Noise_Y_Speed);
  float raw = mix(m.a, m.g, _Use_G_Channel_Alpha) * fxSample(_NoiseTex, noiseUv, _NoiseTex_sRGB).g - vTex.z;
  float ramp = mix(raw, mainUv.x, _ColorGradation);
  vec4 tint = mix(_SubColor, _MainColor, clamp((ramp + _Color_Offset) * _Color_Range, 0.0, 1.0));
  rgb = mix(m.rgb * vColor.rgb, vColor.rgb, _Use_G_Channel_Alpha) * tint.rgb * _Intensity_Color;
  rgb = mix(rgb, _LerpColor.rgb * _LerpColor_Intensity, clamp((ramp + _LerpColor_Offset) * _LerpColor_Range, 0.0, 1.0));
  a = clamp(raw / max(1.0 - vTex.z, 0.0001) * _Intensity_Alpha, 0.0, 1.0) * vColor.a * tint.a * clamp(_EffectAlpha, 0.0, 1.0);`,
  fresnel: `
  ${TIME}
  vec4 m = fxSample(_MainTex, vTex.xy * _MainTex_ST.xy + _MainTex_ST.zw + vec2(vTex.w, 0.0), _MainTex_sRGB);
  vec2 noiseUv = vTex.xy * _NoiseTex_ST.xy + _NoiseTex_ST.zw;
  noiseUv.y += noiseUv.x * _Twist;
  noiseUv += fxTimeWrap * vec2(_Noise_X_Speed, _Noise_Y_Speed);
  float facing = dot(normalize(vNormal), normalize(cameraPosition - vWorld));
  float edge = smoothstep(_RimMin, _RimMax, facing);
  edge = edge + _Fresnel_OneMinus * (1.0 - 2.0 * edge);
  float cut = clamp(vTex.z + _DefaultValues, 0.0, 1.0);
  float raw = mix(m.a, m.g, _Use_G_Channel_Alpha) * fxSample(_NoiseTex, noiseUv, _NoiseTex_sRGB).g
    * fxSample(_AlphaTex, vTex.xy * _AlphaTex_ST.xy + _AlphaTex_ST.zw, _AlphaTex_sRGB).g * edge - cut;
  vec4 tint = mix(_SubColor, _MainColor, clamp((mix(raw, vTex.x, _ColorGradation) + _Color_Offset) * _Color_Range, 0.0, 1.0));
  rgb = mix(m.rgb * vColor.rgb, vColor.rgb, _Use_G_Channel_Alpha) * _Intensity_Color * tint.rgb;
  a = clamp(raw / (1.0001 - cut) * _Intensity_Alpha, 0.0, 1.0) * vColor.a * tint.a * clamp(_EffectAlpha, 0.0, 1.0);`,
  addnoise: `
  ${TIME}
  vec2 sequence = vec2(_SequenceX, _SequenceY);
  vec2 addUv = vTex.xy * _AddNoiseTex_ST.xy + _AddNoiseTex_ST.zw;
  addUv.y += addUv.x * _Twist;
  float added = fxSample(_AddNoiseTex, fract(addUv * sequence) + fxTimeWrap * vec2(_AddNoise_X_Speed, _AddNoise_Y_Speed), _AddNoiseTex_sRGB).g;
  vec2 noiseUv = vTex.xy * _NoiseTex_ST.xy + _NoiseTex_ST.zw;
  noiseUv.y += noiseUv.x * _Twist;
  float warp = fxSample(_NoiseTex, fract(noiseUv * sequence) + fxTimeWrap * vec2(_Noise_X_Speed, _Noise_Y_Speed), _NoiseTex_sRGB).g + _Distortion_Offset;
  vec4 m = fxSample(_MainTex, vTex.xy * _MainTex_ST.xy + _MainTex_ST.zw + warp * vec2(_Distortion_X_Power, _Distortion_Y_Power) * clamp(vTex.w, 0.0, 1.0), _MainTex_sRGB);
  float cut = clamp(vTex.z + _DefaultValues, 0.0, 1.0);
  float raw = added * mix(m.a, m.g, _Use_G_Channel_Alpha) - cut;
  float ramp = mix(raw, fract(vTex.x * _SequenceX), _ColorGradation);
  vec4 tint = mix(_SubColor, _MainColor, clamp((ramp + _Color_Offset) * _Color_Range, 0.0, 1.0));
  rgb = mix(m.rgb * tint.rgb, tint.rgb, _Use_G_Channel_Alpha) * _Intensity_Color * vColor.rgb;
  rgb = mix(rgb, _LerpColor.rgb * _LerpColor_Intensity, clamp((ramp + _LerpColor_Offset) * _LerpColor_Range, 0.0, 1.0));
  a = clamp(raw / (1.0001 - cut) * _Intensity_Alpha, 0.0, 1.0) * tint.a * vColor.a * clamp(_EffectAlpha, 0.0, 1.0);`,
  horn: `
  vec4 flow = vExtra.xyxy * _FlameNoiseTiling + fxTime * _FlameNoiseSpeed;
  float warp = fxSample(_FlameNoiseMap, flow.xy, _FlameNoiseMap_sRGB).r * 2.0 - 1.0;
  float noise = fxSample(_FlameNoiseMap, flow.zw + warp * _FlameDistortionStrength, _FlameNoiseMap_sRGB).r;
  float body = smoothstep(_FlameAlphaThreshold - 0.5 * _FlameAlphaSoftness, _FlameAlphaThreshold + 0.5 * _FlameAlphaSoftness, noise) * _FlameAlphaIntensity;
  float facing = clamp(dot(normalize(vNormal), normalize(cameraPosition - vWorld)), 0.0, 1.0);
  body *= smoothstep(0.0, _FlameOuterEdgeFade, facing);
  float inside = smoothstep(_FlameInsideCenter - 0.5 * _FlameInsideSoftness, _FlameInsideCenter + 0.5 * _FlameInsideSoftness, facing);
  a = clamp(inside * (1.0 - body) + body, 0.0, 1.0);
  rgb = mix(_FlameColorTip.rgb, _FlameColorBase.rgb, inside);`,
};
// 뿔 불꽃 — 대상 메시를 스킨 그대로 그리고, 실루엣 쪽으로 화면에서 조금 부풀린다
const HORN_VERT = `
#include <common>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
uniform float _FlameWidth;
uniform float _FlameDepthPush;
uniform vec3 fxOrigin;
uniform float fxMirror;
varying vec4 vTex;
varying vec4 vExtra;
varying vec4 vColor;
varying vec3 vWorld;
varying vec3 vNormal;
void main() {
  #include <beginnormal_vertex>
  #include <morphnormal_vertex>
  #include <skinbase_vertex>
  #include <skinnormal_vertex>
  #include <begin_vertex>
  #include <morphtarget_vertex>
  #include <skinning_vertex>
  vec4 world = modelMatrix * vec4(transformed, 1.0);
  vNormal = normalize(mat3(modelMatrix) * objectNormal);
  world.xyz += normalize(world.xyz - cameraPosition) * _FlameDepthPush;
  vWorld = world.xyz;
  vec3 vn = normalize(mat3(viewMatrix) * vNormal);
  vec4 view = viewMatrix * world;
  view.xy += vn.xy * sqrt(max(1.0 - vn.z * vn.z, 0.0)) * _FlameWidth * 0.05;
  vTex = vec4(uv, 0.0, 0.0);
  vExtra = vec4((world.xy - fxOrigin.xy) * vec2(fxMirror, 1.0), 0.0, 0.0);
  vColor = vec4(1.0);
  gl_Position = projectionMatrix * view;
}`;
const FLOATS = ['_Use_G_Channel_Alpha', '_Intensity_Color', '_Intensity_Alpha', '_EffectAlpha', '_Use_VretexColor',
  '_UVType', '_Twist', '_Noise_X_Speed', '_Noise_Y_Speed', '_ColorGradation', '_Color_Offset', '_Color_Range',
  '_LerpColor_Offset', '_LerpColor_Range', '_LerpColor_Intensity', '_Fresnel_OneMinus', '_DefaultValues',
  '_RimMin', '_RimMax', '_SequenceX', '_SequenceY', '_AddNoise_X_Speed', '_AddNoise_Y_Speed',
  '_Distortion_Offset', '_Distortion_X_Power', '_Distortion_Y_Power',
  '_FlameDistortionStrength', '_FlameInsideCenter', '_FlameInsideSoftness', '_FlameOuterEdgeFade',
  '_FlameAlphaIntensity', '_FlameAlphaThreshold', '_FlameAlphaSoftness', '_FlameWidth', '_FlameDepthPush'];
const FLOAT_DEF = { _Intensity_Color: 1, _Intensity_Alpha: 1, _EffectAlpha: 1, _Color_Range: 1, _LerpColor_Intensity: 1,
  _RimMax: 1, _SequenceX: 1, _SequenceY: 1, _FlameAlphaIntensity: 1, _FlameAlphaThreshold: 0.5, _FlameAlphaSoftness: 0.5,
  _FlameInsideCenter: 0.95, _FlameInsideSoftness: 1, _FlameOuterEdgeFade: 1, _FlameWidth: 0.3 };
const COLORS = ['_Color', '_MainColor', '_SubColor', '_LerpColor', '_FlameColorBase', '_FlameColorTip', '_FlameNoiseTiling', '_FlameNoiseSpeed'];
// 색 값 중 색이 아닌 것 (그대로 싣는다)
const RAW_VEC = new Set(['_FlameNoiseTiling', '_FlameNoiseSpeed']);

let white = null;
function blank() {
  if (!white) {
    white = new THREE.DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1);
    white.needsUpdate = true;
  }
  return white;
}

export const fxTime = { value: 0 };   // 모든 이펙트 셰이더가 같이 쓰는 시각 (초)

/** 그릴 면 — Unity 컬링(0 끔·1 앞면 버림·2 뒷면 버림)을 이 그리기에서 본 면으로.
 *  메시 파티클은 방향 행렬에 x 뒤집기가 들어 있어 앞뒤가 바뀌고, 스킨 메시는 불러올 때 삼각형 순서를 이미 뒤집었다. */
function sideOf(cull, mode) {
  if (mode === 'quad' || !cull) return THREE.DoubleSide;
  const front = cull === 2;
  return (mode === 'mesh') === front ? THREE.BackSide : THREE.FrontSide;
}

/** 재질 값 → ShaderMaterial. tex(이름, 반복?) → 텍스처. mode: 'quad' 사각형 · 'mesh' 메시 파티클 · 'skin' 덧그리기(뿔). */
function makeMaterial(mat, tex, mode) {
  const skinned = mode === 'skin';
  const opaque = mat.blend[0] === 1 && mat.blend[1] === 0;   // 덮어 그리기 (FX_Opaque) — 깊이도 쓴다
  const kind = BODY[mat.kind] ? mat.kind : 'default';
  const uniforms = { fxTime };
  for (const k of FLOATS) uniforms[k] = { value: mat.f[k] ?? FLOAT_DEF[k] ?? 0 };
  for (const k of COLORS) {
    const c = mat.c[k] || [1, 1, 1, 1];
    // 재질 색은 sRGB 값 — 선형으로 (HDR 값은 1 을 넘는 그대로 늘린다)
    uniforms[k] = { value: new THREE.Vector4(...(RAW_VEC.has(k) ? c : c.slice(0, 3).map(toLinear).concat(c[3]))) };
  }
  for (const k of MAPS) {
    const t = mat.t[k];
    uniforms[k] = { value: t ? tex(t.tex, true) : blank() };   // 흐르는 잡음·시트 넘기기 — 0~1 밖도 반복해 짚는다
    uniforms[k + '_ST'] = { value: new THREE.Vector4(...(t ? t.st : [1, 1, 0, 0])) };
    uniforms[k + '_sRGB'] = { value: t && t.srgb ? 1 : 0 };
  }
  if (skinned) {
    uniforms.fxOrigin = { value: new THREE.Vector3() };
    uniforms.fxMirror = { value: -1 };
  }
  const decl = FLOATS.map((k) => `uniform float ${k};`).join('\n') + '\n' + COLORS.map((k) => `uniform vec4 ${k};`).join('\n');
  const m = new THREE.ShaderMaterial({
    uniforms,
    vertexShader: skinned ? HORN_VERT : PARTICLE_VERT,
    fragmentShader: `${COMMON}\n${decl}\nvoid main() {\n  vec3 rgb = vec3(0.0); float a = 1.0;\n${BODY[kind]}\n  gl_FragColor = vec4(rgb, a);\n  #include <colorspace_fragment>\n}`,
    transparent: !opaque,
    depthWrite: opaque,
    blending: THREE.CustomBlending,
    blendSrc: BLEND[mat.blend[0]] ?? THREE.SrcAlphaFactor,
    blendDst: BLEND[mat.blend[1]] ?? THREE.OneMinusSrcAlphaFactor,
    blendSrcAlpha: THREE.ZeroFactor,   // 캔버스 알파는 그대로 (페이지가 비쳐 보이지 않게)
    blendDstAlpha: THREE.OneFactor,
    side: sideOf(mat.cull, mode),
  });
  return m;
}

function toLinear(c) {
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

// ── 메시 ──
function builtinMesh(name) {
  const g = name === 'sphere' ? new THREE.SphereGeometry(0.5, 24, 16) : name === 'cube' ? new THREE.BoxGeometry(1, 1, 1)
    : name === 'cylinder' ? new THREE.CylinderGeometry(0.5, 0.5, 2, 24) : name === 'capsule' ? new THREE.CapsuleGeometry(0.5, 1, 8, 16)
      : name === 'plane' ? new THREE.PlaneGeometry(10, 10).rotateX(-Math.PI / 2) : new THREE.PlaneGeometry(1, 1);
  if (name === 'quad') g.rotateY(Math.PI);   // Unity 사각형은 -z 를 본다
  // 감김 방향은 Unity 메시와 같다 (법선 쪽에서 보아 반시계) — 뒤집지 않는다
  const out = { pos: Array.from(g.attributes.position.array), nrm: Array.from(g.attributes.normal.array),
    uv: Array.from(g.attributes.uv.array), idx: Array.from(g.index.array) };
  g.dispose();
  return out;
}

// ── 시스템 ──
const _v = new THREE.Vector3(), _w = new THREE.Vector3(), _a = new THREE.Vector3(), _b = new THREE.Vector3();
const _q = new THREE.Quaternion(), _e = new THREE.Euler(), _m4 = new THREE.Matrix4(), _o = new THREE.Matrix4();
const _col = [0, 0, 0, 0], _col2 = [0, 0, 0, 0];
const _vals = [0, 0, 0, 0, 0, 0];   // draw — 입자 하나의 tex2·extra 값
const ATTRS = ['position', 'normal', 'uv', 'color4', 'tex2', 'extra'];
const DEG2RAD = Math.PI / 180;
const _right = new THREE.Vector3(), _up = new THREE.Vector3(), _fwd = new THREE.Vector3(), _cam = new THREE.Vector3();
const _dir = new THREE.Vector3(), _sh = new THREE.Vector3(), _sr = new THREE.Vector3();   // 태어날 방향 · 모양 계산용
const QUAD = [[-0.5, -0.5, 0, 0], [0.5, -0.5, 1, 0], [0.5, 0.5, 1, 1], [-0.5, 0.5, 0, 1]];

class Particle {
  constructor() {
    this.p = new THREE.Vector3();    // 위치 (시뮬레이션 공간)
    this.v = new THREE.Vector3();    // 속도 (시작 속도 + 중력, 시뮬레이션 공간)
    this.vel = new THREE.Vector3();  // 이번 프레임 움직인 속도 (늘이기 사각형 방향)
    this.size = [1, 1, 1];
    this.rot = [0, 0, 0];
    this.color = [1, 1, 1, 1];
    this.r = new Float32Array(10);   // 입자마다 무작위 (곡선 두 값 사이 고르기)
    this.age = 0;
    this.life = 1;
    this.flip = [1, 1];
    this.spin = 1;                   // 회전 방향 뒤집기
  }
}

class FxSystem {
  constructor(def, material, mesh, random) {
    this.def = def;
    this.random = random;
    this.parts = [];
    this.pool = [];
    this.material = material;
    this.cap = 0;
    this.mesh = mesh;   // 메시 그리기의 메시 {pos, nrm, uv, idx} 또는 null (사각형)
    this.per = mesh ? mesh.pos.length / 3 : 4;
    this.perIdx = mesh ? mesh.idx.length : 6;
    this.geometry = new THREE.BufferGeometry();
    this.object = new THREE.Mesh(this.geometry, material);
    this.object.frustumCulled = false;
    this.object.renderOrder = 20;
    this.object.matrixAutoUpdate = false;
    this.W = new THREE.Matrix4();      // 시스템 월드 행렬 (이번 프레임)
    this.Wi = new THREE.Matrix4();
    this.W3 = new THREE.Matrix3();     // 그 회전·크기 부분 (입자마다 다시 구하지 않게 — place)
    this.Wi3 = new THREE.Matrix3();
    this.local = new THREE.Matrix4().fromArray(def.m);
    this.grow(8);
    this.reset();
  }

  grow(n) {
    n = Math.min(MAX_PARTS, Math.max(n, this.cap * 2));
    if (n <= this.cap) return;
    if (this.cap) this.geometry.dispose();   // 옛 GPU 버퍼를 내린다 (다음 그리기에서 새로 올린다)
    this.cap = n;
    const v = n * this.per, g = this.geometry;
    const attr = (name, k) => g.setAttribute(name, new THREE.BufferAttribute(new Float32Array(v * k), k).setUsage(THREE.DynamicDrawUsage));
    attr('position', 3);
    attr('normal', 3);
    attr('uv', 2);
    attr('color4', 4);
    attr('tex2', 2);
    attr('extra', 4);
    const idx = new Uint32Array(n * this.perIdx);
    for (let i = 0; i < n; i++) {
      const base = i * this.per;
      if (this.mesh) for (let k = 0; k < this.perIdx; k++) idx[i * this.perIdx + k] = base + this.mesh.idx[k];
      else idx.set([base, base + 1, base + 2, base, base + 2, base + 3], i * 6);
    }
    g.setIndex(new THREE.BufferAttribute(idx, 1));
    g.setDrawRange(0, 0);
  }

  /** 처음부터 다시 (방출 늦춤·미리 돌리기 포함). */
  reset() {
    for (const p of this.parts) this.pool.push(p);
    this.parts.length = 0;
    const d = this.def;
    this.t = -curve(d.delay, 0, this.random());
    this.acc = 0;
    this.cycle = 0;
    this.fired = (d.emit ? d.emit.bursts : []).map(() => 0);
    this.done = false;
    this.rateR = this.random();
  }

  get alive() {
    return !this.done || this.parts.length > 0;
  }

  /** 미리 돌리기 — 한 주기를 돌려 놓고 시작한다 (반복하는 시스템). */
  prewarm(W) {
    if (!this.def.prewarm || !this.def.loop) return;
    this.W.copy(W).multiply(this.local);
    this.Wi.copy(this.W).invert();
    this.W3.setFromMatrix4(this.W);
    this.Wi3.setFromMatrix4(this.Wi);
    for (let t = 0; t < this.def.dur; t += PREWARM_STEP) this.simulate(PREWARM_STEP);
  }

  /** 한 프레임 — W: FX 루트 월드 행렬. */
  step(dt, W) {
    this.W.copy(W).multiply(this.local);
    this.Wi.copy(this.W).invert();
    this.W3.setFromMatrix4(this.W);
    this.Wi3.setFromMatrix4(this.Wi);
    this.simulate(dt);
  }

  simulate(dt) {
    const d = this.def;
    this.t += dt;
    const dur = Math.max(1e-3, d.dur);
    if (this.t >= 0 && !this.done) {
      const cycle = d.loop ? Math.floor(this.t / dur) : 0;
      if (cycle !== this.cycle) {   // 주기가 넘어갔다 — 버스트 다시
        this.cycle = cycle;
        this.fired.fill(0);
      }
      const ct = d.loop ? this.t - cycle * dur : Math.min(this.t, dur);
      if (!d.loop && this.t > dur) this.done = true;
      if (d.emit) {
        this.acc += Math.max(0, curve(d.emit.rate, ct / dur, this.rateR)) * dt;
        while (this.acc >= 1) { this.acc -= 1; this.spawn(ct / dur); }
        const bursts = d.emit.bursts;
        for (let i = 0; i < bursts.length; i++) {
          const [time, count, cycles, interval, prob] = bursts[i];
          for (;;) {
            const k = this.fired[i];
            if ((cycles > 0 && k >= cycles) || time + k * Math.max(interval, 1e-3) > ct) break;
            this.fired[i]++;
            if (this.random() > prob) continue;
            const n = Math.round(curve(count, ct / dur, this.random()));
            for (let j = 0; j < n; j++) this.spawn(ct / dur);
          }
        }
      }
    }
    this.integrate(dt);
  }

  spawn(nt) {
    if (this.parts.length >= Math.min(this.def.max || MAX_PARTS, MAX_PARTS)) return;
    const d = this.def, R = this.random;
    const p = this.pool.pop() || new Particle();
    for (let i = 0; i < p.r.length; i++) p.r[i] = R();
    p.age = 0;
    p.life = Math.max(1e-3, curve(d.life, nt, p.r[0]));
    shapePoint(d.shape, R, p.p, _dir);
    p.v.copy(_dir).multiplyScalar(curve(d.speed, nt, p.r[1]));
    if (d.space === 1) {   // 월드 공간 — 태어난 자리·방향을 지금 월드로
      p.p.applyMatrix4(this.W);
      p.v.applyMatrix3(this.W3);
    }
    if (d.size3) for (let k = 0; k < 3; k++) p.size[k] = curve(d.size3[k], nt, p.r[2]);
    else p.size[0] = p.size[1] = p.size[2] = curve(d.size, nt, p.r[2]);
    p.spin = p.r[9] < (d.flipRot || 0) ? -1 : 1;
    if (d.rot3) for (let k = 0; k < 3; k++) p.rot[k] = curve(d.rot3[k], nt, p.r[3]) * p.spin;
    else { p.rot[0] = p.rot[1] = 0; p.rot[2] = curve(d.rot, nt, p.r[3]) * p.spin; }
    color(d.color, nt, p.r[4], p.color);
    const f = d.render.flip;
    p.flip[0] = p.r[8] < f[0] ? -1 : 1;
    p.flip[1] = R() < f[1] ? -1 : 1;
    this.parts.push(p);
  }

  integrate(dt) {
    const d = this.def;
    const g = curve(d.gravity, 0, 0);
    if (g) {   // 중력 (월드 아래) — 로컬 공간이면 시스템 기준으로
      _a.set(0, -9.81 * g * dt, 0);
      if (d.space !== 1) _a.applyMatrix3(this.Wi3);
    }
    for (let i = this.parts.length - 1; i >= 0; i--) {
      const p = this.parts[i];
      p.age += dt;
      if (p.age >= p.life) {
        this.pool.push(p);
        this.parts[i] = this.parts[this.parts.length - 1];
        this.parts.pop();
        continue;
      }
      const t = p.age / p.life;
      if (g) p.v.add(_a);
      if (d.limit) limit(d.limit, p, t, dt);
      p.vel.copy(p.v);
      const vo = d.vel;
      if (vo) {
        _b.set(curve(vo.x, t, p.r[5]), curve(vo.y, t, p.r[5]), curve(vo.z, t, p.r[5]));
        if (vo.world !== (d.space === 1)) _b.applyMatrix3((vo.world ? this.Wi3 : this.W3));
        p.vel.add(_b);
        const radial = curve(vo.radial, t, p.r[5]);
        if (radial) {
          _b.copy(p.p);
          if (d.space === 1) _b.applyMatrix4(this.Wi);
          if (_b.lengthSq() > 1e-12) {
            _b.normalize().multiplyScalar(radial);
            if (d.space === 1) _b.applyMatrix3(this.W3);
            p.vel.add(_b);
          }
        }
        if (vo.orb) orbit(vo, p, t, dt, d.space === 1 ? this : null);
        p.vel.multiplyScalar(curve(vo.mod ?? 1, t, p.r[5]));
      }
      p.p.addScaledVector(p.vel, dt);
      if (d.rotOL) {
        const ro = d.rotOL;
        p.rot[2] += curve(ro.z, t, p.r[6]) * dt * p.spin;
        if (ro.x !== undefined) { p.rot[0] += curve(ro.x, t, p.r[6]) * dt * p.spin; p.rot[1] += curve(ro.y, t, p.r[6]) * dt * p.spin; }
      }
    }
  }

  /** 정점 채우기 — camera: 지금 카메라, visible: 그리나. */
  draw(camera, visible) {
    const n = visible ? this.parts.length : 0;
    if (n > this.cap) this.grow(n);
    const g = this.geometry;
    if (!n) { g.setDrawRange(0, 0); return; }
    const d = this.def, r = d.render;
    const pos = g.attributes.position.array, nrm = g.attributes.normal.array, uv = g.attributes.uv.array;
    const col = g.attributes.color4.array, tex2 = g.attributes.tex2.array, extra = g.attributes.extra.array;
    camera.matrixWorld.extractBasis(_right, _up, _fwd);   // _fwd = 카메라 뒤쪽 (+z)
    _cam.setFromMatrixPosition(camera.matrixWorld);
    // 크기 배율 — 계층(0)·자기(1) 방식은 변환 크기를 따르고, 모양(2) 방식은 따르지 않는다
    const scale = d.scaling === 2 ? 1 : Math.cbrt(Math.abs(this.W.determinant())) || 1;
    const tanHalf = Math.tan(THREE.MathUtils.degToRad((camera.fov || 50) / 2));
    const uvm = d.uv;
    const tiles = uvm ? uvm.tiles : [1, 1];
    const values = _vals;
    for (let i = 0; i < n; i++) {
      const p = this.parts[i];
      const t = p.age / p.life;
      // 위치·크기·색
      _v.copy(p.p);
      if (d.space !== 1) _v.applyMatrix4(this.W);
      let sx = p.size[0], sy = p.size[1], sz = p.size[2];
      if (d.sizeOL) {
        const so = d.sizeOL, k = curve(so.x, t, p.r[7]);
        if (so.y !== undefined) { sx *= k; sy *= curve(so.y, t, p.r[7]); sz *= curve(so.z, t, p.r[7]); } else { sx *= k; sy *= k; sz *= k; }
      }
      sx *= scale; sy *= scale; sz *= scale;
      if (r.mode !== 4 && r.max > 0) {   // 화면 높이 비율 상한 (빌보드)
        const lim = r.max * 2 * Math.max(1e-3, _v.distanceTo(_cam)) * tanHalf;
        const big = Math.max(sx, sy);
        if (big > lim) { const k = lim / big; sx *= k; sy *= k; }
      }
      _col[0] = p.color[0]; _col[1] = p.color[1]; _col[2] = p.color[2]; _col[3] = p.color[3];
      if (d.colorOL) { color(d.colorOL, t, p.r[4], _col2); for (let k = 0; k < 4; k++) _col[k] *= _col2[k]; }
      for (let k = 0; k < 3; k++) _col[k] = toLinear(Math.min(1, Math.max(0, _col[k])));
      // 그림 칸
      let u0 = 0, v0 = 0, du = 1, dv = 1;
      if (uvm) {
        const cyc = (t * (uvm.cycles || 1)) % 1;
        let frame, row;
        if (uvm.type === 1) {   // 한 줄만
          row = uvm.rowMode === 0 ? uvm.row : Math.floor(p.r[7] * tiles[1]) % tiles[1];
          frame = Math.floor((curve(uvm.frame, cyc, p.r[7]) + curve(uvm.start, 0, p.r[8])) * tiles[0]) % tiles[0];
          frame += row * tiles[0];
        } else {
          const total = tiles[0] * tiles[1];
          frame = Math.floor((curve(uvm.frame, cyc, p.r[7]) + curve(uvm.start, 0, p.r[8])) * total) % total;
        }
        const cx = frame % tiles[0], cy = Math.floor(frame / tiles[0]);
        du = 1 / tiles[0]; dv = 1 / tiles[1];
        u0 = cx * du; v0 = 1 - (cy + 1) * dv;
      }
      streamValues(d, p, t, values, sx);
      const base = i * this.per;
      if (this.mesh) this.meshVerts(p, base, sx, sy, sz, pos, nrm, uv, u0, v0, du, dv);
      else this.quadVerts(p, base, sx, sy, pos, nrm, uv, u0, v0, du, dv);
      for (let k = 0; k < this.per; k++) {
        const o = base + k;
        col[o * 4] = _col[0]; col[o * 4 + 1] = _col[1]; col[o * 4 + 2] = _col[2]; col[o * 4 + 3] = _col[3];
        tex2[o * 2] = values[0]; tex2[o * 2 + 1] = values[1];
        extra[o * 4] = values[2]; extra[o * 4 + 1] = values[3]; extra[o * 4 + 2] = values[4]; extra[o * 4 + 3] = values[5];
      }
    }
    for (const k of ATTRS) g.attributes[k].needsUpdate = true;
    g.setDrawRange(0, n * this.perIdx);
  }

  quadVerts(p, base, sx, sy, pos, nrm, uv, u0, v0, du, dv) {
    const r = this.def.render;
    const piv = r.pivot;
    let ax, ay;   // 사각형의 가로·세로 축 (월드)
    if (r.mode === 1) {   // 늘이기 — U 는 움직임 방향(뒤로), V 는 가로
      _a.copy(p.vel);
      if (this.def.space !== 1) _a.applyMatrix3(this.W3);
      const speed = _a.length();
      if (speed < 1e-6) _a.set(0, 0, 1).applyMatrix3(this.W3);
      _a.normalize();
      _b.copy(_v).sub(_cam).cross(_a);   // 화면에 누운 가로 방향
      if (_b.lengthSq() < 1e-12) _b.copy(_right);
      _b.normalize();
      const len = sy * r.len + speed * r.vscale;
      for (let k = 0; k < 4; k++) {
        const q = QUAD[k], o = (base + k) * 3;
        const along = piv[1] * Math.abs(len) - (q[0] * p.flip[0] + 0.5) * len;
        const across = (q[1] * p.flip[1] + piv[0]) * sx;
        pos[o] = _v.x + _a.x * along + _b.x * across;
        pos[o + 1] = _v.y + _a.y * along + _b.y * across;
        pos[o + 2] = _v.z + _a.z * along + _b.z * across;
        this.quadUv(uv, base + k, q, u0, v0, du, dv);
        nrm[o] = _fwd.x; nrm[o + 1] = _fwd.y; nrm[o + 2] = _fwd.z;
      }
      return;
    }
    // Unity 축은 x 를 뒤집어 놓는다 (뼈대 루트와 같다). 굴리기는 Unity 축에서 반시계 = 화면에서 시계 방향
    let roll = p.rot[2];
    if (r.align === 1) { ax = _a.set(-1, 0, 0); ay = _b.set(0, 1, 0); }   // 월드
    else if (r.align === 2 || r.align === 4) {   // 로컬 — 시스템 축 (W 에 뒤집기가 들어 있다)
      const e = this.W3.elements;
      ax = _a.set(e[0], e[1], e[2]).normalize(); ay = _b.set(e[3], e[4], e[5]).normalize();
    } else if (r.align === 3) {   // 카메라 위치를 본다
      _w.copy(_cam).sub(_v).normalize();
      ax = _a.set(0, 1, 0).cross(_w);
      if (ax.lengthSq() < 1e-8) ax.copy(_right); else ax.normalize();
      ay = _b.copy(_w).cross(ax).normalize();
      roll = -roll;
    } else { ax = _a.copy(_right); ay = _b.copy(_up); roll = -roll; }   // 화면 — 굴리기는 화면에서 시계 방향
    if (r.mode === 2) { ax = _a.set(-1, 0, 0); ay = _b.set(0, 0, 1); roll = p.rot[2]; }   // 수평
    else if (r.mode === 3) { ay = _b.set(0, 1, 0); ax = _a.copy(_right).setY(0).normalize(); roll = 0; }   // 수직
    const c = Math.cos(roll), s = Math.sin(roll);
    for (let k = 0; k < 4; k++) {
      const q = QUAD[k], o = (base + k) * 3;
      const qx = (q[0] * p.flip[0] + piv[0]) * sx, qy = (q[1] * p.flip[1] + piv[1]) * sy;
      const x = qx * c - qy * s, y = qx * s + qy * c;
      pos[o] = _v.x + ax.x * x + ay.x * y;
      pos[o + 1] = _v.y + ax.y * x + ay.y * y;
      pos[o + 2] = _v.z + ax.z * x + ay.z * y;
      this.quadUv(uv, base + k, q, u0, v0, du, dv);
      nrm[o] = _fwd.x; nrm[o + 1] = _fwd.y; nrm[o + 2] = _fwd.z;
    }
  }

  /** 입자의 이번 움직임 방향 (화면 월드, 단위) → out. 멈춰 있으면 false. */
  velDir(p, out) {
    out.copy(p.vel);
    if (this.def.space !== 1) out.applyMatrix3(this.W3);
    if (out.lengthSq() < 1e-12) return false;
    out.normalize();
    return true;
  }

  quadUv(uv, i, q, u0, v0, du, dv) {
    uv[i * 2] = u0 + q[2] * du;
    uv[i * 2 + 1] = v0 + q[3] * dv;
  }

  meshVerts(p, base, sx, sy, sz, pos, nrm, uv, u0, v0, du, dv) {
    const r = this.def.render, mesh = this.mesh, piv = r.pivot;
    // 방향 축 O — Unity 축을 화면(three 월드)으로. 다 x 뒤집기가 든 축이다 (행렬식 -1, 그래서 앞뒤 면이 바뀐다)
    const O = _o;
    if (r.align === 4 && this.velDir(p, _a)) {   // 속도 방향 — +z 가 움직임
      _b.set(0, 1, 0);
      if (Math.abs(_a.y) > 0.999) _b.set(1, 0, 0);
      _w.crossVectors(_a, _b).normalize();          // x
      _b.crossVectors(_w, _a);                      // y
      O.makeBasis(_w, _b, _a);
    } else if (r.align === 0 || r.align === 3) {    // 화면 — Unity 카메라 축 (z 는 화면 안쪽)
      O.makeBasis(_right, _up, _w.copy(_fwd).negate());
    } else if (r.align === 1) {                     // 월드
      O.makeScale(-1, 1, 1);
    } else {                                        // 로컬 — 시스템 축 (크기만 빼고 뒤집기는 남는다)
      O.extractRotation(this.W);
    }
    // 입자 회전 (Unity 오일러 라디안, Z → X → Y)
    _e.set(p.rot[0], p.rot[1], p.rot[2], 'YXZ');
    _m4.makeRotationFromEuler(_e).premultiply(O);
    const R = _m4.elements;
    const n = mesh.pos.length / 3;
    for (let k = 0; k < n; k++) {
      const lx = (mesh.pos[k * 3] + piv[0]) * sx, ly = (mesh.pos[k * 3 + 1] + piv[1]) * sy, lz = (mesh.pos[k * 3 + 2] + piv[2]) * sz;
      const o = (base + k) * 3;
      pos[o] = _v.x + R[0] * lx + R[4] * ly + R[8] * lz;
      pos[o + 1] = _v.y + R[1] * lx + R[5] * ly + R[9] * lz;
      pos[o + 2] = _v.z + R[2] * lx + R[6] * ly + R[10] * lz;
      const nx = mesh.nrm[k * 3], ny = mesh.nrm[k * 3 + 1], nz = mesh.nrm[k * 3 + 2];
      nrm[o] = R[0] * nx + R[4] * ny + R[8] * nz;
      nrm[o + 1] = R[1] * nx + R[5] * ny + R[9] * nz;
      nrm[o + 2] = R[2] * nx + R[6] * ny + R[10] * nz;
      uv[(base + k) * 2] = u0 + mesh.uv[k * 2] * du;
      uv[(base + k) * 2 + 1] = v0 + mesh.uv[k * 2 + 1] * dv;
    }
  }

  dispose() {
    this.object.removeFromParent();
    this.geometry.dispose();
  }
}

const _cv = [0, 0, 0, 0];
/** 정점 흐름 → vTex.zw, vExtra.xyzw 에 실을 값 6개 (UV 뒤 칸). 쓰는 것만 채우고 나머지 흐름은 0. */
function streamValues(d, p, t, out, sx) {
  out.fill(0);
  const streams = d.streams;
  if (!streams || !streams.length) return;
  let at = -2;   // UV 가 texcoord0.xy (out 밖)
  for (const s of streams) {
    const n = STREAM_N[s] || 0;
    if (!n) continue;
    let vals = null;
    if (s >= 31 && s <= 38) {   // 사용자 값 1·2
      const cv = (d.custom || [])[s <= 34 ? 0 : 1];
      if (Array.isArray(cv)) { for (let k = 0; k < 4; k++) _cv[k] = cv[k] === undefined ? 0 : curve(cv[k], t, p.r[7]); vals = _cv; }
      else if (cv && cv.color) vals = color(cv.color, t, p.r[7], _cv);
    } else if (s === 20) { _cv[0] = p.vel.length(); vals = _cv; }
    else if (s === 12 || s === 13) { _cv[0] = _cv[1] = sx; vals = _cv; }
    else if (s === 21) { _cv[0] = t; vals = _cv; }
    else if (s === 22) { _cv[0] = 1 / p.life; vals = _cv; }
    for (let k = 0; k < n; k++, at++) if (at >= 0 && at < 6 && vals) out[at] = vals[k];
  }
}

const AXES = ['x', 'y', 'z'];
function limit(l, p, t, dt) {
  const damp = 1 - Math.pow(1 - Math.min(1, l.damp || 0), dt * 30);
  if (l.mag !== undefined) {
    const lim = curve(l.mag, t, p.r[7]), sp = p.v.length();
    if (sp > lim && sp > 1e-9) p.v.multiplyScalar((sp - (sp - lim) * damp) / sp);
    return;
  }
  for (const ax of AXES) {
    const lim = Math.abs(curve(l[ax], t, p.r[7])), v = p.v[ax];
    if (Math.abs(v) > lim) p.v[ax] = Math.sign(v) * (Math.abs(v) - (Math.abs(v) - lim) * damp);
  }
}

const _orb = new THREE.Vector3(), _off = new THREE.Vector3();
function orbit(vo, p, t, dt, sys) {
  _orb.set(curve(vo.orb[0], t, p.r[5]), curve(vo.orb[1], t, p.r[5]), curve(vo.orb[2], t, p.r[5]));
  const ang = _orb.length() * dt;
  if (ang < 1e-9) return;
  _off.set(curve(vo.off[0], t, p.r[5]), curve(vo.off[1], t, p.r[5]), curve(vo.off[2], t, p.r[5]));
  if (sys) p.p.applyMatrix4(sys.Wi);
  _q.setFromAxisAngle(_orb.normalize(), ang);
  p.p.sub(_off).applyQuaternion(_q).add(_off);
  if (sys) p.p.applyMatrix4(sys.W);
}

/** 모양에서 태어날 자리·방향 (시스템 로컬, Unity). */
function shapePoint(sh, R, pos, dir) {
  if (!sh) { pos.set(0, 0, 0); dir.set(0, 0, 1); return; }
  const r = sh.r, thick = sh.thick;
  const arc = THREE.MathUtils.degToRad(sh.arc || 360);
  switch (sh.type) {
    case 0: case 1: case 2: case 3: {   // 구·반구 (반구는 +z 쪽)
      randomUnit(R, dir);
      if (sh.type >= 2) dir.z = Math.abs(dir.z);
      const k = 1 - thick + thick * Math.cbrt(R());
      pos.copy(dir).multiplyScalar(r * k);
      break;
    }
    case 4: case 7: case 8: case 9: {   // 원뿔 (밑면에서) · 원뿔 부피
      const th = R() * arc, rho = r * (1 - thick + thick * Math.sqrt(R()));
      const ang = THREE.MathUtils.degToRad(sh.angle) * (r > 1e-6 ? rho / r : 0);
      pos.set(rho * Math.cos(th), rho * Math.sin(th), 0);
      dir.set(Math.sin(ang) * Math.cos(th), Math.sin(ang) * Math.sin(th), Math.cos(ang));
      if (sh.type >= 8) pos.addScaledVector(dir, sh.len * R() / Math.max(1e-3, Math.cos(ang)));
      break;
    }
    case 5: case 15: case 16:   // 상자 — 모양 크기가 상자
      pos.set(R() - 0.5, R() - 0.5, R() - 0.5);
      dir.set(0, 0, 1);
      break;
    case 10: case 11: {   // 원
      const th = R() * arc, rho = r * (1 - thick + thick * Math.sqrt(R()));
      pos.set(rho * Math.cos(th), rho * Math.sin(th), 0);
      dir.set(Math.cos(th), Math.sin(th), 0);
      break;
    }
    default:
      pos.set(0, 0, 0);
      dir.set(0, 0, 1);
  }
  pos.multiply(_sh.fromArray(sh.scale));
  _e.set(sh.rot[0] * DEG2RAD, sh.rot[1] * DEG2RAD, sh.rot[2] * DEG2RAD, 'YXZ');
  pos.applyEuler(_e).add(_sh.fromArray(sh.pos));
  dir.applyEuler(_e);
  if (sh.randDir) dir.lerp(randomUnit(R, _sr), sh.randDir).normalize();
  if (sh.sphDir) dir.lerp(_sh.copy(pos).normalize(), sh.sphDir).normalize();
  if (sh.randPos) pos.addScaledVector(randomUnit(R, _sr), sh.randPos * R());
}

function randomUnit(R, out) {
  const z = R() * 2 - 1, a = R() * Math.PI * 2, s = Math.sqrt(1 - z * z);
  return out.set(s * Math.cos(a), s * Math.sin(a), z);
}

// ── 덧그리기 (AdditiveRenderer) ──
class Overlay {
  constructor(def, model, tex) {
    this.def = def;
    this.material = makeMaterial(def.mat, tex, 'skin');
    this.pairs = [];   // [대상 메시, 덧그린 메시]
    for (const o of model.meshes) {
      if (!def.meshes.includes(o.name) || !o.isSkinnedMesh) continue;
      const m = new THREE.SkinnedMesh(o.geometry, this.material);
      m.bind(o.skeleton, o.bindMatrix);
      m.frustumCulled = false;
      m.renderOrder = 21;
      m.userData.noShadow = true;
      o.parent.add(m);
      this.pairs.push([o, m]);
    }
  }

  update(on) {
    for (const [o, m] of this.pairs) {
      // 모프는 대상 메시 것을 같이 쓴다 — 몸 셰이프는 옷을 입힌 뒤에 옮겨 심어(fit.js) 나중에 생긴다
      m.geometry = o.geometry;
      m.morphTargetInfluences = o.morphTargetInfluences;
      m.morphTargetDictionary = o.morphTargetDictionary;
      m.visible = on && o.visible;
      if (m.visible && o.skeleton.bones[0]) {
        o.skeleton.bones[0].getWorldPosition(this.material.uniforms.fxOrigin.value);
      }
    }
  }

  dispose() {
    for (const [, m] of this.pairs) m.removeFromParent();
    this.material.dispose();
  }
}

// ── 트랙 하나 = prefab 하나를 뼈에 ──
const _p = new THREE.Vector3(), _pos = new THREE.Vector3(), _s = new THREE.Vector3(), _rq = new THREE.Quaternion();
const _off3 = new THREE.Vector3();
class Track {
  constructor(def, prefab, mats, meshes, random) {
    this.def = def;
    this.systems = prefab.systems.map((s) => {
      const mesh = s.mesh !== undefined ? meshes[s.mesh] : null;
      return new FxSystem(s, mats(s.mat, mesh ? 'mesh' : 'quad'), mesh, random);
    });
    this.root = new THREE.Matrix4();
    this.local = new THREE.Matrix4().compose(_off3.fromArray(def.off), new THREE.Quaternion().fromArray(def.rot), new THREE.Vector3(1, 1, 1));
    this.bone = null;
    this.rbone = null;
    this.started = false;
  }

  /** 뼈 찾기 — 없으면 false (다른 옷이 소켓을 가져올 수 있어 나중에 다시 찾는다). */
  resolve(rig) {
    this.bone = this.def.bone ? rig.find(this.def.bone) : rig.root;
    this.rbone = this.def.rbone && this.def.turn ? rig.find(this.def.rbone) : rig.root;
    return !!(this.bone && this.rbone);
  }

  /** FX 루트 월드 행렬 — 자리는 bone, 돌기는 rbone(따르지 않으면 캐릭터 루트), 크기는 뒤집기만. */
  place(rig) {
    _pos.setFromMatrixPosition(this.bone.matrixWorld);
    this.rbone.matrixWorld.decompose(_p, _rq, _s);
    const sign = rig.root.matrixWorld.determinant() < 0 ? -1 : 1;
    // 뒤집힌 행렬을 decompose 하면 x 크기가 음수가 된다 — 돌기는 그대로 두고 뒤집기만 x 에 남긴다
    this.root.compose(_pos, _rq, _s.set(Math.sign(_s.x) || sign, 1, 1));
    this.root.multiply(this.local);
  }

  step(dt, rig) {
    this.place(rig);
    if (!this.started) {
      this.started = true;
      for (const s of this.systems) s.prewarm(this.root);
    }
    for (const s of this.systems) {
      s.step(dt, this.root);
      // 반복하지 않는 시스템은 제 길이가 지나고 입자가 다 지면 처음부터 — 옷 이펙트 구간은 끝이 없어(IsInfinite) 게임도 다시 튼다
      if (!s.alive) s.reset();
    }
  }

  draw(camera, on) {
    for (const s of this.systems) s.draw(camera, on);
  }

  dispose() {
    for (const s of this.systems) s.dispose();
  }
}

/** 모델 하나의 이펙트 — fx: 모델 json 의 fx, model: viewer Model (그 group 에 붙인다), tex(이름, 반복?) → 텍스처
 *  (잡은 텍스처는 부르는 쪽이 놓는다), seed: 같은 옷 여러 벌이 같은 무늬로 돌지 않게 섞는 값. */
export class FxPlayer {
  constructor(fx, model, tex, seed = '') {
    const random = rng(hash(model.id + seed));
    this.model = model;
    this.group = new THREE.Group();
    this.group.name = 'fx';
    this.mats = [];
    const cache = new Map();
    const mats = (m, mode) => {
      const key = mode + JSON.stringify(m);
      if (!cache.has(key)) {
        const mm = makeMaterial(m, tex, mode);
        cache.set(key, mm);
        this.mats.push(mm);
      }
      return cache.get(key);
    };
    this.tracks = fx.tracks.map((t) => {
      const pf = fx.prefabs[t.fx];
      const meshes = (pf.meshes || []).map((m) => (typeof m === 'string' ? builtinMesh(m) : m));
      return new Track(t, pf, mats, meshes, random);
    });
    for (const t of this.tracks) for (const s of t.systems) { s.object.userData.noShadow = true; this.group.add(s.object); }
    this.overlays = (fx.overlays || []).map((o) => new Overlay(o, model, tex));
    this.retry = 0;
    model.group.add(this.group);
  }

  /** 매 프레임 — 뼈 행렬이 이번 자세로 갱신된 뒤 부른다. */
  update(dt, rig, camera) {
    const shown = this.model.shown;
    const hood = this.model.hood === 'on';
    this.retry -= dt;
    for (const t of this.tracks) {
      const on = shown && (!t.def.hood || hood);
      if (!t.bone || !t.rbone) {
        if (this.retry > 0 || !t.resolve(rig)) { t.draw(camera, false); continue; }
      }
      if (!on) { t.draw(camera, false); continue; }
      t.step(dt, rig);
      t.draw(camera, true);
    }
    if (this.retry <= 0) this.retry = 1;
    for (const o of this.overlays) o.update(shown && (!o.def.hood || hood));
  }

  dispose() {
    for (const t of this.tracks) t.dispose();
    for (const o of this.overlays) o.dispose();
    for (const m of this.mats) m.dispose();
    this.group.removeFromParent();
  }
}
