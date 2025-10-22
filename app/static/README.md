Static assets

Overview
- Global styles live in css/base.css and load from the base layout.
- Page-specific styles live in css/<page>.css and are added by that template's styles block.
- Global JS helpers live in js/ui.js and js/jobs.js (notifications for authenticated users).
- Page-specific JS lives in js/<page>.js and is included by that page's scripts block.

Current pages
- Wizard: css/wizard.css, js/wizard.js
- Media Library: js/media_library.js (uses vendor/dropzone and vendor/videojs)
- Auth: js/auth_login.js, js/auth_register.js, js/account_settings.js

Vendors
- Third-party CSS/JS (Dropzone, Video.js, Bootstrap Icons) are served from app/static/vendor to be CSP-friendly.
