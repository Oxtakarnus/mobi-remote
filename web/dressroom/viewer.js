// 드레스룸 3D 화면 — three.js. 모델 묶음(json+bin, mabi/dress/export.py)을 공용 뼈대(Rig)에 묶어 그린다.
//
// 좌표: 자료는 Unity 원래 값(왼손). 뼈대 루트에서 x 를 뒤집어 오른손으로 바꾼다. 메시는 SkinnedMesh 라
// 장면 루트에 두고(bindMatrix = 단위), 뼈 위치만으로 자리가 정해진다 — 옷마다 다른 바인드 포즈(몸 A·옷 T)도
// 같은 뼈대로 스키닝되어 맞는다.
//
// 염색 식 (DyeMap 채널값 raw, 0~1):
//   칸 무게  w = max(1 − 2·raw, 0), 1/128 아래는 0
//   고정색   hi = sRGB→선형(max(2·raw − 1, 0))
//   색       clamp(128/95 · (w.r·칸1 + w.g·칸2 + w.b·칸3) + hi)
// 128/95 는 밝기 0.742(원본 그림 192) 자리가 고른 색 그대로 나오게 하는 값이다.
// 표(아틀라스) 좌표 — 눈동자 _BaseMapAtlasSize, 입 _EmotionMouthMapAtlasSize: (가로 칸, 세로 칸, 1부터 센 칸 번호, 회전°).
// 데칼(꾸미기 입·문신)도 같은 식에 칸 하나(1,1,1,회전)로 넣는다 — 자리 값은 부품 모델의 BaseTexcoord.
//
// 명암: 게임 캐릭터 셰이더를 역산한 식(참고한 웹 드레스룸)을 옮겼다 — 월드 고정 빛 하나(LIGHT), 발→머리 높이로
// 하체만 빛 방향을 따르고 상체는 평평하게, 경계는 띠, 가장자리 실루엣 색. 피부는 외곽선 색, 눈은 거의 평면.
// 재질 값(_TintColor·_ShadingType·_FlatShadingAmount*·_CullType 등)은 머티리얼에서 그대로 읽는다.
import * as THREE from './vendor/three.module.min.js';
import { OrbitControls } from './vendor/OrbitControls.js';
import { eyeVisible, EYE_MESH } from './cover.js';
import { FxPlayer } from './fx.js';

const GAIN = 128 / 95;

const VERT = `
#include <common>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#ifdef MOUTH
attribute vec2 uvMouth;
varying vec2 vMouth;
#endif
varying vec2 vUv;
varying vec3 vWorld;
varying vec3 vWorldN;
#ifdef EMIT
varying vec3 vObj;
varying vec3 vObjN;
#endif
void main() {
  vUv = uv;
#ifdef MOUTH
  vMouth = uvMouth;
#endif
#ifdef EMIT
  vObj = position;
  vObjN = normalize(normal);
#endif
  #include <beginnormal_vertex>
  #include <skinbase_vertex>
  #include <skinnormal_vertex>
  #include <defaultnormal_vertex>
  #include <begin_vertex>
  #include <morphtarget_vertex>
  #include <skinning_vertex>
  #include <project_vertex>
  vWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;
  vWorldN = inverseTransformDirection(normalize(transformedNormal), viewMatrix);
}`;

