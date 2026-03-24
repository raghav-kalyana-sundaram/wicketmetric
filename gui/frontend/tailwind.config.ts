import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Hex palette: opacity modifiers (/30, /80) must resolve in @apply — keep hex here;
        // ambient tint comes from body gradients in globals.css (OKLCH).
        background: {
          DEFAULT: "#0a0d12",
          light: "#eef1f5",
        },
        surface: {
          DEFAULT: "#0f141d",
          elevated: "#1d2633",
          light: "#f7f9fc",
        },
        primary: {
          DEFAULT: "#8ab4f8",
          hover: "#78a6f0",
          light: "#a9c7fa",
          dark: "#5f8de0",
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
          "b-plus": "#06B6D4", // 60-74  — B+ (Cyan)
          b: "#3B82F6", // 45-59  — B  (Blue)
          "c-plus": "#F59E0B", // 30-44  — C+ (Amber)
          c: "#F97316", // 15-29  — C  (Orange)
          d: "#EF4444", // 0-14   — D  (Red)
        },

        // Text colours
        text: {
          primary: {
            DEFAULT: "#e8edf5",
            light: "#121926",
          },
          secondary: {
            DEFAULT: "#b8c4d4",
            light: "#4d5b70",
          },
          muted: {
            DEFAULT: "#94a3b8",
            light: "#7a889a",
          },
        },

        // Chart colours for multi-player comparisons
        chart: {
          1: "#3B82F6", // Blue
          2: "#F59E0B", // Amber
          3: "#10B981", // Emerald
          4: "#EF4444", // Red
        },

        // Cricket-specific semantic colours
        cricket: {
          dot: "#64748B", // Dot ball
          single: "#3B82F6", // 1-3 runs
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
        card: "0 1px 2px rgb(2 6 23 / 0.18)",
        "card-hover":
          "0 8px 20px rgb(2 6 23 / 0.22)",
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
