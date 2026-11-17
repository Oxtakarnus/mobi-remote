// 무대와 조명 — 참고한 웹 드레스룸처럼 무대(기본 원판 · 게임 환생 무대)와 빛(환생 · 야외 한낮 · 야외 밤)을 따로 고른다.
//   빛   light:presets (mabi/dress/stage.py) — direction · direct · indirect(캐릭터 빛 character_light 가 있으면 그것)를
//        캐릭터 명암(LIGHT)에, shadow_strength 를 바닥 그림자 진하기에. 기본 원판은 환생 빛이 아니면 direct + indirect 를 곱한다.
//   무대 stage:rebirth — 그릇(SimpleLit: 텍스처 × 정점 색 × (SH + 해)) + 바닥 원판(평면 반사: 캐릭터를 거울 카메라로 그려 비추고,
//        빈 곳은 반사 프로브 큐브맵). 바탕은 같은 큐브맵 — 게임 별 하늘을 담은 반사 프로브라 별 돔 대신 쓴다.
//        무대 조명(점광·스포트)은 캐릭터 명암에 넣지 않았다.
// 무대 좌표는 Unity 원래 값 — 다른 모델처럼 Rig 루트에서 x 를 뒤집는다. 바닥 원판 높이가 0 이 되게 무대를 내린다.
import * as THREE from './vendor/three.module.min.js';
import { LIGHT, Rig } from './viewer.js';

export const SCENES = [['neutral', '기본'], ['rebirth', '환생 무대']];
export const LIGHTS = [['rebirth', '환생'], ['noon', '한낮'], ['night', '밤']];

const NEUTRAL_BG = new THREE.Color('#22343f');
const NEUTRAL_FLOOR = new THREE.Color('#314651');
const MIRROR_SCALE = 0.75;   // 반사 그림 해상도 (화면 대비)

// 무대 셰이더 공용 — SH(뷰어 축, stage.py eval_sh 와 같은 식) · 해
const LIT = `
uniform vec3 lightVector, directRGB;
uniform vec3 shC, shX, shY, shZ, shXY, shYZ, shZZ, shXZ, shCC;
vec3 sh(vec3 n) {
  return shC + shX * n.x + shY * n.y + shZ * n.z + shXY * n.x * n.y + shYZ * n.y * n.z + shZZ * n.z * n.z
       + shXZ * n.x * n.z + shCC * (n.x * n.x - n.y * n.y);
}
vec3 lit(vec3 n) { return max(sh(n), 0.0) + directRGB * max(dot(n, normalize(lightVector)), 0.0); }
`;

const VERT = `
attribute vec4 vcol;
uniform vec4 st;
uniform mat4 mirrorMatrix;
varying vec2 vUv;
varying vec4 vCol, vMirror;
varying vec3 vN, vW;
void main() {
  vUv = uv * st.xy + st.zw;
  vCol = vcol;
  vN = normalize(mat3(modelMatrix) * normal);
  vec4 w = modelMatrix * vec4(position, 1.0);
  vW = w.xyz;
  vMirror = mirrorMatrix * w;
  gl_Position = projectionMatrix * viewMatrix * w;
}`;

const SIMPLE = `
uniform sampler2D map;
uniform vec3 baseColor;
uniform float vcw;
varying vec2 vUv;
varying vec4 vCol, vMirror;
varying vec3 vN, vW;
${LIT}
void main() {
  vec3 n = normalize(vN) * (gl_FrontFacing ? 1.0 : -1.0);
  vec3 albedo = texture2D(map, vUv).rgb * baseColor * mix(vec3(1.0), vCol.rgb, vcw);
  gl_FragColor = vec4(albedo * lit(n), 1.0);
  #include <colorspace_fragment>
}`;

