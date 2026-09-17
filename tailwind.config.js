/** Tailwind build config for the dashboard. Run scripts/build_css.sh after editing templates or scripts. */
module.exports = {
  content: ['./supervisor/templates/*.html', './supervisor/static/*.js'],
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'system-ui', 'sans-serif'] },
      borderRadius: { sm: '3px', DEFAULT: '3px', md: '3px', lg: '3px' },
    },
  },
};
