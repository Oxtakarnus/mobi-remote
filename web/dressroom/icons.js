// 목록 칸 아이콘 — 보이는 칸만 두 개씩 받아 온다 (옷 꺼내기가 밀리지 않게). 받은 주소는 이번 창에서만 기억한다.
import { rpc } from './ui.js';

const AT_ONCE = 2;

export class IconLoader {
  /** root: 칸들이 든 스크롤 상자 — 그 안의 .tile[data-icon] 을 본다. */
  constructor(root) {
    this.root = root;
    this.urls = new Map();   // id → url | null (아이콘 없음)
    this.want = [];
    this.running = 0;
    this.seen = null;
  }

  /** 받아 둔 주소 (아직 모르면 undefined, 없으면 null). */
  get(id) {
    return this.urls.get(id);
  }

  /** 목록을 새로 그린 뒤 — 아직 주소가 없는 칸을 보이는 대로 받는다. */
  watch() {
    if (!this.seen) {
      this.seen = new IntersectionObserver((es) => {
        for (const e of es) {
          if (!e.isIntersecting) continue;
          this.seen.unobserve(e.target);
          const id = e.target.dataset.icon;
          if (!this.urls.has(id) && !this.want.includes(id)) this.want.push(id);
        }
        this.pump();
      }, { root: this.root, rootMargin: '120px' });
    }
    this.seen.disconnect();
    this.want.length = 0;
    for (const el of this.root.querySelectorAll('.tile[data-icon]')) if (!this.urls.has(el.dataset.icon)) this.seen.observe(el);
  }

  pump() {
    while (this.running < AT_ONCE && this.want.length) {
      const id = this.want.shift();
      this.running++;
      rpc('icon', id).then((r) => (r && !r.error ? r.url : null), () => null).then((url) => {
        this.urls.set(id, url);
        this.running--;
        if (url) for (const img of this.root.querySelectorAll(`.tile[data-icon="${CSS.escape(id)}"] img`)) img.src = url;
        this.pump();
      });
    }
  }
}