const FRAG = `
uniform sampler2D map;
#ifdef BLEND
uniform vec4 alphaScale;   // 반투명 — (최소, 최대, _AlphaOverride, _EffectAlphaValue)
#endif
uniform int kind;          // 0 염색 · 1 그림 · 2 단색
uniform vec3 dye0, dye1, dye2, base;
#ifdef IRIS
uniform vec4 irisAtlas, irisST;
#endif
#ifdef MOUTH
uniform sampler2D mouthMap;
uniform vec4 mouthAtlas, mouthST;
uniform float mouthOn;   // 입 모양 덮어쓰기 중 (꾸미기 입 대신 표정 표 칸)
varying vec2 vMouth;
#endif
#ifdef LIPS
uniform sampler2D lipsMap;
uniform vec4 lipsAtlas, lipsST;
#endif
#ifdef TATTOO
uniform sampler2D tatMap;
uniform vec4 tatAtlas, tatST;
uniform vec3 tatColor;
uniform float tatDye, tatScar;
#endif
uniform vec3 tint, silhouetteTint, outlineTint, flatShading;   // flatShading = (위 몫, 아래 몫, 그림자 받는 세기)
uniform vec3 lightVector, directRGB, ambientRGB;               // 모든 재질이 같이 쓰는 빛
uniform float actorBase, actorHeadHeight, outlineOn, backDarken, shadingType;
#ifdef FEATURE
uniform vec4 featureParams;   // 금속·가죽 — (금속, 가죽, 매끈함, 실루엣 켬)
uniform vec3 skyTop, skyMiddle, skyBottom;   // 금속에 비치는 주변 (위·가운데·아래)
uniform vec4 skyPos;
#endif
#ifdef FRESNEL
uniform vec3 fresnelColor, fresnelParams;   // 가장자리 빛 — 색, (지수, 세기, 상한)
#endif
#ifdef EMIT
uniform sampler2D emitMap, emitNoise;
uniform vec3 emitColor, emitColorG, emitColorB;
uniform vec3 emitMode;    // (숨쉬기, 발광 그림이 sRGB, 잡음 그림이 sRGB)
uniform vec4 emitWave;    // (세기, 숨쉬기 최소 밝기, 주기 초, 잡음 흐름 속도)
uniform vec4 emitNoiseST;
uniform float emitTime, emitDay;   // emitDay: 밤에만 빛나는 몫을 끄면 0
varying vec3 vObj;
varying vec3 vObjN;
#endif
#ifdef STOCKING
uniform sampler2D stockMask;
uniform vec4 stockParams;   // (짙음 = (_Denier - 10) / 170, 무늬 마스크 씀, 점 반짝임 _PointColorSpecular, 마스크 sRGB)
#endif
#ifdef GEM
uniform sampler2D gemCap, gemInc;
uniform vec4 gemBase;      // (_GemBaseColorStrength, _GemBaseStrength, 내포물 그림 있음, 면 반사 그림 있음)
uniform vec3 gemReflect;   // (_GemBrightColorReflection, _GemDarkColorReflection, _GemReflectionGloss)
uniform vec3 gemCapParams; // (_GemMatCapBlend, _GemMatCapIntensity, _GemMatCapScale)
uniform vec4 gemTiling;    // (_GemInclusionMapTilingX·Y, 내포물 그림 sRGB, 면 반사 그림 sRGB)
#endif
varying vec2 vUv;
varying vec3 vWorld;
varying vec3 vWorldN;
const vec3 LUMA = vec3(0.212673, 0.715152, 0.072175);
vec3 toLinear(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(0.04045, c)); }
float sat(float x) { return clamp(x, 0.0, 1.0); }
vec3 sdir(vec3 p) { return p / max(length(p), 1e-5); }
// 카메라 쪽(뒤) 방향 — 화면을 향하는 면이 +
vec3 camBack() { return sdir(vec3(viewMatrix[0][2], viewMatrix[1][2], viewMatrix[2][2])); }
// 발(0) → 머리(1). 하체는 빛 방향을 따라 어둡고, 상체는 평평하게 밝다
float vertical() { return min(max(sat(((vWorld.y - actorBase) / actorHeadHeight + 0.05) * 0.85), flatShading.y), flatShading.x); }
vec3 rimDir(vec3 c, vec3 l) { vec3 f = l * vec3(1.0, 0.3, 1.0); return sdir(f - c * dot(f, c)); }
#ifdef FEATURE
// 금속 하이라이트 — 매끈할수록 작고 또렷하다 (_METAL_FEATURE 의 Blinn-Phong)
float metalHighlight(vec3 n, vec3 look, vec3 l, float strength, float rough) {
  if (strength <= 0.0) return 0.0;
  float peak = max(strength * pow(sat(dot(n, sdir(look + l))), strength * strength * 1024.0) * sat(dot(directRGB, LUMA)), 0.0);
  float low = 0.1 - 0.2 * rough;
  return strength * smoothstep(low, low + 0.3 + 0.4 * rough, peak);
}
// 금속에 비치는 주변 — 게임은 장소의 반사 프로브, 여기선 위·가운데·아래 세 색 하늘
vec3 skyProbe(vec3 ray) {
  float d = sdir(ray).y;
  float high = smoothstep(0.0, 1.0, sat((d - skyPos.z) / (skyPos.w - skyPos.z)));
  float low = smoothstep(0.0, 1.0, sat((d - skyPos.x) / (skyPos.y - skyPos.x)));
  return mix(skyBottom, mix(skyMiddle, skyTop, high * high), low);
}
#endif
// 옷·머리카락 — 게임 캐릭터 셰이더를 역산한 식 (참고한 웹 드레스룸).
// mask: 그림 알파 — 금속·가죽 재질은 알파가 낮은 곳이 금속·가죽 자리다
vec3 clothLight(vec3 albedo, vec3 n, float shadowed, float mask) {
  vec3 c = camBack(), l = normalize(lightVector), look = sdir(cameraPosition - vWorld);
  float h = vertical(), facing = dot(n, c), camLight = dot(c, l);
  float edge = sat(dot(sdir(n + c * 0.5), sdir(l * vec3(1.0, 0.26, 1.0))) * 30.0 + 6.0);
  float shade = 1.0 + flatShading.z * (shadowed - 1.0);
  edge *= shadingType < 0.5 ? max(shade, h * h) : shade;
  float band = max(0.2 * sat(1.0 - camLight), edge);
  float direct = mix(0.5 * dot(n, l) + 0.3, 1.0, h), gi = mix(facing + 0.15, facing * 0.65 + 0.5, h);
  if (shadingType < 0.5) band = 0.3 * h + band; else if (shadingType > 1.5) { direct *= 0.5; gi *= 0.5; }
#ifdef FEATURE
  float cutout = 1.0 - mask;
  if (featureParams.y > 0.5) {
    // 가죽 — 카메라 반사 쪽 넓은 하이라이트, 반구 채움은 줄이고 띠는 평평하게
    float strength = featureParams.z * cutout;
    float highlight = strength > 0.0 ? sat(4.0 * strength * pow(sat(dot(reflect(-c, n) * 1.1, l)), 13.0 * strength)) : 0.0;
    band = sat(mix(band, 0.5 * (edge + band), cutout));
    direct += cutout * highlight;
    gi = mix(gi, facing, cutout);
  }
#endif
  float back = gl_FrontFacing ? 1.0 : backDarken;
  vec3 light = clamp(clamp(directRGB * direct, 0.0, 1.0) * back * sat(band) + clamp(ambientRGB * gi, 0.0, 1.0), 0.0, 1.0);
  vec3 lit = albedo * back * light;
  float grazing = 1.0 - dot(n, look), rim = 0.0;
  vec3 tinted = vec3(0.0);
  if (gl_FrontFacing) {
    rim = sat(dot(n, rimDir(c, l))) * sat(10.0 * grazing - 6.0);
    tinted = (1.0 - dot(look, l)) * silhouetteTint * directRGB * (albedo * vec3(5.0, 5.0, 4.0) + vec3(0.05, 0.15, 0.25)) * 0.5;
  }
#ifdef FEATURE
  if (featureParams.x > 0.5) {
    // 금속 — 하이라이트와 주변 반사를 더하고, 밝은 금속은 눌러 대비를 준다. 실루엣 빛은 금속 자리에서 그림 색으로
    float strength = featureParams.z * cutout, rough = 1.0 - strength;
    vec3 probe = min(skyProbe(reflect(-look, n)), vec3(1.5));
    vec3 add = tint * (metalHighlight(n, look, l, strength, rough)
                       + 0.5 * cutout * probe * (0.5 + 4.5 * dot(albedo, LUMA)) * (0.2 + 0.05 * strength));
    vec3 rimLit = rim * featureParams.w * mix((rim * albedo + tinted) * tint, tinted, mask);
    vec3 base = lit + rimLit;
    vec3 metal = mix(add + base, base * (0.5 + add), dot(albedo * back, LUMA));
    lit = mix(metal, base + rimLit, mask);
  } else lit += rim * tinted;
#else
  lit += rim * tinted;
#endif
  lit = min(lit, vec3(1.5));
#ifdef FRESNEL
  vec3 glow = albedo * clamp(ambientRGB + directRGB, 0.0, 1.0) * fresnelColor * min(pow(max(grazing, 0.0), fresnelParams.x), 1.0) * fresnelParams.y;
  float limit = sat(fresnelParams.z);
  lit += glow * min(limit / max(max(glow.r, max(glow.g, glow.b)) * (1.0 - limit), 1e-5), 1.0);
#endif
  return lit;
}
#ifdef EMIT
float noiseAt(vec2 at) { float v = texture2D(emitNoise, at).r; return emitMode.z > 0.5 ? toLinear(vec3(v)).x : v; }
// 발광 — 그림 R 은 발광 색, G·B 는 두 번째·세 번째 색. 숨 쉬는 옷은 주기에 따라, 물체 좌표에 흐르는 잡음으로 밝기가 오간다
vec3 emission() {
  vec3 e = texture2D(emitMap, vUv).rgb;
  if (emitMode.y > 0.5) e = toLinear(e);
  vec3 glow = e.r * emitColor;
  if (emitMode.x > 0.5) {
    if (emitWave.z >= 0.01) glow = mix(glow * emitWave.y, glow, 0.5 * sin(3.14159265 * emitTime / emitWave.z) + 0.5);
    vec3 w = abs(vObjN);
    w /= max(w.x + w.y + w.z, 1e-4);
    vec2 flow = vec2(emitWave.w * emitTime);
    float nz = noiseAt(vObj.zy * emitNoiseST.xy + emitNoiseST.zw + flow) * w.x
             + noiseAt(vObj.xz * emitNoiseST.xy + emitNoiseST.zw + flow) * w.y
             + noiseAt(vObj.xy * emitNoiseST.xy + emitNoiseST.zw + flow) * w.z;
    glow = mix(glow * emitWave.y, glow, nz);
  }
  return glow * emitDay * emitWave.x + e.g * emitColorG + e.b * emitColorB;
}
#endif
#ifdef STOCKING
// 스타킹 (참고한 웹 드레스룸의 게임 셰이더 식) — 그림 rgb 는 짜임(어두울수록 성김), a 는 덧그린 무늬. dye0 은 피부색, 천 색은 dye1
// (무늬 마스크를 쓰면 R 자리 dye1 · G 자리 dye2). 성긴 곳은 피부가 천 색에 섞여 비치고, 정면일수록 피부가, 비스듬할수록 천이 짙다.
// 빛 옆쪽에 길게 맺히는 반짝임과 마스크 G 자리의 점 반짝임을 더한다
vec3 stocking(vec4 knit, vec3 n) {
  vec3 knitColor = toLinear(knit.rgb), skinTone = dye0, cloth = dye1;
  float second = 0.0;
  if (stockParams.y > 0.5) {
    vec4 m = texture2D(stockMask, vUv);
    if (stockParams.w > 0.5) m.rgb = toLinear(m.rgb);
    cloth = dye2 * m.g + dye1 * m.r;
    second = m.g;
  }
  float lowest = min(knitColor.r, min(knitColor.g, knitColor.b));
  float dense = stockParams.x * sat(1.0 - lowest), thin = 1.0 - dense;
  vec3 blended = mix(sqrt(cloth * skinTone), cloth, dense);
  vec3 shine = mix(skinTone, blended, dense);
  vec3 view = sdir(cameraPosition - vWorld);
  float facing2 = dot(n, view);
  facing2 *= facing2;
  blended = mix(blended, skinTone, thin * facing2);
  vec2 side = sdir(vec3((2.0 * normalize(lightVector) - n).xz, 0.0)).xy;
  float glint = sat(dot(side, sdir(vec3(view.xz, 0.0)).xy)) * dot(n, view);
  float power = dense + 1.0;
  blended += shine * pow(abs(glint), 7.0 * power) * (thin * 0.5 + 0.5);
  blended = mix(blended, skinTone, lowest);
  return mix(blended, knitColor, knit.a) + second * dye2 * pow(max(facing2, 0.0001), 16.0 * power) * stockParams.z;
}
#endif
#ifdef GEM
// 보석 (패션 무기의 수정) — 게임 셰이더 소스가 없어 재질 값 이름에 맞춘 근사. 내포물 그림이 속 결을 만들고, 보는 방향의
// 법선으로 짚은 면 반사 그림이 깎은 면마다 밝기와 색을 바꾼다 (밝은 면은 밝은 반사만큼 더하고 어두운 면은 어두운 반사만큼 누른다).
// 면 반사 색은 바탕색에 곱해 섞는다 — 그림 색으로 바로 섞으면 무지개 조각이 바탕색을 덮었다
vec3 gemFacet(vec3 n) {
  if (gemBase.w < 0.5) return vec3(0.5);
  vec3 nv = sdir((viewMatrix * vec4(n, 0.0)).xyz);
  vec3 cap = texture2D(gemCap, nv.xy * 0.5 * gemCapParams.z + 0.5).rgb;
  return gemTiling.w > 0.5 ? toLinear(cap) : cap;
}
vec3 gem(vec3 base, vec3 n) {
  float inc = 1.0;
  if (gemBase.z > 0.5) {
    inc = texture2D(gemInc, vUv * gemTiling.xy).r;
    if (gemTiling.z > 0.5) inc = toLinear(vec3(inc)).x;
  }
  vec3 body = base * gemBase.x * mix(1.0, inc, gemBase.y);
  vec3 cap = gemFacet(n);
  float facet = sat(dot(cap, LUMA) * 2.0);
  body = body * (1.0 - gemReflect.y * (1.0 - facet)) + gemReflect.x * facet * facet * mix(base, vec3(1.0), 0.5);
  return mix(body, body * cap * 2.0 * gemCapParams.y, gemBase.w > 0.5 ? gemCapParams.x : 0.0);
}
// 보석 광택 — 빛과 시선 사이 반짝임 (광택이 클수록 작고 또렷하다)
vec3 gemGloss(vec3 n) {
  vec3 look = sdir(cameraPosition - vWorld), l = normalize(lightVector);
  return directRGB * gemReflect.z * pow(sat(dot(n, sdir(look + l))), exp2(2.0 + 10.0 * gemReflect.z));
}
#endif
// 피부 — 경계가 부드럽고, 빛 반대쪽 가장자리를 외곽선 색으로 어둡게
vec3 skinLight(vec3 albedo, vec3 n, float shadowed) {
  vec3 c = camBack(), l = normalize(lightVector), look = sdir(cameraPosition - vWorld);
  float h = vertical(), facing = dot(n, c), camLight = dot(c, l);
  float shade = 1.0 + flatShading.z * (shadowed - 1.0);
  float tilted = dot(sdir((n + c * 0.8) * vec3(1.0, 0.15, 1.0)), l);
  float edge = max(sat(30.0 * tilted + 15.0 * min(2.2 * camLight, 0.6)) * max(shade, h * h), 0.4 * sat(1.0 - camLight));
  float intensity = max(0.0, min(0.64 * h + edge, 1.0 - 0.75 * sat(-camLight * facing)));
  vec3 light = clamp(clamp(directRGB * mix(0.3 * tilted + 0.5, 1.0, h), 0.0, 1.0) * intensity
                     + clamp(ambientRGB * mix(facing + 0.15, 1.0, h), 0.0, 1.0), 0.0, 1.0);
  vec3 axis = rimDir(c, l);
  float grazing = 1.0 - dot(n, look);
  float rim = gl_FrontFacing ? sat(dot(n, axis)) * sat(10.0 * grazing - 6.0) : 0.0;
  vec3 tinted = (1.0 - dot(look, l)) * silhouetteTint * directRGB * vec3(2.5, 1.0, 0.5);
  float outline = outlineOn * min(4.0 * sat(20.0 * grazing - 13.3) * sat(dot(n, -axis)), 1.0);
  return min(albedo * light + rim * tinted, vec3(1.5)) * mix(vec3(1.0), outlineTint, outline);
}
// 눈 — 거의 1, 그늘 쪽에서 보면 어두워진다
vec3 eyeLight(vec3 albedo) {
  float k = sat((dot(camBack(), normalize(lightVector)) + 1.2) * 1.02) * 1.14;
  return albedo * clamp(directRGB * k + ambientRGB, 0.0, 1.0);
}
// 회색에 가까운 색일수록 채도를 올린다 (참고한 웹 드레스룸의 후처리 바이브런스 0.5)
vec3 vibrance(vec3 c) {
  float top = max(c.r, max(c.g, c.b)), low = min(c.r, min(c.g, c.b));
  float v = (1.0 - clamp(top - low, 0.0, 1.0)) * 0.5;
  return c * (vec3(1.0) + v * (c - vec3(dot(c, vec3(0.299, 0.587, 0.114)))));
}
vec3 toSrgb(vec3 c) { return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c)); }
// 흉터 칸(FaceScar·BodyScar — 흉터·홍조·점) 그림 색 — 밝기를 피부에서 받아 어두운 피부에선 같은 분홍도 차분해진다.
// 채도가 높은 색(홍조)은 피부 밝기에 맞춘 같은 색상으로 바꾸고, 회색에 가까운 색(흉터 선)은 그대로 피부색을 곱한다.
vec3 scarTone(vec3 c, vec3 skin) {
  float top = max(skin.r, max(skin.g, skin.b));
  vec4 p = c.g >= c.b ? vec4(c.gb, 0.0, -1.0 / 3.0) : vec4(c.bg, -1.0, 2.0 / 3.0);
  vec4 q = c.r >= p.x ? vec4(c.r, p.yz, p.x) : vec4(p.xyw, c.r);
  float range = q.x - min(q.w, q.y), hue = abs(q.z + (q.w - q.y) / (6.0 * range + 1e-4)), chroma = range / (q.x + 1e-4);
  vec3 wheel = clamp(abs(fract(hue + vec3(1.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0) - 1.0, 0.0, 1.0);
  vec3 toned = clamp(top * 0.28 + q.x - 0.08, 0.0, 1.0) * mix(vec3(1.0), wheel, chroma);
  float keep = 1.0 - 0.1 * top;
  return mix(c, toned, clamp((chroma - 0.48) * 25.0, 0.0, 1.0)) * (skin * keep + (1.0 - keep));
}
vec2 atlasUv(vec2 uv, vec4 st, vec4 atlas) {
  uv = (uv - 0.5) / st.xy + 0.5 - 0.1 * st.zw;
  float s = sin(radians(atlas.w)), c = cos(radians(atlas.w));
  uv = vec2(dot(uv - 0.5, vec2(c, s)), dot(uv - 0.5, vec2(-s, c))) + 0.5;
  vec2 cell = 1.0 / atlas.xy;
  float index = atlas.z - 0.999, row = floor(index / atlas.x);
  vec2 low = cell * vec2(floor(index) - atlas.x * row, row);
  return clamp(uv * cell + low, low, low + cell);
}
void main() {
  vec2 uv = vUv;
#ifdef IRIS
  uv = atlasUv(uv, irisST, irisAtlas);
#endif
  vec4 tex = kind < 2 ? texture2D(map, uv) : vec4(1.0);
#ifdef ALPHATEST
  if (tex.a < 0.5) discard;   // 금속·가죽 재질은 알파가 구멍이 아니라 그 재질 자리 표시라 자르지 않는다
#endif
#ifdef BLEND
  float alpha = mix(alphaScale.x, alphaScale.y, tex.a * alphaScale.z) * alphaScale.w;
  if (alpha < 0.01) discard;
#else
  float alpha = 1.0;
#endif
  vec3 albedo;
#ifdef STOCKING
  albedo = stocking(kind < 2 ? tex : vec4(0.0), normalize(vWorldN) * (gl_FrontFacing ? 1.0 : -1.0));   // 그림 없는 스타킹은 무늬 없이
#else
  if (kind == 0) {
    vec3 raw = tex.rgb;
    vec3 w = max(1.0 - 2.0 * raw, 0.0);
    w *= step(1.0 / 128.0, w);
#ifdef SHADE
    // 곱하기 그늘 — 칸 무게만큼 칸 색으로, 나머지는 흰색(그늘 없음)
    float k = min(${GAIN.toFixed(8)} * (w.r + w.g + w.b), 1.0);
    albedo = (w.r * dye0 + w.g * dye1 + w.b * dye2) / max(w.r + w.g + w.b, 1e-4) * k + (1.0 - k);
#else
    vec3 hi = toLinear(max(2.0 * raw - 1.0, 0.0));
    albedo = clamp(${GAIN.toFixed(8)} * (w.r * dye0 + w.g * dye1 + w.b * dye2) + hi, 0.0, 1.0);
#endif
  } else if (kind == 1) {
#ifdef SHADE
    // 그늘 전용 그림(Eye_ShadeHighlight) — 밝을수록 진한 그늘
    albedo = vec3(1.0 - toLinear(vec3(max(tex.r, max(tex.g, tex.b)))).x);
#else
    albedo = toLinear(tex.rgb);
#endif
  } else {
    albedo = base;
  }
#endif
#ifdef TATTOO
  // 문신·흉터·홍조 — 염색 문신은 회색(106) 그림에 고른 색을 입힌다. 흉터 칸은 피부 밝기를 따르고(scarTone),
  // 문신 칸은 피부색으로 조금 물든다 (dye0 = 피부색, 참고한 웹 드레스룸의 _IsScarMode 식)
  vec4 tt = texture2D(tatMap, atlasUv(vUv, tatST, tatAtlas));
  vec3 tc = toLinear(tt.rgb);
  if (tatDye > 0.5) tc = clamp(tatColor * tc / 0.1441, 0.0, 1.0);
  tc = tatScar > 0.5 ? scarTone(tc, dye0) : tc * (dye0 * 0.7 + 0.3);
  albedo = mix(albedo, tc, tt.a);
#endif
#ifdef MOUTH
#ifdef LIPS
  vec4 em = mouthOn > 0.5 ? texture2D(mouthMap, atlasUv(vMouth, mouthST, mouthAtlas))
                          : texture2D(lipsMap, atlasUv(vMouth, lipsST, lipsAtlas));   // 꾸미기 입 (평소 얼굴)
#else
  vec4 em = texture2D(mouthMap, atlasUv(vMouth, mouthST, mouthAtlas));
#endif
  albedo = mix(albedo, toLinear(em.rgb), em.a);
#endif
#ifdef UNLIT
  gl_FragColor = vec4(toSrgb(albedo), alpha);
  return;
#endif
  albedo *= tint;
  vec3 n = normalize(vWorldN) * (gl_FrontFacing ? 1.0 : -1.0);
#ifdef GEM
  albedo = gem(albedo, n);
#endif
#if defined(EYE)
  vec3 c = eyeLight(albedo);
#elif defined(SKIN)
  vec3 c = skinLight(albedo, n, 1.0);
#else
#if defined(STOCKING) || defined(GEM)
  vec3 c = clothLight(albedo, n, 1.0, 1.0);   // 스타킹 그림 알파는 무늬 자리, 보석은 재질 전체 — 금속·가죽 자리가 아니다
#else
  vec3 c = clothLight(albedo, n, 1.0, kind < 2 ? tex.a : 1.0);
#endif
#endif
#ifdef GEM
  c += gemGloss(n);
#endif
#ifdef EMIT
  c += emission();
#endif
  gl_FragColor = vec4(toSrgb(clamp(vibrance(clamp(c, 0.0, 1.0)), 0.0, 1.0)), alpha);
}`;

