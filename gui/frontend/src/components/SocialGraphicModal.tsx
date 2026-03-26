/**
 * Modal: aspect-ratio preview of composited social graphic, download PNG, copy to clipboard.
 * Final image (with watermark) is precomputed when the modal opens or aspect changes so
 * Copy runs synchronously from cached Blob (Safari user-gesture requirement).
 */

import { useEffect, useState, useCallback, useRef } from "react";
import { X, Copy, Download } from "lucide-react";
import {
  compositeSocialGraphic,
  getPublicSiteUrl,
  SOCIAL_ASPECT_LABELS,
  type SocialAspect,
  type SocialGraphicSubject,
} from "@/lib/socialGraphicComposite";

export interface SocialGraphicModalProps {
  open: boolean;
  onClose: () => void;
  /** Raw chart capture (no watermark); composited in this modal. */
  baseBlob: Blob | null;
  filenameBase?: string;
  /** Players shown in the graphic hero (initials or CORS-safe photos). */
  subjects?: SocialGraphicSubject[];
  /** Optional line under the hero (section context). */
  subtitle?: string;
}

const ASPECT_RATIO_STYLE: Record<SocialAspect, string> = {
  square: "1 / 1",
  landscape: "16 / 9",
  portrait: "9 / 16",
};

export default function SocialGraphicModal({
  open,
  onClose,
  baseBlob,
  filenameBase = "cricket-metrics",
  subjects,
  subtitle,
}: SocialGraphicModalProps) {
  const [aspect, setAspect] = useState<SocialAspect>("square");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [finalBlob, setFinalBlob] = useState<Blob | null>(null);
  const [compositing, setCompositing] = useState(false);
  const [compError, setCompError] = useState<string | null>(null);
  const [copyDone, setCopyDone] = useState(false);
  const [copyErr, setCopyErr] = useState<string | null>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeRef.current();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (!open || !baseBlob) {
      setPreviewUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return null;
      });
      setFinalBlob(null);
      setCompositing(false);
      setCompError(null);
      return;
    }

    let cancelled = false;
    setCompositing(true);
    setCompError(null);

    compositeSocialGraphic(baseBlob, aspect, {
      siteUrl: getPublicSiteUrl(),
      subjects,
      subtitle,
    })
      .then((blob) => {
        if (cancelled) return;
        setFinalBlob(blob);
        setPreviewUrl((prev) => {
          if (prev) URL.revokeObjectURL(prev);
          return URL.createObjectURL(blob);
        });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setCompError(
            err instanceof Error ? err.message : "Could not build preview",
          );
          setFinalBlob(null);
          setPreviewUrl((prev) => {
            if (prev) URL.revokeObjectURL(prev);
            return null;
          });
        }
      })
      .finally(() => {
        if (!cancelled) setCompositing(false);
      });

    return () => {
      cancelled = true;
    };
  }, [open, baseBlob, aspect, subjects, subtitle]);

  useEffect(() => {
    if (!open) setAspect("square");
  }, [open]);

  useEffect(() => {
    if (!copyDone) return;
    const t = setTimeout(() => setCopyDone(false), 2000);
    return () => clearTimeout(t);
  }, [copyDone]);

  const handleDownload = useCallback(() => {
    if (!finalBlob) return;
    const u = URL.createObjectURL(finalBlob);
    const a = document.createElement("a");
    a.href = u;
    a.download = `${filenameBase}-${aspect}-${new Date().toISOString().slice(0, 10)}.png`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(u);
  }, [finalBlob, filenameBase, aspect]);

  const handleCopy = useCallback(() => {
    setCopyErr(null);
    if (!finalBlob) return;
    if (!navigator.clipboard?.write) {
      setCopyErr("Clipboard not available in this browser");
      return;
    }
    void navigator.clipboard
      .write([new ClipboardItem({ "image/png": finalBlob })])
      .then(() => setCopyDone(true))
      .catch(() => setCopyErr("Could not copy image"));
  }, [finalBlob]);

  if (!open) return null;

  const canExport = !!finalBlob && !compositing && !compError;

  return (
    <>
      <div
        className="fixed inset-0 z-[60] bg-black/50 backdrop-blur-[2px]"
        aria-hidden
        onClick={onClose}
      />
      <div
        className="fixed left-1/2 top-1/2 z-[61] w-[min(100vw-1.5rem,34rem)] max-h-[min(92vh,900px)] -translate-x-1/2 -translate-y-1/2 flex flex-col rounded-2xl border border-surface-elevated bg-surface shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="social-graphic-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-2 border-b border-surface-elevated px-4 py-3">
          <h2
            id="social-graphic-title"
            className="text-base font-semibold text-text-primary"
          >
            Generate Social Graphic
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-text-muted hover:bg-surface-elevated hover:text-text-primary transition-colors"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
          <p className="text-xs text-text-secondary">
            Choose an aspect ratio. The preview matches the downloaded image.
          </p>

          <div className="flex flex-wrap gap-2">
            {(Object.keys(SOCIAL_ASPECT_LABELS) as SocialAspect[]).map((id) => {
              const { label, hint } = SOCIAL_ASPECT_LABELS[id];
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => setAspect(id)}
                  className={`rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                    aspect === id
                      ? "border-primary/80 bg-white/[0.05] text-text-primary ring-1 ring-primary/20 dark:bg-surface"
                      : "border-surface-elevated text-text-secondary hover:border-primary/40 hover:text-text-primary"
                  }`}
                >
                  <span className="font-medium block">{label}</span>
                  <span className="text-text-muted">{hint}</span>
                </button>
              );
            })}
          </div>

          {(subjects?.length ?? 0) > 0 && (
            <p className="text-[11px] text-text-muted">
              Preview includes a player strip (initials or photos when URLs allow
              CORS).
            </p>
          )}

          <div
            className="relative mx-auto w-full overflow-hidden rounded-xl border border-surface-elevated bg-[#030303]"
            style={{
              aspectRatio: ASPECT_RATIO_STYLE[aspect],
              maxHeight: "min(56vh, 460px)",
            }}
          >
            {compositing && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-text-muted text-sm">
                <div className="h-8 w-8 rounded-full border-2 border-surface-elevated border-t-primary animate-spin" />
                Preparing preview…
              </div>
            )}
            {!compositing && previewUrl && (
              <img
                src={previewUrl}
                alt="Social graphic preview"
                className="h-full w-full object-contain"
              />
            )}
            {!compositing && compError && (
              <div className="absolute inset-0 flex items-center justify-center p-4 text-center text-sm text-danger">
                {compError}
              </div>
            )}
          </div>

          <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={handleCopy}
              disabled={!canExport}
              className="btn-secondary btn-sm order-2 sm:order-1 justify-center disabled:opacity-50"
            >
              <Copy size={16} />
              {copyDone ? "Copied!" : "Copy to Clipboard"}
            </button>
            <button
              type="button"
              onClick={handleDownload}
              disabled={!canExport}
              className="btn-primary btn-sm order-1 sm:order-2 justify-center disabled:opacity-50"
            >
              <Download size={16} />
              Download PNG
            </button>
          </div>
          {copyErr && (
            <p className="text-xs text-danger text-center" role="status">
              {copyErr}
            </p>
          )}
        </div>
      </div>
    </>
  );
}
