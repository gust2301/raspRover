/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        navy: {
          900: '#0a0f1e',
          800: '#0f1629',
          700: '#111827',
          600: '#1e293b',
        },
      },
    },
  },
  plugins: [],
}