const texLoader = new THREE.TextureLoader();
const texCache = new Map();   // url → 텍스처 (쓰는 머티리얼 수를 세어 0 이 되면 GPU 에서 내린다)
function texture(url, held, repeat = false) {
  let t = texCache.get(url);
  if (!t) {
    t = texLoader.load(url);
    t.colorSpace = THREE.NoColorSpace;   // DyeMap 은 색이 아니라 값 — 변환하지 않는다
    t.anisotropy = 4;
    t.userData.refs = 0;
    texCache.set(url, t);
  }
  if (repeat && t.wrapS !== THREE.RepeatWrapping) {   // 0~1 밖을 짚는 그림 (흐르는 잡음·보석 내포물)
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.needsUpdate = true;
  }
  t.userData.refs++;
  held.push(url);
  return t;
}

function release(url) {
  const t = texCache.get(url);
  if (!t || --t.userData.refs > 0) return;
  texCache.delete(url);
  t.dispose();
}

function linear(hex) {
  return new THREE.Color(hex);   // three 가 sRGB 글자를 선형 값으로 바꿔 든다
}

const v4 = (a, d) => new THREE.Vector4(...(a || d));
/** 머티리얼 색(sRGB 0~1 값) → 선형. */
const srgb = (a, d) => new THREE.Color().setRGB(...(a || d).slice(0, 3), THREE.SRGBColorSpace);

/** 모든 재질이 같이 쓰는 빛 — 월드 고정 방향 하나 (참고한 웹 드레스룸의 기본값). actor* 는 Stage.fit 이 키에 맞춘다. */
export const LIGHT = {
  lightVector: { value: new THREE.Vector3(-0.495997672, 0.809989818, 0.312894907).normalize() },
  directRGB: { value: new THREE.Color(0.95, 0.95, 0.95) },
  ambientRGB: { value: new THREE.Color(0.15, 0.15, 0.15) },
  actorBase: { value: 0 },
  actorHeadHeight: { value: 1.5 },
  // 금속에 비치는 주변 — 게임은 장소마다 반사 프로브를 쓴다. 여기선 밝은 위·중간 벽·어두운 바닥 세 색
  skyTop: { value: new THREE.Vector3(0.45, 0.47, 0.52) },
  skyMiddle: { value: new THREE.Vector3(0.26, 0.25, 0.25) },
  skyBottom: { value: new THREE.Vector3(0.07, 0.06, 0.06) },
  skyPos: { value: new THREE.Vector4(-0.35, 0.05, 0.05, 0.8) },   // (아래→중간 시작·끝, 중간→위 시작·끝) 높이
  emitTime: { value: 0 },   // 숨 쉬는 발광의 시간 (초) — 그리는 고리가 늘린다
};

