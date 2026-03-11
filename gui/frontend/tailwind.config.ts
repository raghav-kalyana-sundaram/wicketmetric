import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Dark mode palette (primary)
        background: {
          DEFAULT: "#0F172A",
          light: "#F8FAFC",
        },
        surface: {
          DEFAULT: "#1E293B",
          elevated: "#334155",
          light: "#FFFFFF",
        },
        primary: {
          DEFAULT: "#3B82F6",
          hover: "#2563EB",
          light: "#60A5FA",
          dark: "#1D4ED8",
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
          DEFAULT: "#FFD700",
          light: "#FFED4A",
          dark: "#B8860B",
        },

        // Score / grade colour mapping
        score: {
          s: "#FFD700", // 95-100 — S grade (Gold)
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
            DEFAULT: "#F8FAFC",
            light: "#0F172A",
          },
          secondary: {
            DEFAULT: "#94A3B8",
            light: "#475569",
          },
          muted: {
            DEFAULT: "#64748B",
            light: "#9CA3AF",
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
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
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
        // Typography scale from gui.md
        h1: ["2rem", { lineHeight: "2.5rem", fontWeight: "700" }],
        h2: ["1.5rem", { lineHeight: "2rem", fontWeight: "600" }],
        h3: ["1.25rem", { lineHeight: "1.75rem", fontWeight: "600" }],
        body: ["1rem", { lineHeight: "1.5rem", fontWeight: "400" }],
        small: ["0.875rem", { lineHeight: "1.25rem", fontWeight: "500" }],
      },

      animation: {
        "fade-in": "fadeIn 0.3s ease-out",
        "slide-up": "slideUp 0.3s ease-out",
        "slide-in-right": "slideInRight 0.3s ease-out",
        "pulse-score": "pulseScore 2s ease-in-out infinite",
        "spin-slow": "spin 3s linear infinite",
      },

      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(10px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        slideInRight: {
          "0%": { opacity: "0", transform: "translateX(10px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
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
        card: "0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1)",
        "card-hover":
          "0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)",
        glow: "0 0 15px rgb(59 130 246 / 0.5)",
        "glow-gold": "0 0 15px rgb(255 215 0 / 0.5)",
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
