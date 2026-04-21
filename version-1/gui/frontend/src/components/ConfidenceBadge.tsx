interface ConfidenceBadgeProps {
  balls?: number | null;
  innings?: number | null;
  className?: string;
}

function getConfidenceLevel(
  balls?: number | null,
  innings?: number | null,
): { label: string; tier: "low" | "medium" | "high" } {
  const b = balls ?? 0;
  const i = innings ?? 0;

  if (b >= 30 || i >= 15) return { label: "Strong sample", tier: "high" };
  if (b >= 12 || i >= 6) return { label: "Moderate sample", tier: "medium" };
  return { label: "Small sample", tier: "low" };
}

const TIER_CLASSES: Record<string, string> = {
  low: "bg-warning/15 text-warning border-warning/20",
  medium: "bg-text-muted/10 text-text-muted border-text-muted/15",
  high: "bg-accent/10 text-accent border-accent/20",
};

export default function ConfidenceBadge({
  balls,
  innings,
  className = "",
}: ConfidenceBadgeProps) {
  const { label, tier } = getConfidenceLevel(balls, innings);

  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium leading-none ${TIER_CLASSES[tier]} ${className}`}
    >
      {label}
    </span>
  );
}

export { getConfidenceLevel };
