/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50:  '#eef4ff',
          100: '#dde9ff',
          200: '#b9d1ff',
          300: '#8eb4ff',
          400: '#5d8eff',
          500: '#3b6cf3',
          600: '#2a52d4',
          700: '#1f3fa6',
          800: '#1a3585',
          900: '#162d6f',
        },
        ink: {
          50:  '#f7f8fa',
          100: '#eef0f4',
          200: '#dee2eb',
          300: '#bcc4d1',
          400: '#8e98aa',
          500: '#6b7689',
          600: '#4d5668',
          700: '#3a4254',
          800: '#262d3f',
          900: '#161b2b',
        },
        console: {
          bg: '#10131c',
          text: '#dbe1ee',
          dim: '#7b8499',
          ok: '#4ade80',
          err: '#f87171',
          warn: '#fbbf24',
        },
      },
      fontFamily: {
        sans: ['ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgb(22 27 43 / 4%), 0 8px 24px rgb(22 27 43 / 5%)',
        cardHover: '0 1px 3px rgb(22 27 43 / 5%), 0 12px 32px rgb(22 27 43 / 8%)',
      },
    },
  },
  plugins: [],
};
