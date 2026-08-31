/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        appBg: "#121314",
        sidebarBg: "#17181B",
        surfaceBg: "#202124",
        surfaceHover: "#2A2C31",
        inputBg: "#1C1D20",
        borderSubtle: "#303136",
        arcsaPrimary: "#2F6FED",
        arcsaHover: "#255CC7",
        arcsaSoft: "#1E3A6D",
        warningBg: "#3A2B16",
        warningBorder: "#785316",
        dangerBg: "#3A1B1B",
      }
    },
  },
  plugins: [],
}
