import type { ReactNode } from "react";

interface InsightCardProps {
  headline: string;
  supporting?: string;
  accent?: "default" | "gold" | "green" | "amber";
  icon?: ReactNode;
  className?: string;
  children?: ReactNode;
}

const ACCENT_BORDER: Record<string, string> = {
  default: "border-l-primary/60",
  gold: "border-l-gold",
  green: "border-l-accent",
  amber: "border-l-warning",
};

export default function InsightCard({
  headline,
  supporting,
  accent = "default",
  icon,
  className = "",
  children,
}: InsightCardProps) {
  return (
    <div
      className={`rounded-lg border border-surface-elevated/60 bg-surface-elevated/30 px-4 py-3 border-l-[3px] ${ACCENT_BORDER[accent]} dark:bg-white/[0.02] ${className}`}
    >
      <div className="flex items-start gap-3">
        {icon && (
          <span className="mt-0.5 shrink-0 text-text-muted">{icon}</span>
        )}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium leading-snug text-text-primary">
            {headline}
          </p>
          {supporting && (
            <p className="mt-1 text-xs leading-relaxed text-text-secondary">
              {supporting}
            </p>
          )}
          {children}
        </div>
      </div>
    </div>
  );
}