/** 재질별 명암 값 — 게임 머티리얼 값 그대로, 없으면 게임 셰이더 기본값. */
function shading(m) {
  const f = m.float || {}, vec = m.vec || {};
  const mode = f._OutlineColorMode || 0;
  const oc = srgb(vec._OutlineColor, [1, 1, 1]);
  const outline = mode === 0 ? oc.multiply(new THREE.Color(0.3375, 0.2385, 0.3105)) : mode === 1 ? oc : new THREE.Color(0.36, 0.318, 0.414);
  return {
    tint: { value: srgb(vec._TintColor, [1, 1, 1]) },
    silhouetteTint: { value: f._SilhouetteOff > 0.5 ? new THREE.Color(0, 0, 0) : srgb(vec._SilhouetteTintColor, [1, 1, 1]) },
    outlineTint: { value: outline },
    outlineOn: { value: f._OutlineOff > 0.5 ? 0 : 1 },
    backDarken: { value: f._BackFaceDarkenAmount ?? 0.5 },
    shadingType: { value: f._ShadingType ?? 0 },
    flatShading: { value: new THREE.Vector3(f._FlatShadingAmountTop ?? 1, f._FlatShadingAmountBottom ?? 0, f._ReceiveShadowStrength ?? 1) },
  };
}

function makeMaterial(m, texBase) {
  const kind = m.kind === 'dye' ? 0 : m.kind === 'tex' ? 1 : 2;
  const vec = m.vec || {};
  const defines = {};
  const held = [];
  const uniforms = {
    ...LIGHT,
    ...shading(m),
    map: { value: m.tex ? texture(texBase + m.tex + '.png', held) : null },
    kind: { value: kind },
    dye0: { value: linear(m.dye[0]) },
    dye1: { value: linear(m.dye[1]) },
    dye2: { value: linear(m.dye[2]) },
    base: { value: linear(m.color) },
  };
  const kw = m.kw || [];
  const fl = m.float || {};
  // _RenderMode 1 = 반투명 (안경알·비치는 천) — 알파 = mix(최소, 최대, 그림 알파 × _AlphaOverride) × _EffectAlphaValue
  // (참고한 웹 드레스룸 식). 눈·피부 재질은 전처럼 잘라내기로
  // 스타킹은 그림 알파가 덧그린 무늬 자리라 자르지도 비치지도 않는다
  const blend = fl._RenderMode > 0 && !m.skin && !eyeRole(m.name) && !m.stocking;
  if (blend) {
    defines.BLEND = '';
    uniforms.alphaScale = { value: new THREE.Vector4(fl._AlphaScaleMin ?? 0, fl._AlphaScaleMax ?? 1, fl._AlphaOverride ?? 1, fl._EffectAlphaValue ?? 1) };
  } else if (!m.stocking && (kw.includes('_ALPHATEST_ON') || fl._RenderMode > 0)) defines.ALPHATEST = '';
  if (m.skin) defines.SKIN = '';
  if (vec._BaseMapAtlasSize) {
    defines.IRIS = '';
    uniforms.irisAtlas = { value: v4(vec._BaseMapAtlasSize) };
    uniforms.irisST = { value: v4(vec._BaseMapScalePosition, [1, 1, 0, 0]) };
  }
  if (m.emotion) {
    // 입 — 표정 표(4×8)의 기본 칸. 두 번째 UV(uvMouth) 를 쓰는 메시에만 붙는다 (loadModel 이 정한다)
    const st = vec._EmotionMouthMapScalePosition || [1, 1, 0, 0];
    const sb = vec._EmotionMouthMapScalePositionBase || [1, 1, 0, 0];
    uniforms.mouthMap = { value: texture(texBase + m.emotion + '.png', held) };
    uniforms.mouthAtlas = { value: v4(vec._EmotionMouthMapAtlasSize, [4, 8, 1, 0]) };
    uniforms.mouthOn = { value: 0 };
    uniforms.mouthST = { value: new THREE.Vector4(sb[0] * st[0], sb[1] * st[1], sb[2] + st[2], sb[3] + st[3]) };
  }
  if (!m.skin && !eyeRole(m.name)) clothFeatures(m, defines, uniforms, texBase, held);
  // _CullType 은 Unity CullMode — 0 양면, 1 뒷면만, 2 앞면만. 값이 없는 피부 셰이더는 앞면만
  const cull = m.float ? m.float._CullType : undefined;
  const side = cull === 0 ? THREE.DoubleSide : cull === 1 ? THREE.BackSide : THREE.FrontSide;
  const mat = new THREE.ShaderMaterial({ vertexShader: VERT, fragmentShader: FRAG, side, defines, uniforms });
  if (blend) {
    mat.transparent = true;
    mat.depthWrite = !!fl._ZWrite;   // 안경알은 깊이를 안 쓴다 (뒤 눈이 가려지지 않게)
  }
  mat.userData = { info: m, tex: held };   // tex: 이 머티리얼이 잡은 텍스처 (variant 는 빌려 쓰므로 없다)
  eyeMaterial(mat, eyeRole(m.name));
  return mat;
}

/** 옷 재질의 금속·가죽(_IsMetal·_IsLeather)·가장자리 빛(fresnel)·발광(emit)·스타킹 — 참고한 웹 드레스룸의 게임 셰이더 식.
 *  보석(gem)은 참고할 식이 없어 근사한다. */
function clothFeatures(m, defines, uniforms, texBase, held) {
  const fl = m.float || {};
  const st = m.stocking;
  if (st) {
    defines.STOCKING = '';
    uniforms.stockMask = { value: st.mask ? texture(texBase + st.mask + '.png', held) : uniforms.map.value };
    uniforms.stockParams = { value: new THREE.Vector4((st.denier - 10) / 170, st.mask ? 1 : 0, st.point, st.maskSrgb ? 1 : 0) };
  }
  const g = m.gem;
  if (g) {
    defines.GEM = '';
    const blank = uniforms.map.value;   // 못 읽은 그림 자리 (셰이더가 그 몫을 끈다)
    Object.assign(uniforms, {
      gemCap: { value: g.capTex ? texture(texBase + g.capTex + '.png', held) : blank },
      gemInc: { value: g.incTex ? texture(texBase + g.incTex + '.png', held, true) : blank },
      gemBase: { value: new THREE.Vector4(...g.base, g.incTex ? 1 : 0, g.capTex ? 1 : 0) },
      gemReflect: { value: new THREE.Vector3(...g.reflect) },
      gemCapParams: { value: new THREE.Vector3(...g.matcap) },
      gemTiling: { value: new THREE.Vector4(...g.tiling, g.incTexSrgb ? 1 : 0, g.capTexSrgb ? 1 : 0) },
    });
  }
  const metal = !g && fl._IsMetal > 0.5, leather = !g && !metal && fl._IsLeather > 0.5;
  if (metal || leather) {
    defines.FEATURE = '';
    const smooth = metal ? fl._Smoothness ?? 1 : fl._LeatherSmoothness ?? 0.5;
    uniforms.featureParams = { value: new THREE.Vector4(metal ? 1 : 0, leather ? 1 : 0, smooth, fl._SilhouetteOff > 0.5 ? 0 : 1) };
  }
  if (m.fresnel) {
    defines.FRESNEL = '';
    uniforms.fresnelColor = { value: srgb(m.fresnel) };
    uniforms.fresnelParams = { value: new THREE.Vector3(...m.fresnel.slice(3, 6)) };
  }
  const e = m.emit;
  if (e) {
    defines.EMIT = '';
    const map = texture(texBase + e.tex + '.png', held);
    const breathe = !!e.noise;   // export 가 숨 쉬는 옷(_IsBreathingEmissionMode)에만 잡음 그림을 싣는다
    const [c0, c1, c2] = e.colors.map((c) => new THREE.Vector3(...c));   // HDR 선형 값 그대로
    Object.assign(uniforms, {
      emitMap: { value: map },
      emitNoise: { value: breathe ? texture(texBase + e.noise + '.png', held, true) : map },
      emitColor: { value: c0 }, emitColorG: { value: c1 }, emitColorB: { value: c2 },
      emitMode: { value: new THREE.Vector3(breathe ? 1 : 0, e.srgb ? 1 : 0, e.noiseSrgb ? 1 : 0) },
      emitWave: { value: new THREE.Vector4(...e.wave) },
      emitNoiseST: { value: v4(e.noiseST, [1, 1, 0, 0]) },
      emitDay: { value: e.night ? 0 : 1 },
    });
  }
}

/** 스타킹의 비치는 피부(채널 0)가 몸 피부색을 받나 — 모델 정의가 그 채널을 의상 색 칸에 이었으면 그 칸을 따른다. */
const skinUnder = (info) => !!info.stocking && !(info.slots && info.slots[0] != null);

/** 재질에서 의상 색 칸을 받는 염색 채널 — 스타킹은 채널 1 (무늬 마스크를 쓰면 1·2), 채널 0 은 피부색이 아닐 때만. */
function clothChannels(info) {
  if (!info.stocking) return [0, 1, 2];
  const chs = info.stocking.useMask ? [1, 2] : [1];
  return skinUnder(info) ? chs : [0, ...chs];
}

/** 재질 i 의 갈래 (같은 텍스처를 쓴다 — clone 은 텍스처까지 복제해 아직 안 읽힌 그림을 놓친다). mats 끝에 더한다. */
function variant(mats, i) {
  const src = mats[i];
  const mat = src.clone();
  for (const k in mat.uniforms) if (src.uniforms[k].value && src.uniforms[k].value.isTexture) mat.uniforms[k].value = src.uniforms[k].value;
  Object.assign(mat.uniforms, LIGHT);   // clone 이 끊은 같이 쓰는 빛을 다시 잇는다
  mat.userData = { info: src.userData.info };
  mats.push(mat);
  return mat;
}