const REFLECT = `
uniform sampler2D map, mirror;
uniform samplerCube cube;
uniform vec3 baseColor, adjust;
uniform float ratio, useMirror;
varying vec2 vUv;
varying vec4 vCol, vMirror;
varying vec3 vN, vW;
${LIT}
vec3 fromSrgb(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(0.04045, c)); }
void main() {
  vec3 n = vec3(0.0, 1.0, 0.0);
  vec3 base = texture2D(map, vUv).rgb * baseColor * lit(n);
  vec3 r = reflect(normalize(vW - cameraPosition), n);
  vec3 env = textureCube(cube, vec3(-r.x, r.y, r.z)).rgb * adjust;   // 큐브맵은 Unity 축 — x 를 되돌린다
  if (useMirror > 0.5) {
    vec4 m = texture2DProj(mirror, vMirror);   // 캐릭터 셰이더가 sRGB 로 써 둔 값
    env = mix(env, fromSrgb(m.rgb), m.a);
  }
  gl_FragColor = vec4(mix(base, env, ratio), 1.0);
  #include <colorspace_fragment>
}`;

const SH_KEYS = { shC: 'constant', shX: 'x', shY: 'y', shZ: 'z', shXY: 'xy', shYZ: 'yz', shZZ: 'zz', shXZ: 'xz', shCC: 'c' };
const loader = new THREE.TextureLoader();
const _v2 = new THREE.Vector2();
const _p = new THREE.Vector3();
const _t = new THREE.Vector3();
const _c = new THREE.Color();
const BIAS = new THREE.Matrix4().set(0.5, 0, 0, 0.5, 0, 0.5, 0, 0.5, 0, 0, 0.5, 0.5, 0, 0, 0, 1);

/** 무대·조명. stage: viewer Stage, load(id) → 캐시 json 주소. */
export class Backdrop {
  constructor(stage, load) {
    this.stage = stage;
    this.load = load;
    this.want = { scene: 'neutral', light: 'rebirth', reflect: true };
    this.presets = null;     // 빛 프리셋 {id: {...}}
    this.set3d = null;       // 환생 무대 {group, cube, mats, ready} (처음 고를 때 읽는다)
    this.presetsP = null;    // 빛 프리셋 읽는 중 (못 읽으면 비워 다음에 다시)
    this.stageP = null;      // 무대 읽는 중·읽은 것 (못 읽으면 null — 기본 원판으로 둔다, 다시 안 읽는다)
    // 반사 그림 — three 는 렌더 타깃에 그릴 때 선형 출력용 셰이더 프로그램을 따로 만든다 (재질마다 한 벌 더, D3D 컴파일이 느려
    // 처음 불러올 때 몇십 초 멈춘다). XR 타깃 표시 + sRGB 텍스처면 화면과 같은 프로그램을 쓴다. 캐릭터 셰이더가 sRGB 로 쓴 값을
    // 하드웨어가 한 번 더 인코딩해 담고 읽을 때 풀어 주므로, 읽은 값은 캐릭터 셰이더가 쓴 sRGB 값 그대로다.
    this.rt = new THREE.WebGLRenderTarget(1, 1);
    this.rt.texture.colorSpace = THREE.SRGBColorSpace;
    this.rt.isXRRenderTarget = true;
    this.mcam = new THREE.PerspectiveCamera();
    this.mirrorMatrix = { value: new THREE.Matrix4() };
    stage.beforeRender = () => this.renderMirror();
  }

  /** 고른 것 바꾸기 (주는 값만). 빛·무대는 처음 쓸 때 꺼낸다. */
  async set(v) {
    Object.assign(this.want, v);
    const { scene, light } = this.want;
    // 읽는 약속은 하나만 — 읽는 사이 설정을 또 바꿔도 두 번 읽지 않는다
    if (!this.presetsP) {
      this.presetsP = this.load('light:presets').then((u) => fetch(u)).then((r) => r.json()).then((d) => d.presets || {},
        (e) => { console.warn('조명 프리셋', e); this.presetsP = null; return null; });
    }
    if (scene === 'rebirth' && !this.stageP) this.stageP = this.loadStage().catch((e) => { console.warn('환생 무대', e); return null; });
    this.presets = (await this.presetsP) || this.presets;
    if (scene === 'rebirth') this.set3d = await this.stageP;
    if (this.want.scene !== scene || this.want.light !== light) return;   // 그사이 또 바뀌었다
    this.apply();
  }

