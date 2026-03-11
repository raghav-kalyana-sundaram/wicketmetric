/**
 * Debounce hooks for the Cricket Metrics GUI.
 *
 * Provides `useDebounce` for debouncing values (e.g. search input text)
 * and `useDebouncedCallback` for debouncing function calls.
 *
 * Usage:
 *   import { useDebounce, useDebouncedCallback } from '@/hooks/useDebounce';
 *
 *   // Debounce a value (e.g. search query)
 *   const [query, setQuery] = useState('');
 *   const debouncedQuery = useDebounce(query, 150);
 *
 *   // Debounce a callback
 *   const handleResize = useDebouncedCallback(() => {
 *     recalculateLayout();
 *   }, 200);
 */

import { useEffect, useRef, useState, useCallback, useMemo } from 'react';

// ── useDebounce (value) ──────────────────────────────────────────

/**
 * Returns a debounced version of the provided value.
 *
 * The returned value only updates after `delay` milliseconds of
 * inactivity. This is ideal for search-as-you-type inputs where
 * you want to avoid firing an API call on every keystroke.
 *
 * @param value  The value to debounce.
 * @param delay  Debounce delay in milliseconds (default 150ms).
 * @returns      The debounced value.
 *
 * @example
 *   const [query, setQuery] = useState('');
 *   const debouncedQuery = useDebounce(query, 150);
 *
 *   useEffect(() => {
 *     if (debouncedQuery.length >= 2) {
 *       api.autocomplete({ q: debouncedQuery });
 *     }
 *   }, [debouncedQuery]);
 */
export function useDebounce<T>(value: T, delay: number = 150): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    // Set a timer to update the debounced value after the delay
    const timer = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    // Cancel the timer if value changes before the delay elapses
    return () => {
      clearTimeout(timer);
    };
  }, [value, delay]);

  return debouncedValue;
}

// ── useDebouncedCallback ─────────────────────────────────────────

/**
 * Returns a debounced version of the provided callback function.
 *
 * The callback is only invoked after `delay` milliseconds of
 * inactivity. Subsequent calls within the delay window reset the
 * timer. The returned function also exposes `.cancel()` and
 * `.flush()` methods.
 *
 * @param callback  The function to debounce.
 * @param delay     Debounce delay in milliseconds (default 150ms).
 * @returns         A debounced function with `.cancel()` and `.flush()` methods.
 *
 * @example
 *   const debouncedSearch = useDebouncedCallback((query: string) => {
 *     performSearch(query);
 *   }, 200);
 *
 *   // In an input handler:
 *   onChange={(e) => debouncedSearch(e.target.value)}
 *
 *   // Cancel pending invocation:
 *   debouncedSearch.cancel();
 *
 *   // Immediately invoke pending invocation:
 *   debouncedSearch.flush();
 */
export function useDebouncedCallback<Args extends unknown[]>(
  callback: (...args: Args) => void,
  delay: number = 150,
): DebouncedFunction<Args> {
  // Use refs to always have access to the latest callback and pending args
  // without needing to re-create the debounced function.
  const callbackRef = useRef(callback);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingArgsRef = useRef<Args | null>(null);

  // Keep the callback ref up to date
  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  // Clean up on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, []);

  const cancel = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    pendingArgsRef.current = null;
  }, []);

  const flush = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (pendingArgsRef.current !== null) {
      callbackRef.current(...pendingArgsRef.current);
      pendingArgsRef.current = null;
    }
  }, []);

  const debouncedFn = useCallback(
    (...args: Args) => {
      pendingArgsRef.current = args;

      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
      }

      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        if (pendingArgsRef.current !== null) {
          callbackRef.current(...pendingArgsRef.current);
          pendingArgsRef.current = null;
        }
      }, delay);
    },
    [delay],
  );

  // Attach cancel and flush methods to the debounced function.
  // useMemo ensures the identity is stable as long as the dependencies
  // don't change.
  const result = useMemo(() => {
    const fn = debouncedFn as DebouncedFunction<Args>;
    fn.cancel = cancel;
    fn.flush = flush;
    return fn;
  }, [debouncedFn, cancel, flush]);

  return result;
}

// ── Types ────────────────────────────────────────────────────────

/**
 * A debounced function with `.cancel()` and `.flush()` control methods.
 */
export interface DebouncedFunction<Args extends unknown[]> {
  (...args: Args): void;
  /** Cancel any pending invocation. */
  cancel: () => void;
  /** Immediately invoke any pending invocation. */
  flush: () => void;
}

// ── Default export ───────────────────────────────────────────────

export default useDebounce;
