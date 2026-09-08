/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // "Sello Oficial" token system — deep navy ink, cool pale paper
        // surfaces, hairline borders and a single muted gold accent.
        ink: {
          900: "#0E2340",
          700: "#2C4A72",
          500: "#5C7699",
        },
        surface: {
          0: "#F8F9F8",
          100: "#EEF0EF",
          200: "#E1E4E1",
        },
        line: "#CDD2CD",
        accent: {
          DEFAULT: "#9C7A34",
          hover: "#7D622A",
        },
        good: "#3E7A4F",
        warn: "#A9762B",
        bad: "#A6402F",
      },
      fontFamily: {
        display: ['"Iowan Old Style"', '"Palatino Linotype"', '"Book Antiqua"', "Georgia", '"Times New Roman"', "serif"],
        sans: ["-apple-system", '"Segoe UI"', "Roboto", "Helvetica", "Arial", "sans-serif"],
      },
      // Sharp/minimal archival corners (2-3px) instead of the default
      // soft/bubbly Tailwind radii. `full` is left untouched for
      // circular badges, avatars and pills.
      borderRadius: {
        sm: "2px",
        DEFAULT: "3px",
        md: "3px",
        lg: "3px",
        xl: "3px",
        "2xl": "3px",
        "3xl": "3px",
      },
    },
  },
  plugins: [],
}