/** 눈 부품 역할 — 흰자 · 눈동자 · 눈꺼풀 그림자 · 반짝이 (그리는 순서). */
const EYE_ORDER = { sclera: 10, iris: 11, shade: 12, highlight: 13 };
function eyeRole(name) {
  if (/^Eye_Base_\d+$/.test(name)) return 'sclera';   // Eye_Base_Skin(눈두덩)은 아니다
  if (name.includes('_EyeBall_')) return 'iris';
  if (name.startsWith('Eye_Highlight')) return 'highlight';
  return null;
}

/**
 * 흰자가 실제로 보이는 자리(깊이 통과)에만 스텐실을 찍고, 나머지는 그 안에만 깊이 없이 그린다.
 * 눈동자는 흰자보다 안쪽(눈알 속)에 있어 깊이로 재면 옆에서 볼 때 얼굴 면에 가려진다 — 그래서 깊이는 흰자만 잰다.
 * 머리카락·눈꺼풀이 흰자를 가리면 스텐실이 안 찍혀 눈동자도 같이 가려진다. 모두 깊이를 안 써서 서로 가리지 않는다.
 * 그림자(Mesh_EyeShade — 눈썹과 같은 재질, 위 검정·아래 흰색)는 곱하기로 얹어 위 눈꺼풀 그늘만 남긴다.
 */
function eyeMaterial(mat, role) {
  mat.userData.eye = role;
  if (!role) return;
  mat.defines.EYE = '';
  mat.side = THREE.FrontSide;
  mat.depthWrite = false;
  mat.stencilWrite = true;
  mat.stencilRef = 1;
  if (role === 'sclera') {
    mat.stencilFunc = THREE.AlwaysStencilFunc;
    mat.stencilFail = mat.stencilZFail = THREE.KeepStencilOp;
    mat.stencilZPass = THREE.ReplaceStencilOp;
    return;
  }
  mat.depthTest = false;
  mat.stencilFunc = THREE.EqualStencilFunc;
  if (role === 'shade' || role === 'highlight') {
    mat.defines.UNLIT = '';
    mat.transparent = true;
  }
  if (role === 'shade') {
    mat.defines.SHADE = '';
    mat.blending = THREE.CustomBlending;
    mat.blendSrc = THREE.ZeroFactor;
    mat.blendDst = THREE.SrcColorFactor;
    mat.blendSrcAlpha = THREE.ZeroFactor;
    mat.blendDstAlpha = THREE.OneFactor;
  }
}

/** 공용 뼈대 — 몸 뼈대에 다른 모델의 없는 뼈(치마·얼굴 뼈 등)를 경로대로 붙인다. 루트에서 x 를 뒤집는다. */
export class Rig {
  constructor() {
    this.root = new THREE.Group();
    this.root.scale.x = -1;
    this.bones = new Map();   // 경로 → Bone
    this.named = new Map();   // 이름 → Bone (찾은 것만 기억 — 뼈는 늘기만 한다)
    this.missed = new Set();  // 못 찾은 이름 (매 프레임 찾는 쪽이 뼈 전체를 훑지 않게 — 뼈를 더하면 비운다)
  }

  add(skeleton) {
    this.missed.clear();
    for (const n of skeleton) {
      if (this.bones.has(n.path)) continue;
      const cut = n.path.lastIndexOf('/');
      const parent = cut < 0 ? this.root : this.bones.get(n.path.slice(0, cut));
      if (!parent) continue;
      const b = new THREE.Bone();
      b.name = n.path.slice(cut + 1);
      b.position.fromArray(n.t);
      b.quaternion.fromArray(n.r);
      b.scale.fromArray(n.s);
      b.userData.rest = [b.position.clone(), b.quaternion.clone(), b.scale.clone()];
      parent.add(b);
      this.bones.set(n.path, b);
    }
    this.root.updateMatrixWorld(true);
  }

  /** 이름(경로 끝)으로 뼈 찾기. */
  find(name) {
    let b = this.named.get(name);
    if (b) return b;
    if (this.missed.has(name)) return null;
    const tail = '/' + name;
    for (const [p, x] of this.bones) if (p === name || p.endsWith(tail)) { b = x; break; }
    if (b) this.named.set(name, b); else this.missed.add(name);
    return b || null;
  }

  /** 바인드(기본) 자세로. update=false 면 행렬은 그대로 둔다 (매 프레임 — 그리기가 어차피 갱신한다). */
  rest(update = true) {
    for (const b of this.bones.values()) {
      const [t, r, s] = b.userData.rest;
      b.position.copy(t);
      b.quaternion.copy(r);
      b.scale.copy(s);
    }
    if (update) this.root.updateMatrixWorld(true);
  }
}

/** 붙는 자세 표에서 체형 것 — (아이?, 성별) → (아이?, 'None') → 같은 나이 아무거나 → 첫 것 (mabi/dress/tools.pick_tf 와 같다). */
function pickTf(tf, infant, gender) {
  for (const g of [gender, 'None']) {
    const t = tf.find((x) => x.infant === infant && x.gender === g);
    if (t) return t;
  }
  return tf.find((x) => x.infant === infant) || tf[0] || null;
}

/** 모델 하나 (몸·머리·눈·의상). */
export class Model {
  constructor(id, meta, group, mats, meshes) {
    this.id = id;
    this.meta = meta;
    this.group = group;     // 스킨 메시 (장면 루트)
    this.mats = mats;
    this.meshes = meshes;   // 스킨 메시 + 뼈에 붙은 메시
    this.decals = {};       // 자리 → 데칼 그림 url (잡은 텍스처)
    // 메시 보이기 상태 — 고칠 땐 setShown·setHairCover·setHood·setEyeHide·setTool 로 (meshVisible 이 한 곳에서 정한다)
    this.shown = true;      // 다른 옷이 이 부위를 가리면 false
    this.hairLevel = null;  // 머리 메시(H<k>) 중 보일 단계 (null = 거르지 않음)
    this.hood = 'off';      // 후드 메시 중 보일 모양
    this.eyeHide = null;    // 눈 모델 — 가린 눈 부위 Set
    this.tool = null;       // 패션 무기 — 'Drawn'(꺼냄)·'Undrawn'(넣음), null = 꺼낼 때 고른 상태 (attach[].state)
    this.toolHidden = false;   // 패션 무기 숨김 (상태와 따로)
    this.toolUsed = new Map(); // 도구 조각(attach 항목) → 실제로 놓은 상태 값 (poseTools — 소켓이 없으면 꺼낼 때 상태)
    this.fx = null;         // 의상 이펙트 (fx.js FxPlayer — 모델이 보이고 후드 모양이 맞을 때만 돈다)
    this.fxTex = [];        // 이펙트가 잡은 텍스처 url
  }

  /** 옷의 가림 규칙 (mabi/dress/cover.py — 없으면 null). */
  get rules() {
    return this.meta.rules || null;
  }

  /** 옷의 겹침 순서 값 {slot, junctions} (mabi/dress/cover.py fit — 없으면 null). */
  get fit() {
    return this.meta.fit || null;
  }

  /** 메시 하나를 보이나 — 내보낼 때 숨김·몸 자르는 고리·옷 자르는 판·모델 숨김·머리 단계·후드 모양·가린 눈·무기 상태. */
  meshVisible(o) {
    const f = o.userData.flags;
    const tool = f.piece === undefined ? null : this.toolShown(f.piece);
    if (!this.shown || (tool === null ? f.hidden : !tool) || f.cut || f.sep) return false;
    if (f.hair !== undefined && this.hairLevel !== null && f.hair !== this.hairLevel) return false;
    if (f.hood && f.hood !== this.hood) return false;
    return !this.eyeHide || eyeVisible(o.name, this.eyeHide);
  }

  refresh() {
    for (const o of this.meshes) o.visible = this.meshVisible(o);
  }

  setShown(on) {
    this.shown = on;
    this.refresh();
  }

  /** 이 모델의 후드 모양들 ('on'·'off'·'pressed'). */
  hoods() {
    return [...new Set(this.meshes.map((o) => o.userData.flags.hood).filter(Boolean))];
  }

  /** 후드 모양 — 그 모양 메시가 없으면 벗은 모양. */
  setHood(state) {
    this.hood = this.hoods().includes(state) ? state : 'off';
    this.refresh();
  }

  /** 눈 모델 — 가린 눈 부위. 한쪽 눈썹만 가리면 눈썹 메시에서 그쪽 삼각형만 뺀다. */
  setEyeHide(hidden) {
    this.eyeHide = hidden;
    this.refresh();
    const brow = this.meshes.find((o) => EYE_MESH.brow.test(o.name));
    if (!brow) return;
    const left = this.meshes.find((o) => EYE_MESH.left.test(o.name));
    const L = hidden.has('LeftEyebrow'), R = hidden.has('RightEyebrow');
    let side = 0;   // 왼쪽 눈의 x 부호 (메시 좌표)
    if (L !== R && left) {
      const p = left.geometry.attributes.position;
      let sx = 0;
      for (let i = 0; i < p.count; i++) sx += p.getX(i);
      side = Math.sign(sx);
    }
    const p = brow.geometry.attributes.position;
    const drop = L ? side : -side;   // 뺄 쪽의 x 부호
    keepTriangles(brow, side ? (a, b, c) => Math.sign(p.getX(a) + p.getX(b) + p.getX(c)) === drop : null);
  }

  /** 칸 색을 받는 머티리얼 (피부 빼고) — 없으면 염색 불가 옷. */
  dyeMats() {
    return this.mats.filter((m) => !m.userData.info.skin && m.userData.info.kind === 'dye');
  }

  /** 염색 받는 자리 [재질, 채널, 의상 색 칸] — 재질 slots(채널마다 받는 칸, 모델 정의의 배선)가 있으면 그대로,
   *  없으면 칸 i = 채널 i. 배선 없는 채널은 빠진다 (재질 기본색 그대로). */
  *dyeTargets() {
    for (const m of this.dyeMats()) {
      const sl = m.userData.info.slots;
      for (const ch of clothChannels(m.userData.info)) {
        const k = sl ? sl[ch] : ch;
        if (k != null) yield [m, ch, k];
      }
    }
  }

