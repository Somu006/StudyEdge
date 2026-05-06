/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        cream: '#FAF8F4',
        surface: '#FFFFFF',
        'surface-secondary': '#F2EDE4',
        terracotta: '#C8956C',
        mocha: '#8B6F5E',
        'text-main': '#2C2416',
        'text-muted': '#7A6A58',
        'border-warm': '#E8DDD0',
        'input-bg': '#F7F3ED',
        'tag-bg': '#EDE4D8',
      },
      fontFamily: {
        sans: ['"DM Sans"', 'sans-serif'],
        serif: ['"Playfair Display"', 'serif'],
      },
      boxShadow: {
        'warm': '0 2px 12px rgba(180, 150, 120, 0.08)',
      },
      borderRadius: {
        'btn': '10px',
        'card': '16px',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        }
      },
      animation: {
        'fade-in': 'fadeIn 0.4s ease forwards',
      }
    },
  },
  plugins: [],
}
