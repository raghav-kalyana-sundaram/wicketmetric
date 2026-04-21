/**
 * Share icon: captures exportRef region, opens SocialGraphicModal.
 */

import { useState, useCallback } from "react";
import type { RefObject } from "react";
import { Share2 } from "lucide-react";
import { captureExportRoot } from "@/lib/socialCapture";
import SocialGraphicModal from "@/components/SocialGraphicModal";
import type { SocialGraphicSubject } from "@/lib/socialGraphicComposite";

export interface SocialShareTriggerProps {
  exportRef: RefObject<HTMLElement | null>;
  filenameBase?: string;
  className?: string;
  disabled?: boolean;
  subjects?: SocialGraphicSubject[];
  subtitle?: string;
}

export default function SocialShareTrigger({
  exportRef,
  filenameBase = "cricket-metrics",
  className = "",
  disabled = false,
  subjects,
  subtitle,
}: SocialShareTriggerProps) {
  const [open, setOpen] = useState(false);
  const [baseBlob, setBaseBlob] = useState<Blob | null>(null);
  const [busy, setBusy] = useState(false);
  const [capError, setCapError] = useState<string | null>(null);

  const handleClick = useCallback(async () => {
    const el = exportRef.current;
    if (!el || disabled) return;
    setCapError(null);
    setBusy(true);
    try {
      const blob = await captureExportRoot(el);
      setBaseBlob(blob);
      setOpen(true);
    } catch (e) {
      setCapError(
        e instanceof Error ? e.message : "Could not capture this graphic",
      );
    } finally {
      setBusy(false);
    }
  }, [disabled, exportRef]);

  const handleClose = useCallback(() => {
    setOpen(false);
    setBaseBlob(null);
    setCapError(null);
  }, []);

  return (
    <>
      <div className={`flex flex-col items-end gap-1 ${className}`}>
        <button
          type="button"
          onClick={handleClick}
          disabled={disabled || busy}
          className="shrink-0 rounded-lg p-2 text-text-muted hover:bg-surface-elevated hover:text-primary transition-colors disabled:opacity-40 disabled:pointer-events-none"
          aria-label="Generate social graphic"
          title="Share / Export"
        >
          <Share2 size={18} aria-hidden />
        </button>
        {capError && !open && (
          <p
            className="max-w-[11rem] text-right text-[10px] text-danger leading-tight"
            role="status"
          >
            {capError}
          </p>
        )}
      </div>
      <SocialGraphicModal
        open={open}
        onClose={handleClose}
        baseBlob={baseBlob}
        filenameBase={filenameBase}
        subjects={subjects}
        subtitle={subtitle}
      />
    </>
  );
}