  /** 의상 색 칸(최대 6) → 재질 염색 채널 (dyeTargets). */
  setDyes(colors) {
    for (const [m, ch, k] of this.dyeTargets()) if (colors[k]) m.uniforms['dye' + ch].value = linear(colors[k]);
  }

  /** 패션 무기인가 (도구 붙는 곳이 있다). */
  get hasTools() {
    return !!(this.meta.attach && this.meta.attach.some((a) => a.states));
  }

  /** 도구 조각 a 의 고른 상태 값 {to, visible, tf} — 고른 상태(tool)가 그 도구에 없으면 꺼낼 때 상태.
   *  붙을 소켓이 뼈대에 없어 꺼낼 때 상태로 돌리는 것은 뼈대를 아는 poseTools 가 한다 (toolUsed). */
  toolState(a) {
    if (!a || !a.states) return null;
    const want = this.tool ? a.states[this.tool] : null;
    return want && want.to !== null && want.to !== undefined ? want : a.states[a.state] || null;
  }

  /** 도구 조각 k 의 메시를 보이나 — 숨김이면 아니고, 상태 값이 있으면 그 상태의 visible (넣으면 안 보이는 부채 등). 무기가 아니면 null. */
  toolShown(k) {
    const a = this.meta.attach && this.meta.attach[k];
    if (!a || !a.states) return null;
    if (this.toolHidden) return false;
    const st = this.toolUsed.get(a) || this.toolState(a);
    return st ? st.visible !== false : null;
  }

  /** 무기 상태·숨김 바꾸기 — 자세는 poseTools 로 다시 놓는다. */
  setTool(state, hidden = false) {
    this.tool = state === 'Drawn' || state === 'Undrawn' ? state : null;
    this.toolHidden = !!hidden;
    this.refresh();
  }

  /** 패션 무기 — 도구 prefab 루트(attach[].node)를 지금 상태(setTool)의 소켓 밑에 체형에 맞는 붙는 자세로
   *  (꺼낸 json 은 꺼낼 때 상태·여성 어른 자세로 구워져 있다). 자세는 뼈의 기본값(rest)에 넣는다 — 다음 rest()부터 그 자세. */
  poseTools(rig, infant, gender) {
    const socketOf = (st) => (st && st.to === '' ? rig.root : st && st.to ? rig.bones.get(st.to) : null);
    this.toolUsed.clear();
    for (const a of this.meta.attach || []) {
      let st = a.node ? this.toolState(a) : null;
      if (st && !socketOf(st)) st = a.states[a.state];   // 이 뼈대에 그 소켓이 없으면 꺼낼 때 상태 (구운 자리)
      if (st) this.toolUsed.set(a, st);
      const bone = st && rig.bones.get(a.node);
      const tf = bone && pickTf(st.tf || [], infant, gender);
      if (!tf) continue;
      const socket = socketOf(st);
      if (socket && bone.parent !== socket) socket.add(bone);   // 넣으면 등·허리, 꺼내면 손 — 소켓이 다를 수 있다
      const [t, r, s] = bone.userData.rest;
      t.fromArray(tf.t);
      r.fromArray(tf.r);
      s.fromArray(tf.s);
    }
    if (this.meta.attach) this.refresh();   // 보이기도 실제로 놓은 상태대로 (toolShown)
  }

  /** 깊이를 살짝 뒤로 — 같은 깊이에서 앞 것이 이기게 (줄무늬처럼 깜빡이지 않게). 몸은 2, 옷의 피부 조각은 1 —
   *  몸 < 옷의 피부 조각 < 옷 천 순으로 보인다. skinOnly 면 피부 재질만. */
  pushBack(units = 2, skinOnly = false) {
    for (const m of this.mats) {
      if (skinOnly && !m.userData.info.skin) continue;
      m.polygonOffset = true;
      m.polygonOffsetFactor = units / 2;
      m.polygonOffsetUnits = units;
    }
  }

  /** 피부색 — 머티리얼 기본 피부색(칸 1)과 같은 칸만 바꾼다 (몸은 칸 1·2, 얼굴은 칸 1). 스타킹은 비치는 피부(칸 1). */
  setSkin(hex) {
    for (const m of this.mats) {
      const info = m.userData.info;
      if (skinUnder(info)) m.uniforms.dye0.value = linear(hex);
      if (!info.skin || info.kind !== 'dye') continue;
      info.dye.forEach((d, i) => { if (d === info.dye[0]) m.uniforms['dye' + i].value = linear(hex); });
    }
  }

  /** 눈동자 색 (칸 1) — null 이면 모델 기본색. */
  setEyeColor(hex) {
    for (const m of this.mats) {
      const info = m.userData.info;
      if (m.userData.eye === 'iris' && info.kind === 'dye') m.uniforms.dye0.value = linear(hex || info.dye[0]);
    }
  }

  /** 눈썹 색 (눈썹 재질 칸 2 — 게임은 머리색을 넣는다) — null 이면 모델 기본색. 눈꺼풀 그늘은 그대로. */
  setBrow(hex) {
    for (const m of this.mats) {
      const info = m.userData.info;
      if (BROW.test(info.name) && !m.userData.eye && info.kind === 'dye') m.uniforms.dye1.value = linear(hex || info.dye[1]);
    }
  }

  /**
   * 데칼 — where: 'lips' 입(얼굴 두 번째 UV) · 'face' 얼굴 문신(얼굴 재질) · 'body' 몸 문신(피부 재질).
   * d = {url, st, rot, dye, scar, color} 또는 null(뗀다). scar: 흉터 칸(피부 밝기를 따른다). 얼굴 재질은 입 표가 걸린 재질이다.
   */
  setDecal(where, d) {
    const lips = where === 'lips';
    const def = lips ? 'LIPS' : 'TATTOO', pre = lips ? 'lips' : 'tat';
    const mats = this.mats.filter((m) => (where === 'body' ? m.userData.info.skin && !m.userData.eye : m.uniforms.mouthMap));
    const url = d && mats.length ? d.url : null;
    if (this.decals[where] !== url) {   // 그림은 모델 하나가 한 번 잡는다 (재질마다 세지 않는다)
      if (url) texture(url, []);
      if (this.decals[where]) release(this.decals[where]);
      this.decals[where] = url;
    }
    const tex = url ? texCache.get(url) : null;
    for (const m of mats) {
      if (!tex) {
        if (def in m.defines) { delete m.defines[def]; m.needsUpdate = true; }
        continue;
      }
      const set = (k, v) => { if (m.uniforms[k]) m.uniforms[k].value = v; else m.uniforms[k] = { value: v }; };
      set(pre + 'Map', tex);
      set(pre + 'ST', v4(d.st, [1, 1, 0, 0]));
      set(pre + 'Atlas', new THREE.Vector4(1, 1, 1, d.rot || 0));
      if (!lips) {
        set('tatColor', linear(d.color || TATTOO_GRAY));
        set('tatDye', d.dye ? 1 : 0);
        set('tatScar', d.scar ? 1 : 0);
      }
      if (!(def in m.defines)) { m.defines[def] = ''; m.needsUpdate = true; }
    }
  }

  /** 입 모양 덮어쓰기 — 표정 표 칸(1부터, 풍선껌 같은 장식이 정한다) 또는 0(평소 입: 꾸미기 입이나 재질 기본 칸). */
  setMouth(cell) {
    for (const m of this.mats) {
      const a = m.uniforms.mouthAtlas;
      if (!a) continue;
      if (m.userData.mouthBase === undefined) m.userData.mouthBase = a.value.z;
      a.value.z = cell || m.userData.mouthBase;
      m.uniforms.mouthOn.value = cell ? 1 : 0;
    }
  }

  /** 문신 색만 바꾼다. */
  setDecalColor(where, hex) {
    for (const m of this.mats) if (m.uniforms.tatColor && (where === 'body' ? m.userData.info.skin : m.uniforms.mouthMap)) m.uniforms.tatColor.value = linear(hex || TATTOO_GRAY);
  }

  /** 칸마다 기본 염색색 (그 칸을 받는 첫 재질 채널의 색) — 길이가 이 옷의 칸 수. 받는 칸이 없으면 null (염색 불가). */
  defaults() {
    const out = [];
    for (const [m, ch, k] of this.dyeTargets()) if (!out[k]) out[k] = m.userData.info.dye[ch];
    return out.length ? Array.from(out, (c) => c || '#FFFFFF') : null;
  }

  /** 모프 값 — 이름이 같은 셰이프를 v(0~1) 로. */
  setMorph(name, v) {
    for (const o of this.meshes) {
      const i = o.morphTargetDictionary && o.morphTargetDictionary[name];
      if (i !== undefined) o.morphTargetInfluences[i] = v;
    }
  }

  /** 체형 셰이프 — 하나만 100%, 빈 값이면 기본. */
  setShape(name) {
    for (const s of BODY_SHAPES) this.setMorph(s, s === name ? 1 : 0);
  }

  /** 모자 단계(cover)에 맞는 머리 모양만 보인다 (그 단계가 없는 머리는 H0). */
  setHairCover(cover) {
    const hair = this.meshes.filter((o) => o.userData.flags.hair !== undefined);
    if (!hair.length) return;
    this.hairLevel = hair.some((o) => o.userData.flags.hair === cover) ? cover : 0;
    this.refresh();
  }

  /** 이 모델이 가리는 모자 종류 (없으면 0). */
  cover() {
    return this.meshes.reduce((c, o) => Math.max(c, o.userData.flags.cover || 0), 0);
  }

  dispose() {
    for (const url of Object.values(this.decals)) if (url) release(url);
    this.decals = {};
    if (this.fx) this.fx.dispose();
    this.fx = null;
    for (const url of this.fxTex) release(url);
    this.fxTex = [];
    for (const o of this.meshes) {
      o.removeFromParent();
      o.geometry.dispose();
      if (o.skeleton) o.skeleton.dispose();
    }
    for (const m of this.mats) {
      for (const url of m.userData.tex || []) release(url);
      m.dispose();
    }
  }
}

const BROW = /^Eyebrow/i;
export const BODY_SHAPES = ['Fat', 'Thin', 'Muscular'];   // 체형 셰이프 모프 이름 (빈 값 = 기본)
export const TATTOO_GRAY = '#6A6A6A';   // 문신 그림의 회색 — 이 색을 고르면 그림 그대로

