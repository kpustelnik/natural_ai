// PNG of the 3D view (S key, or the camera button): the WebGL canvas plus the HTML labels
// drawn over it (building ids, room labels, the split-view captions), at device resolution.

import { app, toast } from "../state/app";
import { registry } from "./registry";

function stamp(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

/** Draw the visible HTML labels over the copy, approximating their CSS boxes. */
function drawLabels(ctx: CanvasRenderingContext2D, canvas: HTMLCanvasElement, scale: number): void {
  const base = canvas.getBoundingClientRect();
  const labels = document.querySelectorAll<HTMLElement>(".labels-layer .label, .split-label");
  for (const el of labels) {
    const r = el.getBoundingClientRect();
    if (!r.width || r.right < base.left || r.left > base.right || r.bottom < base.top || r.top > base.bottom) continue;
    const css = getComputedStyle(el);
    if (css.visibility === "hidden" || css.display === "none" || Number(css.opacity) === 0) continue;
    const x = (r.left - base.left) * scale;
    const y = (r.top - base.top) * scale;
    ctx.globalAlpha = Number(css.opacity) || 1;
    ctx.fillStyle = css.backgroundColor;
    ctx.strokeStyle = css.borderTopColor;
    ctx.lineWidth = (parseFloat(css.borderTopWidth) || 0) * scale;
    ctx.beginPath();
    ctx.roundRect(x, y, r.width * scale, r.height * scale, (parseFloat(css.borderTopLeftRadius) || 0) * scale);
    ctx.fill();
    if (ctx.lineWidth) ctx.stroke();
    ctx.fillStyle = css.color;
    ctx.font = `${css.fontWeight} ${parseFloat(css.fontSize) * scale}px ${css.fontFamily}`;
    ctx.textBaseline = "middle";
    ctx.fillText(el.textContent ?? "", x + (parseFloat(css.paddingLeft) || 0) * scale, y + (r.height * scale) / 2);
  }
  ctx.globalAlpha = 1;
}

export function screenshot(): void {
  const canvas = registry.canvas;
  if (!canvas) return;
  const out = document.createElement("canvas");
  out.width = canvas.width;
  out.height = canvas.height;
  const ctx = out.getContext("2d");
  if (!ctx) return;
  ctx.drawImage(canvas, 0, 0); // the context keeps its drawing buffer (preserveDrawingBuffer)
  drawLabels(ctx, canvas, canvas.width / canvas.clientWidth);
  out.toBlob((blob) => {
    if (!blob) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `metro-agh-${app.get().workspace}-${stamp()}.png`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    toast(`Saved ${a.download}`);
  }, "image/png");
}
