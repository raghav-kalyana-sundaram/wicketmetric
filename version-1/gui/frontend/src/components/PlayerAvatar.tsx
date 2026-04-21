import { useMemo, useState, useEffect } from "react";
import { hueFromId, initialsFromName } from "@/lib/avatarVisual";

interface PlayerAvatarProps {
  name: string;
  playerId: string;
  photoUrl?: string | null;
  size?: "sm" | "md";
  className?: string;
}

/**
 * Circular initials avatar; optional photo with fallback on error.
 */
export default function PlayerAvatar({
  name,
  playerId,
  photoUrl,
  size = "sm",
  className = "",
}: PlayerAvatarProps) {
  const [imgOk, setImgOk] = useState(true);
  useEffect(() => {
    setImgOk(true);
  }, [photoUrl]);
  const dims = size === "md" ? "h-9 w-9 text-xs" : "h-7 w-7 text-[10px]";
  const initials = useMemo(() => initialsFromName(name), [name]);
  const bg = useMemo(() => hueFromId(playerId || name), [playerId, name]);

  const showImg = Boolean(photoUrl?.trim()) && imgOk;

  if (showImg) {
    return (
      <span
        className={`inline-flex shrink-0 overflow-hidden rounded-full border border-surface-elevated bg-surface-elevated ${dims} ${className}`}
      >
        <img
          src={photoUrl!}
          alt=""
          className="h-full w-full object-cover"
          onError={() => setImgOk(false)}
        />
      </span>
    );
  }

  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-full border border-surface-elevated/80 font-semibold text-text-primary/95 ${dims} ${className}`}
      style={{ backgroundColor: bg }}
      aria-hidden
    >
      {initials}
    </span>
  );
}
