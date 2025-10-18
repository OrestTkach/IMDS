#!/usr/bin/env python3
"""
Precompute geocodes for CITIES and MICRO_HUBS defined in `src/app.py`.

Usage:
  export NOMINATIM_EMAIL="your.email@example.com"
  python tools/pregeocode.py

This script reads `src/app.py` (AST) to extract the CITIES and MICRO_HUBS
definitions without executing the Streamlit app, then queries Nominatim
and writes `src/geocode_cache.sample.json` which you can review and
rename to `src/geocode_cache.json` before deploying.
"""
import ast
import json
import os
import time
from pathlib import Path
from typing import List, Tuple

import requests


ROOT = Path(__file__).resolve().parents[1]
APP_PY = ROOT / "src" / "app.py"
OUT_SAMPLE = ROOT / "src" / "geocode_cache.sample.json"


def extract_defs() -> Tuple[List[Tuple], List[Tuple]]:
    """Return (CITIES, MICRO_HUBS) by parsing src/app.py with ast.literal_eval."""
    src = APP_PY.read_text(encoding="utf-8")
    mod = ast.parse(src)
    cities = []
    micros = []
    for node in mod.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name == "CITIES":
                try:
                    cities = ast.literal_eval(node.value)
                except Exception:
                    pass
            if name == "MICRO_HUBS":
                try:
                    micros = ast.literal_eval(node.value)
                except Exception:
                    pass
    return cities, micros


def geocode(addr: str, email: str) -> Tuple[float, float] | None:
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": addr, "format": "json", "limit": 1, "addressdetails": 0}
    headers = {"User-Agent": f"SquareMiles-Pregeocode/1.0 (contact: {email})"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.ok:
            data = r.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        print(f"Request failed for {addr}: {e}")
    return None


def main():
    email = os.environ.get("NOMINATIM_EMAIL")
    if not email:
        print("Please set NOMINATIM_EMAIL in the environment to a valid contact email.")
        return

    cities, micros = extract_defs()
    if not cities and not micros:
        print("Could not parse CITIES or MICRO_HUBS from src/app.py")
        return

    cache = {}
    # preserve existing sample if present
    if OUT_SAMPLE.exists():
        try:
            cache = json.loads(OUT_SAMPLE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    tasks = []
    for city in cities:
        # city is tuple (city, hub_name, hub_addr)
        if len(city) >= 3:
            tasks.append((city[2], f"CENTRAL: {city[1]} ({city[0]})"))
    for m in micros:
        # micro tuple (city, key, name, addr)
        if len(m) >= 4:
            tasks.append((m[3], f"MICRO: {m[1]} {m[2]} ({m[0]})"))

    print(f"Will geocode {len(tasks)} addresses (respectful delay 1s).\n")
    for idx, (addr, meta) in enumerate(tasks, start=1):
        if addr in cache:
            print(f"[{idx}/{len(tasks)}] cached -> {meta} = {cache[addr]}")
            continue
        print(f"[{idx}/{len(tasks)}] geocoding -> {meta}: {addr}")
        res = geocode(addr, email)
        cache[addr] = list(res) if res else None
        # be polite to Nominatim
        time.sleep(1.0)

    # write sample cache
    try:
        OUT_SAMPLE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote sample cache to {OUT_SAMPLE}")
    except Exception as e:
        print(f"Failed to write sample cache: {e}")


if __name__ == "__main__":
    main()