  apply() {
    const st = this.stage;
    const p = (this.presets || {})[this.want.light] || null;
    if (p) {
      const cl = p.character_light || {};
      LIGHT.lightVector.value.fromArray(p.direction).normalize();
      LIGHT.directRGB.value.fromArray(cl.direct || p.direct);
      LIGHT.ambientRGB.value.fromArray(cl.indirect || p.indirect);
      st.shade.material.opacity = 0.5 * Math.min(1, Math.max(0, p.shadow_strength ?? 1));
    }
    const k = p && this.want.light !== 'rebirth' ? p : null;   // 기본 원판 — 환생 빛이면 그대로, 아니면 빛 세기를 곱한다
    st.floor.material.uniforms.color.value.copy(NEUTRAL_FLOOR)
      .multiply(k ? _c.setRGB(k.direct[0] + k.indirect[0], k.direct[1] + k.indirect[1], k.direct[2] + k.indirect[2]) : _c.setRGB(1, 1, 1));
    const on = this.want.scene === 'rebirth' && !!this.set3d;
    st.floor.visible = !on;
    if (this.set3d) this.set3d.group.visible = on;
    st.scene.background = on ? this.set3d.cube : NEUTRAL_BG;
  }

  /** 환생 무대 메시·재질을 읽어 장면에 (숨긴 채). */
  async loadStage() {
    const url = await this.load('stage:rebirth');
    const meta = await (await fetch(url)).json();
    const dir = url.slice(0, url.lastIndexOf('/') + 1);
    const bin = await (await fetch(dir + meta.bin)).arrayBuffer();
    const texBase = dir + '../tex/';
    const info = meta.stage || {};
    const sh = (info.lighting || {}).ambient_sh || null;
    const tex = (name, srgb = true) => {
      const t = loader.load(texBase + name + '.png');
      t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
      t.wrapS = t.wrapT = THREE.RepeatWrapping;
      t.anisotropy = 4;
      return t;
    };
    let cube = null;
    const mats = meta.materials.map((m) => {
      const uniforms = {
        ...LIGHT,
        map: { value: m.tex ? tex(m.tex) : null },
        st: { value: new THREE.Vector4(...((m.st || {})._BaseMap || [1, 1, 0, 0])) },
        baseColor: { value: new THREE.Color().setRGB(...((m.colors || {})._BaseColor || [1, 1, 1]).slice(0, 3), THREE.SRGBColorSpace) },
        vcw: { value: (m.floats || {})._VertexColorWeight ?? 1 },
        mirrorMatrix: this.mirrorMatrix,
      };
      for (const [u, key] of Object.entries(SH_KEYS)) uniforms[u] = { value: new THREE.Vector3(...((sh && sh[key]) || [0, 0, 0])) };
      if (!sh) uniforms.shC.value.copy(LIGHT.ambientRGB.value);   // SH 가 없으면 캐릭터 간접광 세기로 고르게
      const c = (m.cubes || {})._LowOptionCubeTexture;
      const reflect = !!m.reflect && !!c;
      if (reflect) {
        if (!cube) {
          cube = new THREE.CubeTextureLoader().load(c.faces.map((f) => texBase + f + '.png'));
          cube.colorSpace = THREE.SRGBColorSpace;
        }
        const f = m.floats || {}, col = m.colors || {};
        Object.assign(uniforms, {
          cube: { value: cube },
          mirror: { value: this.rt.texture },
          useMirror: { value: 1 },
          ratio: { value: f._LowOptionReflectionRatio ?? f._ReflectionRatio ?? 0.5 },
          adjust: { value: new THREE.Color().setRGB(...(col._LowOptionAdjustColor || [1, 1, 1]).slice(0, 3)) },
        });
      }
      const mat = new THREE.ShaderMaterial({ uniforms, vertexShader: VERT, fragmentShader: reflect ? REFLECT : SIMPLE });
      mat.userData.reflect = reflect;
      return mat;
    });
    const rig = new Rig();
    rig.add(meta.skeleton || []);
    const f32 = (off, n) => new Float32Array(bin, off, n).slice();
    for (const m of meta.meshes) {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(f32(m.pos, m.n * 3), 3));
      g.setAttribute('normal', new THREE.BufferAttribute(f32(m.nrm, m.n * 3), 3));
      g.setAttribute('uv', new THREE.BufferAttribute(f32(m.uv, m.n * 2), 2));
      g.setAttribute('vcol', m.col !== undefined ? new THREE.BufferAttribute(f32(m.col, m.n * 4), 4)
        : new THREE.BufferAttribute(new Float32Array(m.n * 4).fill(1), 4));
      const total = m.groups.reduce((s, x) => s + x.count, 0);
      const idx = new Uint32Array(total);
      let at = 0;
      const use = [];
      m.groups.forEach((x, gi) => {
        idx.set(new Uint32Array(bin, x.off, x.count), at);
        g.addGroup(at, x.count, gi);
        use.push(mats[x.mat]);
        at += x.count;
      });
      g.setIndex(new THREE.BufferAttribute(idx, 1));
      const mesh = new THREE.Mesh(g, use);
      mesh.userData.floor = true;   // 메시 보기(선)에서 뺀다
      mesh.receiveShadow = false;
      (rig.bones.get(m.node) || rig.root).add(mesh);
    }
    const group = rig.root;
    group.name = 'stage:rebirth';
    group.position.y = -(info.floor_y || 0);
    group.visible = false;
    this.stage.scene.add(group);
    if (!cube) cube = NEUTRAL_BG;
    return { group, cube, mats };
  }

  /** 프레임마다 — 환생 무대가 보이면 캐릭터를 거울 카메라로 반사 그림에 그린다 (바닥 원판이 읽는다). */
  renderMirror() {
    const s = this.set3d;
    const on = !!s && s.group.visible;
    if (s) for (const m of s.mats) if (m.userData.reflect) m.uniforms.useMirror.value = on && this.want.reflect ? 1 : 0;
    if (!on || !this.want.reflect) return;
    const st = this.stage, r = st.renderer, cam = st.camera;
    r.getDrawingBufferSize(_v2);
    const w = Math.max(1, Math.round(_v2.x * MIRROR_SCALE)), h = Math.max(1, Math.round(_v2.y * MIRROR_SCALE));
    if (this.rt.width !== w || this.rt.height !== h) this.rt.setSize(w, h);
    // 바닥(y = 0)에 비친 카메라 — 위치·바라보는 점·위쪽을 뒤집는다 (three Reflector 와 같은 방법, 바닥 아래는 그리지 않으니 비스듬한 near 면은 생략)
    cam.updateMatrixWorld();
    const mc = this.mcam;
    _p.setFromMatrixPosition(cam.matrixWorld);
    _t.set(0, 0, -1).applyQuaternion(cam.quaternion).add(_p);
    mc.position.set(_p.x, -_p.y, _p.z);
    mc.up.set(0, 1, 0).applyQuaternion(cam.quaternion);
    mc.up.y = -mc.up.y;
    mc.lookAt(_t.x, -_t.y, _t.z);
    mc.near = cam.near;
    mc.far = cam.far;
    mc.updateMatrixWorld();
    mc.projectionMatrix.copy(cam.projectionMatrix);
    mc.projectionMatrixInverse.copy(cam.projectionMatrixInverse);
    this.mirrorMatrix.value.copy(BIAS).multiply(mc.projectionMatrix).multiply(mc.matrixWorldInverse);
    // 무대·바닥·그림자 판은 빼고 캐릭터만, 바탕은 비워(알파 0) 빈 곳은 큐브맵이 보이게
    const hide = [s.group, st.floor, st.shade].filter((o) => o.visible);
    for (const o of hide) o.visible = false;
    const bg = st.scene.background;
    st.scene.background = null;
    const auto = r.shadowMap.autoUpdate;
    r.shadowMap.autoUpdate = false;
    const old = r.getRenderTarget();
    r.getClearColor(_c);
    const alpha = r.getClearAlpha();
    r.setRenderTarget(this.rt);
    r.setClearColor(0x000000, 0);
    r.clear();
    r.render(st.scene, mc);
    r.setRenderTarget(old);
    r.setClearColor(_c, alpha);
    r.shadowMap.autoUpdate = auto;
    st.scene.background = bg;
    for (const o of hide) o.visible = true;
  }
}
