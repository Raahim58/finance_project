import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#15202b",
        muted: "#687786",
        line: "#d8dfe4",
        surface: "#f3f5f6",
        accent: "#17745b",
        warn: "#a44932"
      }
    }
  },
  plugins: []
};

export default config;
