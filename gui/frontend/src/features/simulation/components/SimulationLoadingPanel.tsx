import { useEffect, useRef, useState } from "react";

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const fn = () => setReduced(mq.matches);
    mq.addEventListener("change", fn);
    return () => mq.removeEventListener("change", fn);
  }, []);
  return reduced;
}

interface SimulationLoadingPanelProps {
  isPending: boolean;
  targetIterations: number;
}

export default function SimulationLoadingPanel({
  isPending,
  targetIterations,
}: SimulationLoadingPanelProps) {
  const counterRef = useRef<HTMLSpanElement>(null);
  const reducedMotion = usePrefersReducedMotion();

  useEffect(() => {
    if (!isPending) return;

    if (reducedMotion) {
      if (counterRef.current) {
        counterRef.current.textContent = String(targetIterations);
      }
      return;
    }

    let n = 0;
    if (counterRef.current) counterRef.current.textContent = "0";

    const step = () =>
      Math.max(
        1,
        Math.min(
          Math.floor(targetIterations / 35),
          Math.ceil(targetIterations / 25),
        ),
      );

    const id = window.setInterval(() => {
      n = Math.min(targetIterations, n + step());
      if (counterRef.current) {
        counterRef.current.textContent = n.toLocaleString();
      }
      if (n >= targetIterations) {
        window.clearInterval(id);
      }
    }, 80);

    return () => window.clearInterval(id);
  }, [isPending, targetIterations, reducedMotion]);

  if (!isPending) return null;

  return (
    <div
      className="flex flex-col items-center justify-center gap-5 rounded-xl border border-white/[0.08] bg-surface-elevated/40 py-14 px-6"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="relative" aria-hidden>
        <div className="h-12 w-12 rounded-full border-4 border-surface-elevated" />
        <div className="absolute inset-0 h-12 w-12 rounded-full border-4 border-primary border-t-transparent animate-spin motion-reduce:animate-none" />
      </div>
      <div className="text-center">
        <p className="text-sm font-medium text-text-primary">
          Running simulations…
        </p>
        {reducedMotion ? (
          <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-primary">
            {targetIterations.toLocaleString()} iterations
          </p>
        ) : (
          <p className="mt-2 text-text-secondary text-sm">
            Progress:{" "}
            <span
              ref={counterRef}
              className="font-mono text-2xl font-semibold tabular-nums text-primary"
            >
              0
            </span>
            <span className="text-text-muted">
              {" "}
              / {targetIterations.toLocaleString()}
            </span>
          </p>
        )}
      </div>
    </div>
  );
}
