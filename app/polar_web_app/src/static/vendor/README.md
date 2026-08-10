# Vendored: Chart.js

- **Version**: 4.4.7
- **File**: `chart.umd.min.js`
- **Source**: `https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js`
- **SHA-256**: `206b6e8bb00fc7bba2c7ee80ca41db3e9e05ba7be0aa35abeba9cfd5357f5d0e`

Downloaded once and committed here rather than loaded from a CDN `<script>` tag
(this app has no build step or bundler) — see `plan.html`, which references
`/static/vendor/chart.umd.min.js` directly, served by the existing
`StaticFiles` mount in `app.py`.

To bump the version: download the new `chart.umd.min.js` from jsDelivr,
replace this file, verify its SHA-256, and update the values above.
