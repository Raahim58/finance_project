import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#17202a",
        muted: "#5f6f7c",
        line: "#d7dde2",
        surface: "#f6f8f9",
        accent: "#0f766e",
        warn: "#b45309"
      }
    }
  },
  plugins: []
};

export default config;