/** url(cache/models/<id>.json) → Model. 뼈대는 rig 에 붙인다 (없는 뼈만). */
export async function loadModel(id, url, rig) {
  const meta = await (await fetch(url)).json();
  const dir = url.slice(0, url.lastIndexOf('/') + 1);
  const bin = await (await fetch(dir + meta.bin)).arrayBuffer();
  const texBase = dir + '../tex/';
  rig.add(meta.skeleton || []);
  const mats = meta.materials.map((m) => makeMaterial(m, texBase));
  const group = new THREE.Group();
  group.name = id;
  const meshes = [];
  const f32 = (off, n) => new Float32Array(bin, off, n).slice();
  for (const m of meta.meshes) {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(f32(m.pos, m.n * 3), 3));
    g.setAttribute('normal', new THREE.BufferAttribute(f32(m.nrm, m.n * 3), 3));
    g.setAttribute('uv', new THREE.BufferAttribute(f32(m.uv, m.n * 2), 2));
    if (m.uv1 !== undefined) g.setAttribute('uvMouth', new THREE.BufferAttribute(f32(m.uv1, m.n * 2), 2));
    const total = m.groups.reduce((s, x) => s + x.count, 0);
    const idx = new Uint32Array(total);
    let at = 0;
    const useMats = [];
    m.groups.forEach((x, gi) => {
      idx.set(new Uint32Array(bin, x.off, x.count), at);
      g.addGroup(at, x.count, gi);
      let mat = mats[x.mat];
      if (m.name === 'Mesh_EyeBrow' && !BROW.test(mat.userData.info.name)) {
        // 남성 눈 모델은 눈썹 메시에 흰자 재질(Eye_Base)이 걸려 있어 염색 지도 원본 색(보라)이 나온다 — 눈썹 재질로
        mat = mats.find((y) => BROW.test(y.userData.info.name)) || mat;
      }
      if (m.name === 'Mesh_EyeShade') {   // 눈썹 재질을 같이 쓰기도 하지만 그늘로 그린다
        mat = variant(mats, x.mat);
        eyeMaterial(mat, 'shade');
      } else if (mat.uniforms.mouthMap && m.uv1 === undefined) {   // 입 표는 두 번째 UV 가 있는 메시에만
        mat = variant(mats, x.mat);
        delete mat.defines.MOUTH;
      } else if (mat.uniforms.mouthMap) {
        mat.defines.MOUTH = '';
      }
      useMats.push(mat);
      at += x.count;
    });
    // 스킨 메시는 뼈대 루트의 x 뒤집기가 뼈 행렬 안에 숨어 있어 three 가 감김 방향을 못 바꿔 준다 —
    // 삼각형 순서를 직접 뒤집어야 앞면이 앞면으로 잡힌다 (뼈에 붙은 일반 메시는 three 가 행렬식으로 처리)
    if (m.rig) for (let t = 0; t < total; t += 3) { const a = idx[t + 1]; idx[t + 1] = idx[t + 2]; idx[t + 2] = a; }
    g.setIndex(new THREE.BufferAttribute(idx, 1));
    const names = Object.keys(m.shapes || {});
    if (names.length) {
      g.morphAttributes.position = names.map((k) => {
        const a = new THREE.BufferAttribute(f32(m.shapes[k], m.n * 3), 3);
        a.name = k;
        return a;
      });
      g.morphTargetsRelative = true;
    }
    let mesh;
    if (m.rig) {
      g.setAttribute('skinIndex', new THREE.BufferAttribute(new Uint16Array(bin, m.rig.idx, m.n * 4).slice(), 4));
      g.setAttribute('skinWeight', new THREE.BufferAttribute(f32(m.rig.w, m.n * 4), 4));
      mesh = new THREE.SkinnedMesh(g, useMats);
      const bind = new Float32Array(bin, m.rig.bind, m.rig.bones.length * 16);
      const bones = [], inv = [];
      m.rig.bones.forEach((p, i) => {
        bones.push(rig.bones.get(p) || rig.root);
        inv.push(new THREE.Matrix4().set(...bind.subarray(i * 16, i * 16 + 16)));   // Unity 행 우선
      });
      mesh.bind(new THREE.Skeleton(bones, inv), new THREE.Matrix4());
      group.add(mesh);
    } else {
      mesh = new THREE.Mesh(g, useMats);
      (rig.bones.get(m.node) || rig.root).add(mesh);
    }
    mesh.frustumCulled = false;
    mesh.renderOrder = Math.max(0, ...useMats.map((x) => EYE_ORDER[x.userData.eye] || 0));
    if (names.length) mesh.updateMorphTargets();
    mesh.userData = { flags: m };
    mesh.name = m.name;
    meshes.push(mesh);
  }
  const model = new Model(id, meta, group, mats, meshes);
  model.refresh();   // 몸 자르는 고리(cut)는 자리만 쓴다 (fit.js hideCovered), 후드는 벗은 모양부터
  if (meta.fx) {
    try {
      model.fx = new FxPlayer(meta.fx, model, (name, repeat) => texture(texBase + name + '.png', model.fxTex, repeat));
    } catch (e) {   // 이펙트가 안 돼도 옷은 입는다
      console.warn('의상 이펙트를 만들지 못했습니다', id, e);
      if (model.fx) model.fx.dispose();
      model.fx = null;
    }
  }
  return model;
}

const _v = new THREE.Vector3();

/** 메시 삼각형 거르기 — drop(a, b, c) 가 참인 삼각형을 뺀다 (drop 이 없으면 처음대로 다). 처음 인덱스는 mesh.userData.index0 에
 *  두고, 같은 버퍼(처음 크기) 앞쪽에 채운 뒤 그룹 범위만 줄인다 — 버퍼를 새로 만들면 GPU 쪽 옛 버퍼가 남는다.
 *  눈썹 한쪽 숨기기(setEyeHide)와 옷에 덮인 몸·안쪽 옷 숨기기(fit.js hideCovered)가 쓴다. */
export function keepTriangles(mesh, drop = null) {
  const g = mesh.geometry, u = mesh.userData;
  if (!u.index0) u.index0 = { idx: g.index.array.slice(), groups: g.groups.map((x) => ({ ...x })) };
  const { idx, groups } = u.index0;
  if (!drop) {
    g.index.array.set(idx, 0);
    g.groups = groups.map((x) => ({ ...x }));
  } else {
    const out = [];
    g.groups = groups.map((gr) => {
      const start = out.length;
      for (let t = gr.start; t < gr.start + gr.count; t += 3) {
        const a = idx[t], b = idx[t + 1], c = idx[t + 2];
        if (!drop(a, b, c)) out.push(a, b, c);
      }
      return { start, count: out.length - start, materialIndex: gr.materialIndex };
    });
    g.index.array.set(out, 0);
  }
  g.index.needsUpdate = true;
}

/** 메시의 지금 뼈 자세에서 정점 월드 위치·법선 (+ 정점마다 스킨 행렬 선형부 9개 — 모프 옮기기용). 모프는 넣지 않는다. */
export function bakePose(mesh, withLinear = false) {
  const pos = mesh.geometry.attributes.position.array;
  const nrm = mesh.geometry.attributes.normal.array;
  const n = pos.length / 3;
  const P = new Float32Array(n * 3), N = new Float32Array(n * 3);
  const L = withLinear ? new Float32Array(n * 9) : null;
  if (!mesh.isSkinnedMesh) {
    mesh.updateWorldMatrix(true, false);
    const e = mesh.matrixWorld.elements;
    for (let i = 0; i < n; i++) {
      _v.fromArray(pos, i * 3).applyMatrix4(mesh.matrixWorld).toArray(P, i * 3);
      _v.fromArray(nrm, i * 3).transformDirection(mesh.matrixWorld).toArray(N, i * 3);
      if (L) L.set([e[0], e[1], e[2], e[4], e[5], e[6], e[8], e[9], e[10]], i * 9);
    }
    return { P, N, L };
  }
  const sk = mesh.skeleton;
  const mats = sk.bones.map((b, i) => new THREE.Matrix4().multiplyMatrices(b.matrixWorld, sk.boneInverses[i]).elements);
  const si = mesh.geometry.attributes.skinIndex.array, sw = mesh.geometry.attributes.skinWeight.array;
  const M = new Float64Array(16);
  for (let i = 0; i < n; i++) {
    M.fill(0);
    for (let k = 0; k < 4; k++) {
      const w = sw[i * 4 + k];
      if (!w) continue;
      const e = mats[si[i * 4 + k]];
      for (let j = 0; j < 16; j++) M[j] += w * e[j];
    }
    const x = pos[i * 3], y = pos[i * 3 + 1], z = pos[i * 3 + 2];
    P[i * 3] = M[0] * x + M[4] * y + M[8] * z + M[12];
    P[i * 3 + 1] = M[1] * x + M[5] * y + M[9] * z + M[13];
    P[i * 3 + 2] = M[2] * x + M[6] * y + M[10] * z + M[14];
    const a = nrm[i * 3], b = nrm[i * 3 + 1], c = nrm[i * 3 + 2];
    _v.set(M[0] * a + M[4] * b + M[8] * c, M[1] * a + M[5] * b + M[9] * c, M[2] * a + M[6] * b + M[10] * c).normalize().toArray(N, i * 3);
    if (L) L.set([M[0], M[1], M[2], M[4], M[5], M[6], M[8], M[9], M[10]], i * 9);
  }
  return { P, N, L };
}

/** 화면 — 장면·카메라·돌려 보기. onTick(dt) 은 매 프레임 그리기 전에 부른다. */
// 탭 카메라 — [대상 높이(키 비율·오프셋), 거리(m, 30도 기준), 카메라 높이 오프셋]
const SHOTS = {
  full: (h) => [h * 0.55, h * 2.3, h * 0.05],
  upper: (h) => [h * 0.72, 1.25 * h / 1.65, h * 0.02],
  face: (h) => [h - 0.13, 1.15, 0],
  feet: (h) => [0.12, 0.95 * h / 1.65, 0.33],
};
const BASE_FOV = 30;

