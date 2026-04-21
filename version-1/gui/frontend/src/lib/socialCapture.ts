/**
 * Rasterize an in-page export region for social graphics (no DOM clone in the modal).
 * Uses html2canvas on the live element; onclone forces dark theme on the cloned document
 * so captures match shared branding without toggling the real <html> class.
 */

import html2canvas from "html2canvas";

/** Add to the wrapper you pass to captureExportRoot for optional styling hooks. */
export const SOCIAL_EXPORT_ROOT_CLASS = "social-export-capture-root";

const CAPTURE_BG = "#060606";

export async function captureExportRoot(
  element: HTMLElement,
): Promise<Blob> {
  const canvas = await html2canvas(element, {
    scale: 2,
    useCORS: true,
    logging: false,
    backgroundColor: CAPTURE_BG,
    onclone(clonedDoc, clonedElement) {
      clonedDoc.documentElement.classList.add("dark");
      if (clonedElement instanceof HTMLElement) {
        clonedElement.style.backgroundColor = CAPTURE_BG;
        clonedElement.classList.add("dark");
      }
    },
  });

  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) resolve(blob);
        else reject(new Error("PNG capture failed (empty blob)"));
      },
      "image/png",
      1,
    );
  });
}
