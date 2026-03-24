/**
 * FormatToggle — gender then competition (Men's/Women's × T20 / IPL).
 */

import { useFormat } from "@/api/FormatContext";
import {
  ALL_FORMATS,
  type Competition,
  type Gender,
  formatFromGenderComp,
  genderCompFromFormat,
} from "@/api/formatConstants";
import { useQueryClient } from "@tanstack/react-query";

interface FormatToggleProps {
  className?: string;
  /**
   * `strip` = full dataset bar (under main nav). `toolbar` = inline horizontal row.
   * `default` = compact block for mobile menu.
   */
  variant?: "default" | "toolbar" | "strip";
}

export default function FormatToggle({
  className = "",
  variant = "default",
}: FormatToggleProps) {
  const { format, setFormat, availableFormats } = useFormat();
  const queryClient = useQueryClient();

  if (availableFormats.length <= 1) {
    return null;
  }

  const { gender, competition } = genderCompFromFormat(format);

  const apply = (g: Gender, c: Competition) => {
    const next = formatFromGenderComp(g, c);
    if (!availableFormats.includes(next)) return;
    if (next === format) return;
    setFormat(next);
    queryClient.invalidateQueries();
  };

  const dense = variant === "toolbar" || variant === "strip";
  const segBase = dense
    ? "min-h-10 px-3.5 py-2 text-xs font-semibold rounded-lg transition-colors duration-200 ease-out-quart whitespace-nowrap sm:min-h-0 sm:py-1.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/35 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    : "px-3 py-1.5 text-xs font-semibold rounded-lg transition-all duration-200 ease-out whitespace-nowrap focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/35 focus-visible:ring-offset-2 focus-visible:ring-offset-background";
  const segActive =
    "bg-primary/18 text-primary shadow-sm ring-1 ring-primary/25 dark:text-primary-light";
  const segIdle =
    "text-text-secondary hover:text-text-primary hover:bg-surface-elevated/45 dark:hover:bg-surface-elevated/55";

  const gBtn = (g: Gender, label: string) => {
    const active = gender === g;
    return (
      <button
        key={g}
        type="button"
        role="radio"
        aria-checked={active}
        onClick={() => apply(g, competition)}
        className={`${segBase} ${active ? segActive : segIdle}`}
      >
        {label}
      </button>
    );
  };

  const cBtn = (c: Competition, label: string) => {
    const active = competition === c;
    return (
      <button
        key={c}
        type="button"
        role="radio"
        aria-checked={active}
        onClick={() => apply(gender, c)}
        className={`${segBase} ${active ? segActive : segIdle}`}
      >
        {label}
      </button>
    );
  };

  const visible = ALL_FORMATS.filter((f) => availableFormats.includes(f));
  const menT20Ok = visible.includes("mens_t20i");
  const menIplOk = visible.includes("mens_ipl");
  const womenT20Ok = visible.includes("womens_t20i");
  const womenIplOk = visible.includes("womens_ipl");
  const showWomenDataHint =
    (menT20Ok || menIplOk) && !womenT20Ok && !womenIplOk;

  const shellClass =
    "inline-flex rounded-xl border border-surface-elevated/80 bg-surface-elevated/20 p-1 dark:border-surface-elevated/60 dark:bg-surface-elevated/25";

  if (variant === "toolbar" || variant === "strip") {
    const inner = (
      <>
        <div className={shellClass} role="radiogroup" aria-label="Gender">
          {menT20Ok || menIplOk ? gBtn("men", "Men") : null}
          {womenT20Ok || womenIplOk ? gBtn("women", "Women") : null}
        </div>
        <span
          className="select-none text-text-muted/40 dark:text-text-muted/50"
          aria-hidden
        >
          ·
        </span>
        <div className={shellClass} role="radiogroup" aria-label="Competition">
          {(gender === "men" ? menT20Ok : womenT20Ok) ? cBtn("t20", "T20") : null}
          {(gender === "men" ? menIplOk : womenIplOk) ? cBtn("ipl", "IPL") : null}
        </div>
      </>
    );

    if (variant === "strip") {
      return (
        <div
          className={`flex w-full min-w-0 flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-x-6 sm:gap-y-3 ${className}`}
          role="group"
          aria-label="Dataset: gender and competition"
        >
          <div className="min-w-0 shrink-0">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              Dataset
            </p>
            <p className="mt-0.5 text-sm text-text-secondary">
              Men&apos;s / women&apos;s · T20I vs franchise
            </p>
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-2 sm:justify-end">
            {inner}
          </div>
          {showWomenDataHint ? (
            <p
              className="w-full basis-full text-[10px] text-text-muted leading-snug"
              title="Women’s slices need their own pipeline outputs on the server."
            >
              Women&apos;s T20 / Women&apos;s IPL appear after you build{" "}
              <code className="text-[9px]">output/womens_t20i</code> (or legacy{" "}
              <code className="text-[9px]">output/womens_t20</code>) and{" "}
              <code className="text-[9px]">output/womens_ipl</code>, then restart
              the API.
            </p>
          ) : null}
        </div>
      );
    }

    return (
      <div
        className={`flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3 ${className}`}
        role="group"
        aria-label="Dataset: gender and competition"
      >
        <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
          Dataset
        </span>
        <div className="flex flex-wrap items-center gap-2">{inner}</div>
        {showWomenDataHint ? (
          <p
            className="text-[10px] text-text-muted leading-snug max-w-md sm:ml-1"
            title="Women’s slices need their own pipeline outputs on the server."
          >
            Women&apos;s T20 / Women&apos;s IPL appear after you build{" "}
            <code className="text-[9px]">output/womens_t20i</code> (or legacy{" "}
            <code className="text-[9px]">output/womens_t20</code>) and{" "}
            <code className="text-[9px]">output/womens_ipl</code>, then restart
            the API.
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div
      className={`flex flex-col gap-2 ${className}`}
      role="group"
      aria-label="Dataset: gender and competition"
    >
      <div className={shellClass} role="radiogroup" aria-label="Gender">
        {menT20Ok || menIplOk ? gBtn("men", "Men") : null}
        {womenT20Ok || womenIplOk ? gBtn("women", "Women") : null}
      </div>
      <div className={shellClass} role="radiogroup" aria-label="Competition">
        {(gender === "men" ? menT20Ok : womenT20Ok) ? cBtn("t20", "T20") : null}
        {(gender === "men" ? menIplOk : womenIplOk) ? cBtn("ipl", "IPL") : null}
      </div>
      {showWomenDataHint ? (
        <p
          className="text-[10px] text-text-muted leading-snug px-1 pb-0.5 max-w-[220px]"
          title="Women’s slices need their own pipeline outputs on the server."
        >
          Women&apos;s T20 / Women&apos;s IPL appear after you build{" "}
          <code className="text-[9px]">output/womens_t20i</code> (or legacy{" "}
          <code className="text-[9px]">output/womens_t20</code>) and{" "}
          <code className="text-[9px]">output/womens_ipl</code>, then restart
          the API. See <code className="text-[9px]">scripts/sync_cricsheet.sh</code>{" "}
          or <code className="text-[9px]">DEPLOYMENT.md</code>.
        </p>
      ) : null}
    </div>
  );
}
