# Krexion Automation Templates

Ready-to-import Visual Recorder / RUT step JSONs for common offer flows.

## How to use

1. Open Visual Recorder → click "Import Steps" → choose a JSON file from this folder.
2. Set proxy + Excel data in the main setup screen.
3. Click "Live Test" to verify on a single visit.
4. If any step needs tweaking, use "✨ Refine with AI" to fix it without re-recording.

## Available templates

### `linkthem_offer250_FINAL.json` (351 steps) — **YOUR OFFER**
- **Offer URL**: https://linkthem.net/aff_c?offer_id=250&aff_id=171338
- **Funnel**: retailproductsusa Q1–Q3 (Yes/No → Use it myself/Share with family → Weekly/Monthly) → **email Continue (required)** → displayoptoffers surveys → **lead form (required, visible #lfirstname wait)** → 3 deals → conversion
- **Forms are NOT optional** — `#lfirstname` visible hone tak wait (120s), phir full form + phone 3-part fill
- **Excel columns**: `first, last, address, city, state, zip_code, cellphone, email, gender, day, month, year`
- **Phone/SMS popup**: always **No thanks**
- **Email newsletter popup**: always **Yes**
- **Survey**: random answer each step; `Math.random()` per visit — unique user behavior
- **Deal page**: clicks 3 different CONTINUE deals (`dataset.rfClicked` tracks done deals); skips survey when deal page detected
- **Excel columns required**: `first, last, address, city, state, zip_code, cellphone, email, gender, day, month, year` (optional: `dob`)

### `upLevelRewards_2X_cash_summer.json` (35 steps)
- **Offer URL**: https://offer-luxe-spot.lovable.app
- **Funnel**: lovable landing → trksy.org tracker → uplevelrewards.com form → surveys (random per visit) → lead form → deal page (Fillwords / JustPlay / Bingo Billions — 3 free deals click)
- **Tested redirect chain**: ✓ lovable → trksy.org → www.uplevelrewards.com (verified live via US ProxyJet residential)
- **Survey randomization**: each survey step uses `Math.random()` to pick from first 3 visible options → unique answer per visit.
- **Form fill**: native React-compatible value setter (works on both classic `<form method=post>` AND React SPA forms).
- **Deal page**: skips Whatnot ($5 min), clicks 3 free deals (Fillwords / JustPlay / Bingo Billions) with `history.back()` between to return to deal page. Uses a `window.__krxClicked` Set to avoid re-clicking the same deal.
- **Excel columns required**: `first, last, email, cellphone, address, city, state, zip_code, gender, day, month, year, dob`
