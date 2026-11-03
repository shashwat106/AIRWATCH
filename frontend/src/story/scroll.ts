import { RefObject, useEffect, useRef } from "react";

export const clamp = (v: number, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
/** Progress of `p` through the window [from, to], as 0 to 1. */
export const span = (p: number, from: number, to: number) => clamp((p - from) / (to - from));

export const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * Calls onChange with how far the page has scrolled through a tall section, from 0 to 1.
 * Animation is tied to scroll position, so scrolling back plays it in reverse.
 * With reduced motion it reports 1 once, and every chapter shows its finished state.
 */
export function useProgress(ref: RefObject<HTMLElement>, onChange: (p: number) => void) {
  const callback = useRef(onChange);
  callback.current = onChange;
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (reducedMotion()) {
      callback.current(1);
      return;
    }
    let current = -1;
    let last = -1;
    let frame = 0;
    let before = performance.now();
    const tick = (time: number) => {
      const gap = time - before;
      before = time;
      const box = el.getBoundingClientRect();
      const near = box.bottom > -200 && box.top < window.innerHeight + 200;
      if (near) {
        const target = clamp(-box.top / Math.max(box.height - window.innerHeight, 1));
        // Time-based easing, so slow devices keep up with the scrollbar.
        current = current < 0 ? target : current + (target - current) * (1 - Math.exp(-gap / 80));
        if (Math.abs(target - current) < 0.0005) current = target;
        if (current !== last) {
          last = current;
          callback.current(current);
        }
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [ref]);
}
