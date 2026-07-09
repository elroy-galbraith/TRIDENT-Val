/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        paper: '#F7F8F6',
        ink: '#16232E',
        inkmute: '#5B6B77',
        line: '#DDE3E0',
        teal: '#0E7C7B',
        tealdeep: '#0A5958',
        amber: '#C77D0A',
        flag: '#B3352C',
        ok: '#2E7D4F',
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}
