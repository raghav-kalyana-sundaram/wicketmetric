import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Hex palette: opacity modifiers (/30, /80) must resolve in @apply — keep hex here;
        // ambient tint comes from body gradients in globals.css (OKLCH).
        /* R=G=B only — avoids slate/zinc Tailwind defaults that read blue on panels */
        background: {
          DEFAULT: "#030303",
          light: "#eef1f5",
        },
        surface: {
          DEFAULT: "#0c0c0c",
          elevated: "#141414",
          light: "#f7f9fc",
        },
        /* Monochrome primary: light chrome in dark UI, black in light (see globals overrides) */
        primary: {
          DEFAULT: "#e8e8ee",
          hover: "#f4f4f8",
          light: "#fafafa",
          dark: "#1a1a1f",
        },
        accent: {
          DEFAULT: "#10B981",
          hover: "#059669",
          light: "#34D399",
        },
        warning: {
          DEFAULT: "#F59E0B",
          hover: "#D97706",
          light: "#FCD34D",
        },
        danger: {
          DEFAULT: "#EF4444",
          hover: "#DC2626",
          light: "#FCA5A5",
        },
        gold: {
          DEFAULT: "#C89B3C",
          light: "#E0BC6D",
          dark: "#8A6423",
        },

        // Score / grade colour mapping
        score: {
          s: "#C89B3C", // 95-100 — S grade (Gold)
          "a-plus": "#10B981", // 85-94  — A+ (Emerald)
          a: "#22C55E", // 75-84  — A  (Green)
          "b-plus": "#787878", // 60-74  — B+ (neutral)
          b: "#5c5c5c", // 45-59  — B  (neutral)
          "c-plus": "#F59E0B", // 30-44  — C+ (Amber)
          c: "#F97316", // 15-29  — C  (Orange)
          d: "#EF4444", // 0-14   — D  (Red)
        },

        // Text colours
        text: {
          primary: {
            DEFAULT: "#e4e4e7",
            light: "#121926",
          },
          secondary: {
            DEFAULT: "#c4c4cc",
            light: "#4d5b70",
          },
          muted: {
            DEFAULT: "#8f8f98",
            light: "#7a889a",
          },
        },

        // Chart colours for multi-player comparisons
        chart: {
          1: "#d4d4dc", // Light chrome (dark bg)
          2: "#F59E0B", // Amber
          3: "#10B981", // Emerald
          4: "#EF4444", // Red
        },

        // Cricket-specific semantic colours
        cricket: {
          dot: "#64748B", // Dot ball
          single: "#9ca3af", // 1-3 runs (neutral)
          boundary: "#22C55E", // Four
          six: "#FFD700", // Six
          wicket: "#EF4444", // Wicket
        },
      },

      fontFamily: {
        sans: [
          "Manrope",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        heading: [
          "Bricolage Grotesque",
          "Manrope",
          "ui-sans-serif",
          "system-ui",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "Liberation Mono",
          "Courier New",
          "monospace",
        ],
      },

      fontSize: {
        h1: ["clamp(1.75rem, 1.5rem + 1vw, 2.125rem)", { lineHeight: "1.2", fontWeight: "700", letterSpacing: "-0.02em" }],
        h2: ["clamp(1.35rem, 1.2rem + 0.6vw, 1.5rem)", { lineHeight: "1.3", fontWeight: "600", letterSpacing: "-0.015em" }],
        h3: ["1.25rem", { lineHeight: "1.4", fontWeight: "600", letterSpacing: "-0.01em" }],
        body: ["1rem", { lineHeight: "1.55", fontWeight: "400" }],
        small: ["0.875rem", { lineHeight: "1.35", fontWeight: "500" }],
      },

      transitionTimingFunction: {
        "out-quart": "cubic-bezier(0.25, 1, 0.5, 1)",
        "out-quint": "cubic-bezier(0.22, 1, 0.36, 1)",
      },

      animation: {
        "fade-in": "fadeIn 0.35s cubic-bezier(0.25, 1, 0.5, 1)",
        "slide-up": "slideUp 0.4s cubic-bezier(0.25, 1, 0.5, 1)",
        "slide-in-right": "slideInRight 0.35s cubic-bezier(0.25, 1, 0.5, 1)",
        "content-enter": "contentEnter 0.5s cubic-bezier(0.25, 1, 0.5, 1) both",
        "pulse-score": "pulseScore 2s ease-in-out infinite",
        "spin-slow": "spin 3s linear infinite",
      },

      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        slideInRight: {
          "0%": { opacity: "0", transform: "translateX(8px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        contentEnter: {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        pulseScore: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.7" },
        },
      },

      borderRadius: {
        card: "0.75rem",
      },

      boxShadow: {
        card: "0 1px 2px rgb(0 0 0 / 0.4)",
        "card-hover": "0 8px 20px rgb(0 0 0 / 0.45)",
      },

      spacing: {
        18: "4.5rem",
        88: "22rem",
        112: "28rem",
        128: "32rem",
      },

      maxWidth: {
        "8xl": "88rem",
      },

      screens: {
        xs: "480px",
      },
    },
  },
  plugins: [],
};

export default config;
