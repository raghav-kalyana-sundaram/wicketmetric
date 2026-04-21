import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import type { ReactNode } from "react";

export interface CrossLink {
  label: string;
  to: string;
  icon?: ReactNode;
}

interface CrossLinkBarProps {
  links: CrossLink[];
  title?: string;
  className?: string;
}

export default function CrossLinkBar({
  links,
  title,
  className = "",
}: CrossLinkBarProps) {
  if (links.length === 0) return null;

  return (
    <div
      className={`rounded-lg border border-surface-elevated/50 bg-surface-elevated/20 px-4 py-3 dark:bg-white/[0.015] ${className}`}
    >
      {title && (
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
          {title}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {links.map((link) => (
          <Link
            key={link.to}
            to={link.to}
            className="inline-flex items-center gap-1.5 rounded-lg border border-surface-elevated/70 bg-surface px-3 py-1.5 text-xs font-medium text-text-secondary transition-colors hover:border-primary/30 hover:bg-surface-elevated hover:text-primary dark:border-white/[0.08] dark:hover:border-white/[0.15] dark:hover:bg-white/[0.04]"
          >
            {link.icon}
            <span>{link.label}</span>
            <ArrowRight size={10} className="opacity-50" />
          </Link>
        ))}
      </div>
    </div>
  );
}
