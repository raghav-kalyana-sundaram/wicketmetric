/**
 * Format context — re-exports for backward compatibility.
 *
 * Provider is in FormatProvider.tsx; hook in useFormat.ts so Vite Fast Refresh
 * does not invalidate the tree when only the hook changes.
 */

export type { Format } from "@/api/formatConstants";
export {
  ALL_FORMATS,
  DEFAULT_FORMAT,
  FORMAT_ICONS,
  FORMAT_LABELS,
} from "@/api/formatConstants";

export { FormatProvider } from "@/api/FormatProvider";
export { useFormat } from "@/api/useFormat";