/**
 * 3D 무대 — 카메라·바닥·그리기 고리. opts.aa: 계단 현상 줄이기 (만들 때만 정한다 — 바꾸려면 화면을 다시 연다).
 * 화면 설정(setView): scale 해상도 배율 · fps 'auto'|30|60 · pauseBlur 다른 창이면 멈춤 · wire 메시 보기 · fov 원근(도).
 */
export class Stage {
  constructor(canvas, opts = {}) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: opts.aa !== false, alpha: true, stencil: true });
    this.view = { scale: 1, fps: 'auto', pauseBlur: false, wire: false, shadow: 1024 };
    this.renderer.setPixelRatio(this.pixelRatio());
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(BASE_FOV, 1, 0.05, 50);
    this.anim = null;     // 카메라 옮기는 중 {t, dur, p0, p1, q0, q1}
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.minDistance = 0.1;
    this.controls.maxDistance = 8;
    this.controls.addEventListener('start', () => { this.anim = null; });   // 끌면 탭 카메라 옮기기는 멈춘다
    this.onTick = null;
    this.beforeRender = null;   // 그리기 바로 앞 (무대 바닥 반사 — backdrop.js)
    this.onLost = null;   // 그래픽 장치가 끊겼다 (드라이버 재시작 등)
    canvas.addEventListener('webglcontextlost', (e) => { e.preventDefault(); if (this.onLost) this.onLost(); });
    this.height = 1.6;
    this.controls.maxPolarAngle = Math.PI / 2;   // 바닥 아래로는 안 간다
    // 중립 무대 (참고한 웹 드레스룸) — 바탕 #22343f, 반지름 3m 원판 #314651, 발밑은 접촉 그림자로 둥글게 어둡게
    this.scene.background = new THREE.Color('#22343f');
    const floor = new THREE.Mesh(new THREE.CircleGeometry(3, 96), new THREE.ShaderMaterial({
      uniforms: { color: { value: new THREE.Color('#314651') } },
      vertexShader: 'varying vec3 vW; void main() { vW = (modelMatrix * vec4(position, 1.0)).xyz; gl_Position = projectionMatrix * viewMatrix * vec4(vW, 1.0); }',
      fragmentShader: `uniform vec3 color; varying vec3 vW;
        void main() {
          float reach = dot(vW.xz, vW.xz) + 0.04;
          float k = reach < 0.3 ? clamp(0.3 + pow(min(reach * 3.333333, 1.0), 0.4), 0.0, 1.0) : 1.0;
          gl_FragColor = vec4(color * k, 1.0);
          #include <colorspace_fragment>
        }`,
    }));
    floor.rotation.x = -Math.PI / 2;
    floor.userData.floor = true;
    this.scene.add(floor);
    this.floor = floor;   // 기본 원판 (무대를 고르면 숨긴다)
    // 바닥 그림자 (참고한 웹 드레스룸) — 빛 방향(LIGHT.lightVector)의 그림자 맵을 바닥 위 얇은 판에 50% 로. 캐릭터 명암은 따로라 그림자만 쓴다
    this.sun = new THREE.DirectionalLight(0xffffff, 1);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(1024, 1024);
    Object.assign(this.sun.shadow.camera, { left: -1.6, right: 1.6, top: 1.6, bottom: -1.6, near: 0.1, far: 12 });
    this.sun.shadow.bias = -0.0005;
    this.sun.shadow.normalBias = 0.01;
    this.sun.target.position.set(0, 0.9, 0);
    this.scene.add(this.sun, this.sun.target);
    this.shade = new THREE.Mesh(new THREE.PlaneGeometry(6, 6), new THREE.ShadowMaterial({ opacity: 0.5, depthWrite: false }));
    this.shade.rotation.x = -Math.PI / 2;
    this.shade.position.y = 0.001;
    this.shade.receiveShadow = true;
    this.shade.userData.floor = true;
    this.scene.add(this.shade);
    this.front(1.6);
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    this.resize();
    // 프레임: 자동은 60fps, 창이 포커스를 잃으면 30fps — 게임과 GPU 를 덜 나눠 쓰게. 창이 가려지면 브라우저가 알아서 멈춘다
    let last = performance.now();
    const tick = (now) => {
      const focus = document.hasFocus();
      const fps = this.view.fps === 'auto' ? (focus ? 60 : 30) : +this.view.fps || 60;
      if ((this.view.pauseBlur && !focus) || now - last < 1000 / fps - 1.5) { requestAnimationFrame(tick); return; }
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      LIGHT.emitTime.value = (LIGHT.emitTime.value + dt) % 3600;
      this.step(dt);
      this.controls.update();
      // 가까이 볼수록 near 를 당긴다 — 얼굴을 크게 봐도 잘리지 않게
      const near = Math.min(0.05, Math.max(0.002, this.camera.position.distanceTo(this.controls.target) * 0.025));
      if (Math.abs(near - this.camera.near) > 1e-4) { this.camera.near = near; this.camera.updateProjectionMatrix(); }
      if (this.onTick) this.onTick(dt);
      this.sun.position.copy(this.sun.target.position).addScaledVector(LIGHT.lightVector.value, 6);
      if (this.beforeRender) this.beforeRender();
      this.renderer.render(this.scene, this.camera);
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  pixelRatio() {
    return Math.min(3, (window.devicePixelRatio || 1) * this.view.scale);
  }

  /** 화면 설정 바꾸기 (주는 값만). */
  setView(v) {
    const old = { ...this.view };
    Object.assign(this.view, v);
    if (this.view.scale !== old.scale) { this.renderer.setPixelRatio(this.pixelRatio()); this.resize(); }
    if (this.view.wire !== old.wire) this.scene.traverse((o) => this.wire(o));
    if (this.view.shadow !== old.shadow) {
      const s = this.view.shadow;
      this.sun.castShadow = s > 0;
      this.shade.visible = s > 0;
      if (s > 0) {
        this.sun.shadow.mapSize.set(s, s);
        if (this.sun.shadow.map) { this.sun.shadow.map.dispose(); this.sun.shadow.map = null; }   // 새 크기로 다시 만든다
      }
    }
  }

  /** 메시 보기 — 바닥 말고 다 선으로. */
  wire(o) {
    if (!o.isMesh || o.userData.floor) return;
    for (const m of Array.isArray(o.material) ? o.material : [o.material]) if (m) m.wireframe = this.view.wire;
  }

  /** 거리 — 30도에서 정한 거리를 지금 원근(fov)에서 같은 크기로 보이게. */
  dist(d) {
    return d * Math.tan(BASE_FOV * Math.PI / 360) / Math.tan(this.camera.fov * Math.PI / 360);
  }

  /** 원근(도) — 보이는 크기는 그대로 두고 카메라를 당기거나 민다. */
  setFov(deg) {
    if (!(deg >= 10 && deg <= 90) || deg === this.camera.fov) return;
    const t = Math.tan(this.camera.fov * Math.PI / 360);
    const off = this.camera.position.clone().sub(this.controls.target);
    this.camera.fov = deg;
    this.camera.updateProjectionMatrix();
    this.anim = null;
    this.camera.position.copy(this.controls.target).addScaledVector(off, t / Math.tan(deg * Math.PI / 360));
    this.controls.maxDistance = this.dist(8);
    this.controls.update();
  }

  /** 키(m)에 맞춰 정면에서 본다. */
  front(height = this.height) {
    const h = Math.max(0.6, height);
    this.height = h;
    this.anim = null;
    const [y, d, up] = SHOTS.full(h);
    this.controls.target.set(0, y, 0);
    this.camera.position.set(0, y + up, this.dist(d));
    this.controls.update();
  }

  /** 탭 카메라 — 'full'·'upper'·'face'·'feet' 로 부드럽게 옮긴다 (정면에서). */
  shot(kind) {
    const [y, d, up] = (SHOTS[kind] || SHOTS.full)(this.height);
    const t = new THREE.Vector3(0, y, 0);
    const p = new THREE.Vector3(0, y + up, this.dist(d));
    this.anim = { t: 0, dur: 0.45, p0: this.camera.position.clone(), p1: p, q0: this.controls.target.clone(), q1: t };
  }

  /** 프레임마다 — 카메라 옮기기. */
  step(dt) {
    const a = this.anim;
    if (!a) return;
    a.t = Math.min(a.dur, a.t + dt);
    const k = a.t / a.dur, e = k * k * (3 - 2 * k);
    this.camera.position.lerpVectors(a.p0, a.p1, e);
    this.controls.target.lerpVectors(a.q0, a.q1, e);
    if (a.t >= a.dur) this.anim = null;
  }

  /** 뼈대 키(기본 자세의 머리 뼈 높이)에 맞춰 정면으로. pose: 기본 자세로 두는 함수 (몸 조절이 있으면 그것까지). */
  fit(rig, pose) {
    const y = this.measure(rig, pose);
    if (y != null) this.front(y + 0.15);
  }

  /** 카메라는 두고 키만 다시 잰다 — 명암의 발(0)~머리(1) 높이, 정면 버튼 높이. */
  measure(rig, pose) {
    if (pose) pose(); else rig.rest();
    const head = rig.find('_Head');
    if (!head) return null;
    head.updateWorldMatrix(true, false);
    const y = head.getWorldPosition(new THREE.Vector3()).y;
    LIGHT.actorHeadHeight.value = Math.max(0.5, y);
    this.height = Math.max(0.6, y + 0.15);
    return y;
  }

  resize() {
    const el = this.renderer.domElement.parentElement;
    const w = el.clientWidth, h = el.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  add(model) {
    const prep = (o) => {
      if (!o.isMesh || o.userData.noShadow) return;   // 이펙트는 그림자를 안 드리운다
      o.castShadow = true;
      if (this.view.wire) this.wire(o);
    };
    model.group.traverse(prep);
    for (const o of model.meshes) if (o.parent !== model.group) prep(o);   // 뼈에 붙은 메시(무기·장식)는 group 밖 뼈 밑에 있다
    this.scene.add(model.group);
  }

  remove(model) {
    if (!model) return;
    this.scene.remove(model.group);
    model.dispose();
  }
}
