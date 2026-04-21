import { useContext } from "react";
import { FormatContext, type FormatContextValue } from "@/api/appFormatContext";

/**
 * Access the current format context. Must be used within `<FormatProvider>`.
 */
export function useFormat(): FormatContextValue {
  const ctx = useContext(FormatContext);
  if (ctx == null) {
    throw new Error("useFormat() must be used within a <FormatProvider>");
  }
  return ctx;
}
