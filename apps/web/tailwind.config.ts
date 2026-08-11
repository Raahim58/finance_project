import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#171a1d",
        muted: "#666c72",
        line: "rgba(23,26,29,.075)",
        surface: "#f1f2ef",
        accent: "#126b52",
        warn: "#b9473c"
      }
    }
  },
  plugins: []
};

export default config;
