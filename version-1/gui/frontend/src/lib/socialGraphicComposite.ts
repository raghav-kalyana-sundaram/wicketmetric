/**
 * Letterbox a captured chart/table onto a fixed social aspect ratio: poster-style layout,
 * optional hero strip with player avatars, framed content, watermark.
 */

import { hueFromId, initialsFromName } from "@/lib/avatarVisual";

export type SocialAspect = "square" | "landscape" | "portrait";

const ASPECT_DIMENSIONS: Record<SocialAspect, { w: number; h: number }> = {
  square: { w: 1080, h: 1080 },
  landscape: { w: 1920, h: 1080 },
  portrait: { w: 1080, h: 1920 },
};

export const SOCIAL_ASPECT_LABELS: Record<
  SocialAspect,
  { id: SocialAspect; label: string; hint: string }
> = {
  square: { id: "square", label: "Square", hint: "Instagram" },
  landscape: { id: "landscape", label: "Landscape", hint: "X / Twitter" },
  portrait: { id: "portrait", label: "Portrait", hint: "Stories / TikTok" },
};

/** Who appears on the graphic hero (photos optional — see `photoUrl` JSDoc). */
export interface SocialGraphicSubject {
  id: string;
  name: string;
  /**
   * Optional headshot. Use URLs that allow CORS (`Access-Control-Allow-Origin`) or same-origin;
   * otherwise the compositor falls back to initials. Map from API `photo_url` when available.
   */
  photoUrl?: string | null;
}

export interface CompositeSocialGraphicOptions {
  siteUrl: string;
  brandName?: string;
  subjects?: SocialGraphicSubject[];
  /** Optional line under avatars (e.g. section title). */
  subtitle?: string;
}

function loadImageFromBlob(blob: Blob): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not decode capture for compositing"));
    };
    img.src = url;
  });
}

function tryLoadPhoto(url: string | null | undefined): Promise<HTMLImageElement | null> {
  const u = url?.trim();
  if (!u) return Promise.resolve(null);
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = u;
  });
}

export function getPublicSiteUrl(): string {
  const fromEnv = import.meta.env.VITE_SITE_URL?.trim();
  if (fromEnv) return fromEnv.replace(/\/$/, "");
  if (typeof window !== "undefined") return window.location.origin;
  return "";
}

export function displaySiteUrlForWatermark(fullUrl: string): string {
  return fullUrl.replace(/^https?:\/\//, "");
}

function drawBackgroundGradient(ctx: CanvasRenderingContext2D, w: number, h: number) {
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, "#0a0a0a");
  g.addColorStop(0.45, "#060606");
  g.addColorStop(1, "#030303");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);

  const rg = ctx.createRadialGradient(
    w * 0.85,
    h * 0.08,
    0,
    w * 0.85,
    h * 0.08,
    Math.max(w, h) * 0.55,
  );
  rg.addColorStop(0, "rgba(255, 255, 255, 0.055)");
  rg.addColorStop(0.5, "rgba(255, 255, 255, 0.018)");
  rg.addColorStop(1, "rgba(255, 255, 255, 0)");
  ctx.fillStyle = rg;
  ctx.fillRect(0, 0, w, h);
}

function roundRectPath(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.lineTo(x + w - rr, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + rr);
  ctx.lineTo(x + w, y + h - rr);
  ctx.quadraticCurveTo(x + w, y + h, x + w - rr, y + h);
  ctx.lineTo(x + rr, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - rr);
  ctx.lineTo(x, y + rr);
  ctx.quadraticCurveTo(x, y, x + rr, y);
  ctx.closePath();
}

function truncateText(
  ctx: CanvasRenderingContext2D,
  text: string,
  maxWidth: number,
): string {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let t = text;
  while (t.length > 1 && ctx.measureText(`${t}…`).width > maxWidth) {
    t = t.slice(0, -1);
  }
  return t.length <= 1 ? t : `${t}…`;
}

