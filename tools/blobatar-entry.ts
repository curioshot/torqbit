/**
 * Bundle entry for the island widget's Blobatar face.
 * Bundled with esbuild to assets/blobatar/blobatar-face.js (IIFE).
 * Upstream: https://github.com/Alain00/blobatar (MIT), packages/blobatar/src.
 */
import { _parts } from "/tmp/opencode/blobatar/packages/blobatar/src/blobatar";
import * as EX from "/tmp/opencode/blobatar/packages/blobatar/src/expression";
import { gaze, type Gaze } from "/tmp/opencode/blobatar/packages/blobatar/src/gaze";

const EXPRESSIONS: Record<string, any> = {
  idle: EX.idle,
  happy: EX.happy,
  sad: EX.sad,
  mad: EX.mad,
  surprised: EX.surprised,
  wink: EX.wink,
  sleepy: EX.sleepy,
  smug: EX.smug,
  unsure: EX.unsure,
  scared: EX.scared,
  love: EX.love,
  shy: EX.shy,
  sick: EX.sick,
  thinking: EX.thinking,
};

interface MountOpts {
  name: string;
  expression?: string;
  background?: boolean | "square" | "circle" | "squircle";
  travel?: number;
  gaze?: boolean;
}

let el: HTMLElement | null = null;
let svg: SVGSVGElement | null = null;
let g: SVGGElement | null = null;
let bgPath: SVGPathElement | null = null;
let driver: Gaze | null = null;
let state: Required<Pick<MountOpts, "name">> & {
  expression: string;
  background: boolean | "square" | "circle" | "squircle";
  travel: number;
} = { name: "island-bot", expression: "idle", background: false, travel: 4 };

function compute() {
  const expr = EXPRESSIONS[state.expression] ?? EXPRESSIONS.idle;
  return _parts(state.name, {
    animate: "always",
    expression: expr,
    background: state.background,
  } as any);
}

function applyVars(vars: Record<string, string>) {
  if (!svg) return;
  for (const k of Object.keys(vars)) svg.style.setProperty(k, vars[k]);
}

export function mount(target: HTMLElement, opts: MountOpts) {
  el = target;
  state = {
    name: opts.name || "island-bot",
    expression: opts.expression || "idle",
    background: opts.background ?? false,
    travel: opts.travel ?? 4,
  };
  const parts: any = compute();
  el.innerHTML = "";
  const ns = "http://www.w3.org/2000/svg";
  svg = document.createElementNS(ns, "svg") as SVGSVGElement;
  svg.setAttribute("viewBox", "0 0 100 100");
  svg.setAttribute("width", "100%");
  svg.setAttribute("height", "100%");
  svg.setAttribute("aria-hidden", "true");
  svg.style.display = "block";
  svg.style.overflow = "visible";
  svg.style.setProperty("--mo-track-travel", `${state.travel}px`);
  applyVars(parts.vars || {});
  if (parts.bg) {
    bgPath = document.createElementNS(ns, "path") as SVGPathElement;
    bgPath.setAttribute("d", parts.bg.d);
    bgPath.setAttribute("fill", parts.bg.fill);
    svg.appendChild(bgPath);
  }
  g = document.createElementNS(ns, "g") as SVGGElement;
  g.setAttribute("class", parts.cls || "");
  g.innerHTML = parts.inner || "";
  svg.appendChild(g);
  el.appendChild(svg);
  if (driver) { try { driver.stop(); } catch {} driver = null; }
  if (opts.gaze !== false) {
    try { driver = gaze(svg, { target: "pointer" }); } catch {}
  }
  return true;
}

/** Morph to a new expression without rebuilding the subtree (CSS transition). */
export function setExpression(name: string) {
  if (!svg || !g) return false;
  state.expression = name;
  const parts: any = compute();
  g.setAttribute("class", parts.cls || "");
  applyVars(parts.vars || {});
  if (bgPath && parts.bg) {
    bgPath.setAttribute("d", parts.bg.d);
    bgPath.setAttribute("fill", parts.bg.fill);
  }
  return true;
}

export function setName(name: string) {
  state.name = name || "island-bot";
  if (!el) return false;
  const keepExpr = state.expression;
  const keepBg = state.background;
  mount(el, { name: state.name, expression: keepExpr, background: keepBg, travel: state.travel, gaze: !!driver });
  return true;
}

export function setBackground(bg: boolean | "square" | "circle" | "squircle") {
  state.background = bg;
  if (!el) return false;
  mount(el, { name: state.name, expression: state.expression, background: bg, travel: state.travel, gaze: !!driver });
  return true;
}

export function lookAt(x: number | null, y: number | null) {
  try {
    if (driver) {
      if (x === null || y === null) driver.lookAt(null);
      else driver.lookAt({ x, y } as any);
    }
  } catch {}
}

export const EXPRESSION_NAMES = Object.keys(EXPRESSIONS);

// UMD-ish export: works in browser (window) and node (globalThis, for seed previews).
const root: any = typeof window !== "undefined" ? window : globalThis;
root.BlobatarFace = { mount, setExpression, setName, setBackground, lookAt, EXPRESSION_NAMES };
