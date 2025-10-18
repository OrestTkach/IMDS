Geocode cache and precompute

This project uses OpenStreetMap Nominatim for free geocoding. To avoid rate limiting
and to make deployments stable, precompute the geocodes for the hard-coded
`CITIES` and `MICRO_HUBS` in `src/app.py` and commit them as `src/geocode_cache.json`.

Quick steps

1. Locally, set your contact email (Nominatim requires contact info):

```bash
export NOMINATIM_EMAIL="your.email@example.com"
```

2. Run the precompute script (this writes `src/geocode_cache.sample.json`):

```bash
python tools/pregeocode.py
```

3. Review `src/geocode_cache.sample.json`. If everything looks correct, rename or copy
   it to `src/geocode_cache.json` before deploying:

```bash
cp src/geocode_cache.sample.json src/geocode_cache.json
git add src/geocode_cache.json
git commit -m "Add precomputed geocode cache"
git push
```

Notes
- The script sleeps 1s between requests to be polite to Nominatim.
- If you deploy to an environment without persistent disk, keep the cache committed
  or provide a URL (S3/GCS) and modify `app.py` to fetch the cache on startup.