async function drawAvatarCircle(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  r: number,
  subject: SocialGraphicSubject,
  photo: HTMLImageElement | null,
) {
  ctx.save();
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.clip();

  if (photo && photo.naturalWidth > 0) {
    const iw = photo.naturalWidth;
    const ih = photo.naturalHeight;
    const scale = Math.max((2 * r) / iw, (2 * r) / ih);
    const dw = iw * scale;
    const dh = ih * scale;
    const dx = cx - dw / 2;
    const dy = cy - dh / 2;
    ctx.drawImage(photo, dx, dy, dw, dh);
  } else {
    ctx.fillStyle = hueFromId(subject.id);
    ctx.fillRect(cx - r - 2, cy - r - 2, 2 * r + 4, 2 * r + 4);
    ctx.fillStyle = "rgba(248, 250, 252, 0.94)";
    ctx.font = `600 ${Math.max(12, Math.round(r * 0.78))}px system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(initialsFromName(subject.name), cx, cy + 1);
  }
  ctx.restore();

  ctx.strokeStyle = "rgba(255, 255, 255, 0.22)";
  ctx.lineWidth = Math.max(2, r * 0.07);
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.stroke();
}

async function drawHeroStrip(
  ctx: CanvasRenderingContext2D,
  w: number,
  pad: number,
  subjects: SocialGraphicSubject[],
  subtitle: string | undefined,
  minDim: number,
): Promise<number> {
  const n = Math.min(subjects.length, 4);
  if (n === 0) return 0;

  const baseR =
    n <= 2
      ? Math.round(minDim * 0.048)
      : Math.round(minDim * 0.036);
  const gap = Math.round(baseR * 0.35);
  const nameFont = Math.max(13, Math.round(minDim * 0.018));
  const vsFont = Math.max(12, Math.round(minDim * 0.016));

  const photos = await Promise.all(
    subjects.slice(0, n).map((s) => tryLoadPhoto(s.photoUrl)),
  );

  const nameBelowY = (cx: number, cy: number, name: string) => {
    ctx.save();
    ctx.font = `500 ${nameFont}px system-ui, sans-serif`;
    ctx.fillStyle = "rgba(226, 232, 240, 0.92)";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const maxW = baseR * 2.8;
    const label = truncateText(ctx, name, maxW);
    ctx.fillText(label, cx, cy + baseR + gap);
    ctx.restore();
  };

  let heroBottom = pad;

  if (n === 2) {
    const sep = Math.round(minDim * 0.1);
    const cx0 = w / 2 - sep;
    const cx1 = w / 2 + sep;
    const cy = pad + baseR + 8;

    await drawAvatarCircle(ctx, cx0, cy, baseR, subjects[0], photos[0]);
    await drawAvatarCircle(ctx, cx1, cy, baseR, subjects[1], photos[1]);

    ctx.save();
    ctx.font = `600 ${vsFont}px system-ui, sans-serif`;
    ctx.fillStyle = "rgba(148, 163, 184, 0.75)";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("vs", w / 2, cy);
    ctx.restore();

    nameBelowY(cx0, cy, subjects[0].name);
    nameBelowY(cx1, cy, subjects[1].name);

    heroBottom = cy + baseR + gap + nameFont + 6;
  } else {
    const step = 2 * baseR + gap * 2;
    const totalW = n * step - gap * 2;
    let x0 = (w - totalW) / 2 + baseR;
    const cy = pad + baseR + 8;

    for (let i = 0; i < n; i++) {
      const cx = x0 + i * step;
      await drawAvatarCircle(ctx, cx, cy, baseR, subjects[i], photos[i]);
      nameBelowY(cx, cy, subjects[i].name);
    }
    heroBottom = cy + baseR + gap + nameFont + 6;
  }

  if (subtitle?.trim()) {
    ctx.save();
    const subSize = Math.max(11, Math.round(minDim * 0.014));
    ctx.font = `400 ${subSize}px system-ui, sans-serif`;
    ctx.fillStyle = "rgba(148, 163, 184, 0.85)";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const st = truncateText(ctx, subtitle.trim(), w - pad * 4);
    ctx.fillText(st, w / 2, heroBottom);
    heroBottom += subSize + 10;
    ctx.restore();
  } else {
    heroBottom += 4;
  }

  return heroBottom - pad;
}

function drawWatermark(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  brand: string,
  urlToDraw: string,
) {
  const margin = Math.round(Math.min(w, h) * 0.024);
  const logoSize = Math.round(Math.min(w, h) * 0.03);
  const line1 = Math.max(16, Math.round(Math.min(w, h) * 0.019));
  const line2 = Math.max(12, Math.round(line1 * 0.78));

  ctx.font = `600 ${line1}px system-ui, sans-serif`;
  const brandW = ctx.measureText(brand).width;
  ctx.font = `400 ${line2}px system-ui, sans-serif`;
  const urlW = ctx.measureText(urlToDraw).width;
  const textW = Math.max(brandW, urlW);
  const gap = 10;
  const rightX = w - margin;
  const textLeft = rightX - textW;
  const logoLeft = textLeft - gap - logoSize;
  const blockTop = h - margin - Math.max(logoSize, line1 + line2 + 6);

  ctx.fillStyle = "rgba(255, 255, 255, 0.1)";
  const tileR = Math.max(5, logoSize * 0.2);
  roundRectPath(ctx, logoLeft, blockTop, logoSize, logoSize, tileR);
  ctx.fill();

  ctx.fillStyle = "rgba(244, 244, 245, 0.95)";
  ctx.font = `600 ${Math.round(logoSize * 0.4)}px system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("CM", logoLeft + logoSize / 2, blockTop + logoSize / 2 + 1);

  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  ctx.fillStyle = "rgba(244, 244, 245, 0.92)";
  ctx.font = `600 ${line1}px system-ui, sans-serif`;
  ctx.fillText(brand, textLeft, blockTop + 2);
  ctx.fillStyle = "rgba(161, 161, 170, 0.88)";
  ctx.font = `400 ${line2}px system-ui, sans-serif`;
  ctx.fillText(urlToDraw, textLeft, blockTop + line1 + 5);
}

/**
 * Composite base raster: gradient background, optional hero (avatars), framed chart, watermark.
 */
export async function compositeSocialGraphic(
  baseImageBlob: Blob,
  aspect: SocialAspect,
  options: CompositeSocialGraphicOptions,
): Promise<Blob> {
  const { w, h } = ASPECT_DIMENSIONS[aspect];
  const chartImg = await loadImageFromBlob(baseImageBlob);
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas 2D not available");

  const minDim = Math.min(w, h);
  const pad = Math.round(minDim * 0.032);
  const footerH = Math.round(minDim * 0.072);

  drawBackgroundGradient(ctx, w, h);

  const subjects = options.subjects?.filter(Boolean) ?? [];
  const heroUsedH =
    subjects.length > 0
      ? await drawHeroStrip(ctx, w, pad, subjects, options.subtitle, minDim)
      : options.subtitle?.trim()
        ? (() => {
            ctx.save();
            const subSize = Math.max(12, Math.round(minDim * 0.02));
            ctx.font = `500 ${subSize}px system-ui, sans-serif`;
            ctx.fillStyle = "rgba(226, 232, 240, 0.9)";
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            const st = truncateText(
              ctx,
              options.subtitle!.trim(),
              w - pad * 4,
            );
            ctx.fillText(st, w / 2, pad + 4);
            ctx.restore();
            return subSize + pad + 16;
          })()
        : 0;

  const frameTop = pad + heroUsedH + (heroUsedH > 0 ? pad * 0.5 : 0);
  const frameH = h - frameTop - footerH - Math.round(pad * 0.65);
  const frameW = w - 2 * pad;
  const frameX = pad;
  const frameR = Math.round(minDim * 0.022);

  roundRectPath(ctx, frameX, frameTop, frameW, frameH, frameR);
  ctx.fillStyle = "#121a26";
  ctx.fill();
  ctx.strokeStyle = "rgba(148, 163, 184, 0.22)";
  ctx.lineWidth = Math.max(1, Math.round(minDim * 0.002));
  ctx.stroke();

  const innerPad = Math.round(minDim * 0.022);
  const innerX = frameX + innerPad;
  const innerY = frameTop + innerPad;
  const innerW = frameW - 2 * innerPad;
  const innerH = frameH - 2 * innerPad;

  const iw = chartImg.naturalWidth || chartImg.width;
  const ih = chartImg.naturalHeight || chartImg.height;
  const scale = Math.min(innerW / iw, innerH / ih, 1);
  const dw = iw * scale;
  const dh = ih * scale;
  const dx = innerX + (innerW - dw) / 2;
  const dy = innerY + (innerH - dh) / 2;

  ctx.save();
  roundRectPath(ctx, innerX, innerY, innerW, innerH, Math.round(frameR * 0.65));
  ctx.clip();
  ctx.drawImage(chartImg, dx, dy, dw, dh);
  ctx.restore();

  const brand = options.brandName ?? "Cricket Metrics";
  const urlLine = displaySiteUrlForWatermark(
    options.siteUrl || getPublicSiteUrl(),
  );
  const urlToDraw =
    urlLine.length > 48 ? `${urlLine.slice(0, 45)}…` : urlLine;

  drawWatermark(ctx, w, h, brand, urlToDraw);

  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (b) => {
        if (b) resolve(b);
        else reject(new Error("Composite PNG failed"));
      },
      "image/png",
      1,
    );
  });
}

/** Build compositor subjects from player-like objects (uses `photo_url` when present). */
export function subjectsFromPlayers(
  players: { id: string; name: string; photo_url?: string | null }[],
  max = 4,
): SocialGraphicSubject[] {
  return players.slice(0, max).map((p) => ({
    id: p.id,
    name: p.name,
    photoUrl: p.photo_url ?? null,
  }));
}
