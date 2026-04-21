import type { ReactNode } from "react";

interface PageIntroProps {
  title: string;
  subtitle?: string;
  question?: string;
  children?: ReactNode;
  className?: string;
}

export default function PageIntro({
  title,
  subtitle,
  question,
  children,
  className = "",
}: PageIntroProps) {
  return (
    <div className={`page-header ${className}`}>
      {question && (
        <p className="text-xs font-medium uppercase tracking-wider text-text-muted">
          {question}
        </p>
      )}
      <h1 className="page-title">{title}</h1>
      {subtitle && <p className="page-subtitle">{subtitle}</p>}
      {children}
    </div>
  );
}
