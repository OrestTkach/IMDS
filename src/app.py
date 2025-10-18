#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SquareMiles – City-Specific Multimodal Optimizer (HARD-CODED CITIES & HUBS)

Run: streamlit run app.py
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium
import streamlit.components.v1 as components
import time
import os
import json
from pathlib import Path

# =============================
# UI / PAGE
# =============================
st.set_page_config(page_title="SquareMiles – City-Specific Multimodal Optimizer", layout="wide")
st.title("SquareMiles – City-Specific Multimodal Optimizer")
st.caption("Address input • City-aware modes • Open-data routing • Cost & CO₂ optimization • ESG dashboard")

# =============================
# DATA MODELS
# =============================
@dataclass(frozen=True)
class Node:
    key: str
    name: str
    lat: float
    lon: float
    kind: str 

# =============================
# FLEET MODES & FACTORS (FROM EXCEL)
# =============================
MODES: Dict[str, Dict] = {
    'truck': {'label':'Truck (HGV)','emission_kg_per_km':0.448,'cost_trans':0.508,'cost_labour':0.289190,'speed_kph':23.45,'osrm_profile':'driving'},
    'elcv': {'label':'Electric LCV','emission_kg_per_km':0.346,'cost_trans':0.070,'cost_labour':0.289190,'speed_kph':23.45,'osrm_profile':'driving'},
    'small_van': {'label':'Small Van (ICE)','emission_kg_per_km':0.210,'cost_trans':0.179,'cost_labour':0.289190,'speed_kph':23.45,'osrm_profile':'driving'},
    'cargo_bike': {'label':'Cargo Bike','emission_kg_per_km':0.033,'cost_trans':0.004,'cost_labour':0.419688,'speed_kph':16.0,'osrm_profile':'cycling'},
    'e_scooter_trailer': {'label':'E-Scooter + Trailer','emission_kg_per_km':0.025,'cost_trans':0.005,'cost_labour':0.479643,'speed_kph':14.0,'osrm_profile':'cycling'},
    'autonomous_robot': {'label':'Autonomous Delivery Robot','emission_kg_per_km':0.010,'cost_trans':0.005,'cost_labour':1.119167,'speed_kph':6.0,'osrm_profile':'walking'},
    'cargo_tram': {'label':'Cargo Tram','emission_kg_per_km':0.0,'cost_trans':0.808,'cost_labour':0.335750,'speed_kph':20.0,'osrm_profile':None},
    'cargo_bus': {'label':'Cargo Bus / Night Bus','emission_kg_per_km':0.822,'cost_trans':0.366,'cost_labour':0.289190,'speed_kph':23.45,'osrm_profile':'driving'},
    'boat': {'label':'Urban River Barge / Boat','emission_kg_per_km':0.033,'cost_trans':31.718,'cost_labour':0.559583,'speed_kph':12.0,'osrm_profile':None},
}

# Additional factors for the ESG dashboard (noise_idx from Excel)
MODE_ESG = {
    'truck': {'fuel_l_per_km':0.30,'electricity_kwh_per_km':0.0,'road_space_eq':3.0,'noise_idx':0.84,'safety_risk':0.8,'capex_k$':150},
    'small_van': {'fuel_l_per_km':0.12,'electricity_kwh_per_km':0.0,'road_space_eq':1.6,'noise_idx':0.68,'safety_risk':0.6,'capex_k$':35},
    'elcv': {'fuel_l_per_km':0.0,'electricity_kwh_per_km':0.20,'road_space_eq':1.6,'noise_idx':0.68,'safety_risk':0.5,'capex_k$':45},
    'cargo_bike': {'fuel_l_per_km':0.0,'electricity_kwh_per_km':0.05,'road_space_eq':0.4,'noise_idx':0.40,'safety_risk':0.3,'capex_k$':7},
    'e_scooter_trailer': {'fuel_l_per_km':0.0,'electricity_kwh_per_km':0.03,'road_space_eq':0.2,'noise_idx':0.24,'safety_risk':0.25,'capex_k$':3},
    'autonomous_robot': {'fuel_l_per_km':0.0,'electricity_kwh_per_km':0.02,'road_space_eq':0.1,'noise_idx':0.24,'safety_risk':0.2,'capex_k$':12},
    'cargo_tram': {'fuel_l_per_km':0.0,'electricity_kwh_per_km':0.40,'road_space_eq':0.0,'noise_idx':0.72,'safety_risk':0.15,'capex_k$':500},
    'cargo_bus': {'fuel_l_per_km':0.08,'electricity_kwh_per_km':0.0,'road_space_eq':1.8,'noise_idx':0.88,'safety_risk':0.5,'capex_k$':250},
    'boat': {'fuel_l_per_km':0.05,'electricity_kwh_per_km':0.0,'road_space_eq':0.0,'noise_idx':0.56,'safety_risk':0.3,'capex_k$':350},
}
KWH_TO_LITRE_EQ = 0.25

# =============================
# CITY LIST & AVAILABILITY RULES (FROM EXCEL "Yes")
# =============================
CITY_LIST = [
    "Hamburg, Germany","Shanghai, China","Amsterdam, Netherlands","New York City, USA","London, UK",
    "São Paulo, Brazil","Nairobi, Kenya","Mumbai, India","Singapore, Singapore","Istanbul, Turkey",
]
CITY_MODE_CAPS = {
    'Hamburg, Germany': {'allowed':['boat','cargo_bike','cargo_bus','cargo_tram','elcv','small_van','truck'],'notes':'dense waterways & strong bike infra; no robots, no tram freight'},
    'Shanghai, China': {'allowed':['autonomous_robot','cargo_bike','cargo_tram','e_scooter_trailer','small_van','truck'],'notes':'robots pilot zones; extensive waterways; tram corridors exist'},
    'Amsterdam, Netherlands': {'allowed':['boat','cargo_bike','cargo_bus','cargo_tram','elcv','truck'],'notes':'canals & tram; scooters widely piloted; no robots'},
    'New York City, USA': {'allowed':['autonomous_robot','cargo_bike','cargo_bus','small_van','truck'],'notes':'clean trucks, cargo bikes; boat feasible; no tram/robots'},
    'London, UK': {'allowed':['autonomous_robot','cargo_bike','cargo_bus','elcv','truck'],'notes':'ULEZ; cargo bus at night; scooters allowed in trials; no cargo tram'},
    'São Paulo, Brazil': {'allowed':['cargo_bus','small_van','truck'],'notes':'no urban barges/boats for last-mile; scooters constrained; no robots/tram'},
    'Nairobi, Kenya': {'allowed':['cargo_bus','small_van','truck'],'notes':'no boats/tram/robots; bikes feasible'},
    'Mumbai, India': {'allowed':['boat','cargo_bike','cargo_bus','small_van','truck'],'notes':'coastal/creeks allow boat in some corridors; no tram/robots'},
    'Singapore, Singapore': {'allowed':['boat','cargo_bike','cargo_bus','elcv','truck'],'notes':'strict PMD rules (no public e-scooters); high compliance; no robots/tram'},
    'Istanbul, Turkey': {'allowed':['boat','cargo_bus','cargo_tram','truck'],'notes':'tram present; Bosphorus/Golden Horn allow boats; no scooters/robots'},
}

# =============================
# HARD-CODED CENTRAL HUBS & 10 MICRO-HUBS PER CITY
# =============================
CITIES = [
    ("Hamburg, Germany","Billbrook Central Warehouse","Billbrookdeich 100, 22113 Hamburg, Germany"),
    ("Shanghai, China","Pudong Central Warehouse","200 Century Ave, Pudong, Shanghai, China"),
    ("Amsterdam, Netherlands","Westpoort Central Hub","Isolatorweg 36, 1014 AS Amsterdam, Netherlands"),
    ("New York City, USA","Midtown West Central Hub","620 W 42nd St, New York, NY 10036, USA"),
    ("London, UK","Canary Wharf Central Hub","1 Canada Square, London E14 5AB, UK"),
    ("São Paulo, Brazil","Marginal Tietê Central Hub","Av. Marquês de São Vicente 2210, São Paulo, Brazil"),
    ("Nairobi, Kenya","Mombasa Road Central Hub","Sameer Business Park, Mombasa Road, Nairobi, Kenya"),
    ("Mumbai, India","Bhiwandi Central Warehouse","Bhiwandi, Maharashtra 421302, India"),
    ("Singapore, Singapore","Jurong Port Central Hub","5 Jurong Port Rd, Singapore 619318"),
    ("Istanbul, Turkey","İkitelli Central Warehouse","İkitelli OSB, Başakşehir, İstanbul, Türkiye"),
]

MICRO_HUBS = [
    # ---------------- Hamburg ----------------
    ("Hamburg, Germany","HH-MH1","HafenCity","Großer Grasbrook, 20457 Hamburg, Germany"),
    ("Hamburg, Germany","HH-MH2","Altona","Altona, Hamburg, Germany"),
    ("Hamburg, Germany","HH-MH3","Wandsbek","Wandsbek, Hamburg, Germany"),
    ("Hamburg, Germany","HH-MH4","Bergedorf","Bergedorf, Hamburg, Germany"),
    ("Hamburg, Germany","HH-MH5","Eppendorf","Eppendorf, Hamburg, Germany"),
    ("Hamburg, Germany","HH-MH6","St. Pauli","St. Pauli, Hamburg, Germany"),
    ("Hamburg, Germany","HH-MH7","Harburg","Harburg, Hamburg, Germany"),
    ("Hamburg, Germany","HH-MH8","Bahrenfeld","Bahrenfeld, Hamburg, Germany"),
    ("Hamburg, Germany","HH-MH9","Niendorf","Niendorf, Hamburg, Germany"),
    ("Hamburg, Germany","HH-MH10","Rothenburgsort","Rothenburgsort, Hamburg, Germany"),
    # ---------------- Shanghai ----------------
    ("Shanghai, China","SH-MH1","Lujiazui","Pudong Lujiazui, Shanghai, China"),
    ("Shanghai, China","SH-MH2","Jing'an Temple","1686 Nanjing West Rd, Jing'an, Shanghai, China"),
    ("Shanghai, China","SH-MH3","Xintiandi","Lane 181 Taicang Rd, Huangpu, Shanghai, China"),
    ("Shanghai, China","SH-MH4","Hongqiao","Hongqiao Railway Station, Shanghai, China"),
    ("Shanghai, China","SH-MH5","Zhangjiang Hi-Tech Park","Zhangjiang, Pudong, Shanghai, China"),
    ("Shanghai, China","SH-MH6","Waigaoqiao","Waigaoqiao, Pudong, Shanghai, China"),
    ("Shanghai, China","SH-MH7","Yangpu","Yangpu District, Shanghai, China"),
    ("Shanghai, China","SH-MH8","Minhang","Minhang District, Shanghai, China"),
    ("Shanghai, China","SH-MH9","Qibao","Qibao, Minhang, Shanghai, China"),
    ("Shanghai, China","SH-MH10","Wujiaochang","Wujiaochang, Yangpu, Shanghai, China"),
    # ---------------- Amsterdam ----------------
    ("Amsterdam, Netherlands","AMS-MH1","Dam Square","Dam, 1012 JS Amsterdam, Netherlands"),
    ("Amsterdam, Netherlands","AMS-MH2","De Pijp / Albert Cuyp","Albert Cuypstraat, 1073 BD Amsterdam, Netherlands"),
    ("Amsterdam, Netherlands","AMS-MH3","Sloterdijk","Station Sloterdijk, Amsterdam, Netherlands"),
    ("Amsterdam, Netherlands","AMS-MH4","Zuidas","Zuidas, Amsterdam, Netherlands"),
    ("Amsterdam, Netherlands","AMS-MH5","Jordaan","Jordaan, Amsterdam, Netherlands"),
    ("Amsterdam, Netherlands","AMS-MH6","Noord / Buiksloterweg","Buiksloterweg, 1031 BT Amsterdam, Netherlands"),
    ("Amsterdam, Netherlands","AMS-MH7","Bijlmer Arena","Johan Cruijff Boulevard, 1101 DS Amsterdam, Netherlands"),
    ("Amsterdam, Netherlands","AMS-MH8","Museumplein","Museumplein, 1071 DJ Amsterdam, Netherlands"),
    ("Amsterdam, Netherlands","AMS-MH9","Westerpark","Westerpark, Amsterdam, Netherlands"),
    ("Amsterdam, Netherlands","AMS-MH10","Oostpoort","Winkelcentrum Oostpoort, 1093 Amsterdam, Netherlands"),
    # ---------------- New York City ----------------
    ("New York City, USA","NYC-MH1","World Trade Center","185 Greenwich St, New York, NY 10007, USA"),
    ("New York City, USA","NYC-MH2","Grand Central","89 E 42nd St, New York, NY 10017, USA"),
    ("New York City, USA","NYC-MH3","Harlem 125th","11 W 125th St, New York, NY 10027, USA"),
    ("New York City, USA","NYC-MH4","Brooklyn Navy Yard","63 Flushing Ave, Brooklyn, NY 11205, USA"),
    ("New York City, USA","NYC-MH5","Long Island City","Court Square, Queens, NY 11101, USA"),
    ("New York City, USA","NYC-MH6","Williamsburg","Bedford Ave, Brooklyn, NY 11211, USA"),
    ("New York City, USA","NYC-MH7","Upper East 86/Lex","86th St & Lexington Ave, New York, NY 10028, USA"),
    ("New York City, USA","NYC-MH8","Union Square","201 Park Ave S, New York, NY 10003, USA"),
    ("New York City, USA","NYC-MH9","SoHo","Prince St & Broadway, New York, NY 10012, USA"),
    ("New York City, USA","NYC-MH10","Astoria","31-01 Steinway St, Queens, NY 11103, USA"),
    # ---------------- London ----------------
    ("London, UK","LDN-MH1","King's Cross","Euston Rd, London N1 9AL, UK"),
    ("London, UK","LDN-MH2","Paddington","Praed St, London W2 1HB, UK"),
    ("London, UK","LDN-MH3","Shoreditch","Shoreditch High St, London E1 6PQ, UK"),
    ("London, UK","LDN-MH4","Borough Market","8 Southwark St, London SE1 1LB, UK"),
    ("London, UK","LDN-MH5","Greenwich","Greenwich, London SE10, UK"),
    ("London, UK","LDN-MH6","Hammersmith","Hammersmith Broadway, London W6, UK"),
    ("London, UK","LDN-MH7","Brixton","Brixton Station Rd, London SW9 8QB, UK"),
    ("London, UK","LDN-MH8","Camden","Camden Market, London NW1, UK"),
    ("London, UK","LDN-MH9","Stratford","Station St, London E15 1AZ, UK"),
    ("London, UK","LDN-MH10","Wembley","Wembley Stadium, London HA9 0WS, UK"),
    # ---------------- São Paulo ----------------
    ("São Paulo, Brazil","SP-MH1","Luz / CPTM","Praça da Luz, São Paulo, Brazil"),
    ("São Paulo, Brazil","SP-MH2","Paulista Ave","Av. Paulista 1578, São Paulo, Brazil"),
    ("São Paulo, Brazil","SP-MH3","Pinheiros","Rua Paes Leme 524, São Paulo, Brazil"),
    ("São Paulo, Brazil","SP-MH4","Morumbi","Av. Giovanni Gronchi 5819, São Paulo, Brazil"),
    ("São Paulo, Brazil","SP-MH5","Mooca","Rua da Mooca 2500, São Paulo, Brazil"),
    ("São Paulo, Brazil","SP-MH6","Itaquera","Rua Itaquera 1100, São Paulo, Brazil"),
    ("São Paulo, Brazil","SP-MH7","Vila Mariana","Rua Domingos de Morais 2564, São Paulo, Brazil"),
    ("São Paulo, Brazil","SP-MH8","Tatuapé","Rua Tuiuti 1000, São Paulo, Brazil"),
    ("São Paulo, Brazil","SP-MH9","Santo Amaro","Av. das Nações Unidas 22540, São Paulo, Brazil"),
    ("São Paulo, Brazil","SP-MH10","Guarulhos Cargo","Rod. Hélio Smidt, Guarulhos, Brazil"),
    # ---------------- Nairobi ----------------
    ("Nairobi, Kenya","NRB-MH1","Westlands","Westlands, Nairobi, Kenya"),
    ("Nairobi, Kenya","NRB-MH2","Kilimani","Kilimani, Nairobi, Kenya"),
    ("Nairobi, Kenya","NRB-MH3","CBD","City Hall Way, Nairobi, Kenya"),
    ("Nairobi, Kenya","NRB-MH4","Industrial Area","Addis Ababa Rd, Industrial Area, Nairobi, Kenya"),
    ("Nairobi, Kenya","NRB-MH5","Eastleigh","Eastleigh, Nairobi, Kenya"),
    ("Nairobi, Kenya","NRB-MH6","Karen","Karen, Nairobi, Kenya"),
    ("Nairobi, Kenya","NRB-MH7","Langata","Langata Rd, Nairobi, Kenya"),
    ("Nairobi, Kenya","NRB-MH8","Gigiri","Gigiri, Nairobi, Kenya"),
    ("Nairobi, Kenya","NRB-MH9","Kasarani","Kasarani, Nairobi, Kenya"),
    ("Nairobi, Kenya","NRB-MH10","Ruiru","Ruiru, Kiambu County, Kenya"),
    # ---------------- Mumbai ----------------
    ("Mumbai, India","MMB-MH1","Andheri East","Andheri East, Mumbai, Maharashtra, India"),
    ("Mumbai, India","MMB-MH2","BKC","Bandra Kurla Complex, Mumbai, Maharashtra, India"),
    ("Mumbai, India","MMB-MH3","Dadar","Dadar, Mumbai, Maharashtra, India"),
    ("Mumbai, India","MMB-MH4","Colaba","Colaba, Mumbai, Maharashtra, India"),
    ("Mumbai, India","MMB-MH5","Powai","Powai, Mumbai, Maharashtra, India"),
    ("Mumbai, India","MMB-MH6","Vashi","Vashi, Navi Mumbai, Maharashtra, India"),
    ("Mumbai, India","MMB-MH7","Thane West","Thane West, Thane, Maharashtra, India"),
    ("Mumbai, India","MMB-MH8","Goregaon East","Goregaon East, Mumbai, Maharashtra, India"),
    ("Mumbai, India","MMB-MH9","Mulund West","Mulund West, Mumbai, Maharashtra, India"),
    ("Mumbai, India","MMB-MH10","Chembur","Chembur, Mumbai, Maharashtra, India"),
    # ---------------- Singapore ----------------
    ("Singapore, Singapore","SGP-MH1","Raffles Place","Raffles Place, Singapore"),
    ("Singapore, Singapore","SGP-MH2","Orchard","Orchard Road, Singapore"),
    ("Singapore, Singapore","SGP-MH3","Ang Mo Kio","Ang Mo Kio Hub, Singapore"),
    ("Singapore, Singapore","SGP-MH4","Woodlands","Woodlands MRT Station, Singapore"),
    ("Singapore, Singapore","SGP-MH5","Tampines","Tampines MRT Station, Singapore"),
    ("Singapore, Singapore","SGP-MH6","Paya Lebar","Paya Lebar Quarter, Singapore"),
    ("Singapore, Singapore","SGP-MH7","Jurong East","Jurong East MRT Station, Singapore"),
    ("Singapore, Singapore","SGP-MH8","Bukit Panjang","Bukit Panjang Plaza, Singapore"),
    ("Singapore, Singapore","SGP-MH9","Chinatown","Chinatown, Singapore"),
    ("Singapore, Singapore","SGP-MH10","Toa Payoh","Toa Payoh Central, Singapore"),
    # ---------------- Istanbul ----------------
    ("Istanbul, Turkey","IST-MH1","Kadıköy Pier","Kadıköy İskelesi, İstanbul, Türkiye"),
    ("Istanbul, Turkey","IST-MH2","Taksim","Taksim Meydanı, İstanbul, Türkiye"),
    ("Istanbul, Turkey","IST-MH3","Beşiktaş","Beşiktaş, İstanbul, Türkiye"),
    ("Istanbul, Turkey","IST-MH4","Bakırköy","Bakırköy, İstanbul, Türkiye"),
    ("Istanbul, Turkey","IST-MH5","Ümraniye","Ümraniye, İstanbul, Türkiye"),
    ("Istanbul, Turkey","IST-MH6","Sarıyer","Sarıyer, İstanbul, Türkiye"),
    ("Istanbul, Turkey","IST-MH7","Beylikdüzü","Beylikdüzü, İstanbul, Türkiye"),
    ("Istanbul, Turkey","IST-MH8","Pendik","Pendik, İstanbul, Türkiye"),
    ("Istanbul, Turkey","IST-MH9","Kartal","Kartal, İstanbul, Türkiye"),
    ("Istanbul, Turkey","IST-MH10","Sultanahmet","Sultanahmet, Fatih, İstanbul, Türkiye"),
]

# =============================
# OPEN DATA HELPERS
# =============================
@st.cache_data(show_spinner=False)
def geocode_address(addr: str) -> Optional[Tuple[float, float]]:
    # Simple on-disk cache to avoid repeated Nominatim calls across app restarts
    cache_file = Path(__file__).parent / "geocode_cache.json"
    try:
        if cache_file.exists():
            with cache_file.open("r", encoding="utf-8") as fh:
                _cache = json.load(fh)
        else:
            _cache = {}
    except Exception:
        _cache = {}

    key = addr.strip()
    if not key:
        return None

    # Return cached value if present (including explicit nulls)
    if key in _cache:
        val = _cache[key]
        if val is None:
            return None
        return (val[0], val[1])

    url = "https://nominatim.openstreetmap.org/search"
    # Prefer Streamlit secrets (for Streamlit Cloud), then environment variable, then fallback demo
    email = "ot014@hdm-stuttgart.de"
    try:
        email = st.secrets.get("NOMINATIM_EMAIL") if hasattr(st, 'secrets') else None
    except Exception:
        email = None
    if not email:
        email = os.environ.get("NOMINATIM_EMAIL", "demo@example.com")
    params = {"q": key, "format": "json", "limit": 1, "addressdetails": 0}
    headers = {"User-Agent": f"SquareMiles-Streamlit/1.0 (contact: {email})"}

    # retries with exponential backoff for rate-limits / transient errors
    for attempt in range(4):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=12)
        except requests.RequestException:
            r = None

        if r is None:
            wait = 0.5 * (2 ** attempt)
            time.sleep(wait)
            continue

        if r.status_code == 429:
            # too many requests — backoff
            wait = 1 + attempt * 2
            time.sleep(wait)
            continue

        if r.ok:
            try:
                jlist = r.json()
                if jlist:
                    lat = float(jlist[0]["lat"])
                    lon = float(jlist[0]["lon"])
                    _cache[key] = [lat, lon]
                    try:
                        with cache_file.open("w", encoding="utf-8") as fh:
                            json.dump(_cache, fh, ensure_ascii=False, indent=2)
                    except Exception:
                        pass
                    return (lat, lon)
                else:
                    _cache[key] = None
                    try:
                        with cache_file.open("w", encoding="utf-8") as fh:
                            json.dump(_cache, fh, ensure_ascii=False, indent=2)
                    except Exception:
                        pass
                    return None
            except Exception:
                # malformed JSON — treat as transient
                wait = 0.5 * (2 ** attempt)
                time.sleep(wait)
                continue
        else:
            # other HTTP errors — short wait then retry
            wait = 0.5 * (2 ** attempt)
            time.sleep(wait)
            continue

    # All retries exhausted: cache miss as None to avoid repeated attempts until manual cache clear
    try:
        _cache[key] = None
        with cache_file.open("w", encoding="utf-8") as fh:
            json.dump(_cache, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return None

def haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = (math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2)
    return 2 * 6371.0088 * math.asin(math.sqrt(h))

@st.cache_data(show_spinner=False)
def osrm_distance_and_shape(a, b, profile):
    try:
        url = f"https://router.project-osrm.org/route/v1/{profile}/{a[1]},{a[0]};{b[1]},{b[0]}?overview=full&geometries=geojson"
        r = requests.get(url, timeout=12)
        if r.ok:
            data = r.json()
            if data.get("routes"):
                dist_km = data["routes"][0]["distance"] / 1000.0
                coords = data["routes"][0]["geometry"]["coordinates"]
                return dist_km, [[c[1], c[0]] for c in coords]
    except Exception:
        pass
    return None

def route_with_engine(a, b, mode_key, modes_dict, engine):
    m = modes_dict[mode_key]
    if not m.get("osrm_profile"):
        d = haversine_km(a, b)
        return d, [[a[0], a[1]], [b[0], b[1]]]
    if engine == "OSRM (open data)":
        r = osrm_distance_and_shape(a, b, m["osrm_profile"])
        if r: return r
    d = haversine_km(a, b)
    return d, [[a[0], a[1]], [b[0], b[1]]]

def impact_for_leg(distance_km: float, mode_key: str) -> Tuple[float, float, float]:
    m = MODES[mode_key]
    time_h = distance_km / max(m["speed_kph"], 1e-6)
    co2_kg = m["emission_kg_per_km"] * distance_km
    cost = (m["cost_trans"] + m["cost_labour"]) * distance_km
    return time_h, co2_kg, cost

def eval_candidate_via_hub(origin, hub: Node, dest, m1: str, m2: str, engine: str):
    segs: List[Dict] = []
    d1, g1 = route_with_engine(origin, (hub.lat, hub.lon), m1, MODES, engine)
    t1, e1, c1 = impact_for_leg(d1, m1)
    segs.append({"from":"Start","to":hub.name,"mode":m1,"distance_km":round(d1,3),"time_h":t1,"co2_kg":e1,"cost":c1,"geometry":g1})
    d2, g2 = route_with_engine((hub.lat, hub.lon), dest, m2, MODES, engine)
    t2, e2, c2 = impact_for_leg(d2, m2)
    segs.append({"from":hub.name,"to":"Destination","mode":m2,"distance_km":round(d2,3),"time_h":t2,"co2_kg":e2,"cost":c2,"geometry":g2})
    totals = {"distance_km":round(d1+d2,3),"time_h":t1+t2,"co2_kg":e1+e2,"cost":c1+c2}
    return segs, totals

def eval_candidate_direct(origin, dest, mode_key: str, engine: str):
    segs: List[Dict] = []
    d, g = route_with_engine(origin, dest, mode_key, MODES, engine)
    t, e, c = impact_for_leg(d, mode_key)
    segs.append({"from":"Start","to":"Destination","mode":mode_key,"distance_km":round(d,3),"time_h":t,"co2_kg":e,"cost":c,"geometry":g})
    totals = {"distance_km":round(d,3),"time_h":t,"co2_kg":e,"cost":c}
    return segs, totals

@st.cache_data(show_spinner=True)
def build_city_graph(cities, micro_rows):
    graph = {}
    for city, hub_name, hub_addr in cities:
        ch_geo = geocode_address(hub_addr)
        if not ch_geo:
            continue
        graph[city] = {"city": city, "central_hub": Node("CENTRAL", hub_name, ch_geo[0], ch_geo[1], "depot"), "micro_hubs": []}
    by_city: Dict[str, List[Tuple[str,str,str]]] = {}
    for c, key, name, addr in micro_rows:
        by_city.setdefault(c, []).append((key, name, addr))
    for c, rows in by_city.items():
        if c not in graph:
            continue
        for key, name, addr in rows[:10]:
            mh_geo = geocode_address(addr)
            if mh_geo:
                graph[c]["micro_hubs"].append(Node(key, name, mh_geo[0], mh_geo[1], "hub"))
    graph = {k:v for k,v in graph.items() if v["micro_hubs"]}
    return graph

CITY_GRAPH = build_city_graph(CITIES, MICRO_HUBS)
if not CITY_GRAPH:
    st.error("No cities could be geocoded with micro-hubs. Please check addresses.")
    st.stop()

# =============================
# SEARCH (supports direct or fixed-hub)
# =============================
@st.cache_data(show_spinner=True)
def search_best_routes(city_name: str, city_obj, origin, dest, engine: str,
                       via_hub: bool, fixed_hub: Optional[Node]):
    allowed = CITY_MODE_CAPS[city_name]["allowed"]
    results = []
    if via_hub:
        hubs = [fixed_hub] if fixed_hub else city_obj["micro_hubs"]
        for hub in hubs:
            for m1 in allowed:
                for m2 in allowed:
                    segs, totals = eval_candidate_via_hub(origin, hub, dest, m1, m2, engine)
                    results.append({"hub":hub,"modes":(m1,m2),"segments":segs,"totals":totals})
    else:
        for m in allowed:
            segs, totals = eval_candidate_direct(origin, dest, m, engine)
            results.append({"hub":None,"modes":(m,), "segments":segs, "totals":totals})

    if not results:
        return {"all":[], "min_co2":None, "min_cost":None, "best_combo":None}

    min_co2 = min(results, key=lambda r: r["totals"]["co2_kg"])
    min_cost = min(results, key=lambda r: r["totals"]["cost"])
    co2_vals = [r["totals"]["co2_kg"] for r in results]
    cost_vals = [r["totals"]["cost"] for r in results]
    cmin, cmax = min(co2_vals), max(co2_vals)
    kmin, kmax = min(cost_vals), max(cost_vals)

    def norm(x, lo, hi): return 0.0 if hi==lo else (x-lo)/(hi-lo)
    for r in results:
        r["score_norm_co2"]  = norm(r["totals"]["co2_kg"], cmin, cmax)
        r["score_norm_cost"] = norm(r["totals"]["cost"], kmin, kmax)
    return {"all":results, "min_co2":min_co2, "min_cost":min_cost, "best_combo":None}

def pick_best_combo(results_dict, weight_cost: float):
    res = results_dict["all"]
    if not res: return None
    w = max(0.0, min(1.0, weight_cost))
    return min(res, key=lambda r: w*r["score_norm_cost"] + (1.0-w)*r["score_norm_co2"])

# =============================
# ESG DASHBOARD
# =============================
def aggregate_mode_km(segments: List[Dict]) -> Dict[str, float]:
    agg = {}
    for s in segments:
        agg[s["mode"]] = agg.get(s["mode"], 0.0) + s["distance_km"]
    return agg

def esg_metrics_for_segments(segments: List[Dict]):
    km_by_mode = aggregate_mode_km(segments)
    fuel_l = 0.0; kwh = 0.0; road_space = 0.0; noise = 0.0; safety = 0.0
    for m, km in km_by_mode.items():
        f = MODE_ESG.get(m, {"fuel_l_per_km":0.0,"electricity_kwh_per_km":0.0,"road_space_eq":1.0,"noise_idx":0.5,"safety_risk":0.5})
        fuel_l += f["fuel_l_per_km"] * km
        kwh += f["electricity_kwh_per_km"] * km
        road_space += f["road_space_eq"] * km
        noise  += f["noise_idx"] * km
        safety += f["safety_risk"] * km
    return {"fuel_l":fuel_l, "kwh":kwh, "road_space_eq_km":road_space, "noise_index_km":noise, "safety_risk_km":safety}

def delta_percent(a: float, b: float) -> float:
    if a == 0: return float("inf") if b != 0 else 0.0
    return (b - a) / a * 100.0

def badge(value: float, unit: str, invert_good: bool=False):
    good = (value < 0) if invert_good else (value > 0)
    color = "green" if good else ("red" if (not good and value != 0) else "gray")
    sign = "▲" if value > 0 else ("▼" if value < 0 else "→")
    return f":{color}[{sign} {value:+.1f}{unit}]"

def render_esg_dashboard(base_pack, scen_pack, scen_title: str):
    base_segs, base_tot = base_pack
    sc_segs, sc_tot = scen_pack
    base_esg = esg_metrics_for_segments(base_segs)
    scen_esg = esg_metrics_for_segments(sc_segs)

    p_co2 = delta_percent(base_tot["co2_kg"], sc_tot["co2_kg"])
    p_fuel = delta_percent(base_esg["fuel_l"], scen_esg["fuel_l"])
    p_congestion = delta_percent(base_esg["road_space_eq_km"], scen_esg["road_space_eq_km"])
    p_jobs = delta_percent(base_tot["time_h"], sc_tot["time_h"])
    p_safety = delta_percent(base_esg["safety_risk_km"], scen_esg["safety_risk_km"])
    p_noise = delta_percent(base_esg["noise_index_km"], scen_esg["noise_index_km"])
    p_cost = delta_percent(base_tot["cost"], sc_tot["cost"])
    p_ttd  = delta_percent(base_tot["time_h"], sc_tot["time_h"])

    green_capex_k = 0.0
    green_modes = {"elcv","cargo_bike","e_scooter_trailer","autonomous_robot","cargo_tram","cargo_bus","boat"}
    km_by_mode = aggregate_mode_km(sc_segs)
    for m, km in km_by_mode.items():
        if m in green_modes:
            green_capex_k += MODE_ESG.get(m, {}).get("capex_k$", 0) * 0.02
    monthly_saving = max(0.0, (base_tot["cost"] - sc_tot["cost"]))
    roi_months = (green_capex_k*1000) / monthly_saving if monthly_saving > 0 else float("inf")
    subsidy_needed = max(0.0, (green_capex_k*1000 - 12*monthly_saving))

    st.subheader(f"Impact Dashboard for {scen_title}")
    st.markdown("**Legend:** 🌍 Environment • 👥 Social • 💰 Economic")

    e1, e2, e3 = st.columns(3)
    with e1:
        st.markdown("### 🌍 Environmental")
        st.write(f"CO₂ saved: {badge(p_co2, '%', invert_good=True)}  (baseline {base_tot['co2_kg']:.2f} kg → {sc_tot['co2_kg']:.2f} kg)")
        st.write(f"Fuel avoided: {badge(p_fuel, '%', invert_good=True)}")
        st.write(f"Traffic congestion change: {badge(p_congestion, '%', invert_good=True)}")
    with e2:
        st.markdown("### 👥 Social")
        st.write(f"Jobs created (labor hours): {badge(p_jobs, '%', invert_good=False)}")
        st.write(f"Improved safety (risk index): {badge(p_safety, '%', invert_good=True)}")
        st.write(f"Noise reduction: {badge(p_noise, '%', invert_good=True)}")
    with e3:
        st.markdown("### 💰 Economic")
        st.write(f"Operating cost delta: {badge(p_cost, '%', invert_good=True)}")
        st.write(f"Time-to-delivery delta: {badge(p_ttd, '%', invert_good=True)}")
        st.write(f"ROI on green modes (months): **{('∞' if roi_months==float('inf') else f'{roi_months:.1f}')}**")
        st.write(f"Subsidies needed (12m breakeven): **${subsidy_needed:,.0f}**")

# =============================
# CITY POLICY LINKS (unchanged)
# =============================
CITY_POLICY_LINKS = {
    "Hamburg, Germany":[("Hamburg – Clean Air / Umweltzone info","https://www.hamburg.de/luftreinhaltung/"),
                        ("Freight delivery guidance (City of Hamburg)","https://www.hamburg.de/verkehr/")],
    "Shanghai, China":[("Shanghai Low-Emission Zones (overview)","https://transportpolicy.net/region/china/")],
    "Amsterdam, Netherlands":[("Amsterdam Zero-Emission City Logistics (ZES)","https://www.amsterdam.nl/en/traffic-transport/zero-emission/")],
    "New York City, USA":[("NYC Clean Trucks Program","https://www.nyccte.org/clean-trucks-program"),
                          ("Commercial Loading & Deliveries (NYC DOT)","https://www.nyc.gov/html/dot/html/motorist/commercial-vehicles.shtml")],
    "London, UK":[("London ULEZ","https://tfl.gov.uk/modes/driving/ultra-low-emission-zone"),
                  ("Freight & Deliveries (TfL)","https://tfl.gov.uk/info-for/deliveries-in-london")],
    "São Paulo, Brazil":[("São Paulo Vehicle Restriction & Urban Mobility","https://www.prefeitura.sp.gov.br/")],
    "Nairobi, Kenya":[("Nairobi mobility & logistics (NMS)","https://nms.go.ke/")],
    "Mumbai, India":[("Mumbai logistics & traffic management","https://mumbaicity.gov.in/")],
    "Singapore, Singapore":[("Singapore Green Plan / Clean Vehicles","https://www.lta.gov.sg/")],
    "Istanbul, Turkey":[("Istanbul transport authority (İBB Ulaşım)","https://ulasim.istanbul/")],
}

def policy_box(city_name: str):
    st.subheader("Supportive regulations & policies (open data links)")
    links = CITY_POLICY_LINKS.get(city_name, [])
    if not links:
        st.info("No policy links registered for this city yet.")
        return
    for title, url in links:
        st.markdown(f"- [{title}]({url})")
    with st.expander("How this supports corporate environmental goals (CSRD/ESRS & indirect costs)"):
        st.markdown("""
- **CSRD/ESRS** requires environmental disclosures (incl. Scope 1–3 where material).
- Cleaner last-mile reduces **CO₂ intensity per delivery** and aids target pathways.
- Compliance with **LEZ/ZES/ULEZ** avoids fines and detours ⇒ **lower indirect costs**.
- Metrics from this app (km, kg CO₂, cost) can feed **environmental assessments**.
""")

# =============================
# RENDERING HELPERS
# =============================
def render_map(segments, origin, dest, city_obj, hub=None, title="Route", key=None, show_hub_marker=True):
    center = ((origin[0]+dest[0])/2, (origin[1]+dest[1])/2)
    m = folium.Map(location=[center[0], center[1]], zoom_start=12, tiles="cartodbpositron")
    folium.Marker([origin[0], origin[1]], tooltip="Start", icon=folium.Icon(color="red")).add_to(m)
    folium.Marker([dest[0], dest[1]], tooltip="Destination", icon=folium.Icon(color="blue")).add_to(m)
    if hub and show_hub_marker:
        folium.Marker([hub.lat, hub.lon], tooltip=hub.name, icon=folium.Icon(color="green")).add_to(m)
    colors = {"truck":"gray","elcv":"green","small_van":"darkpurple","cargo_bike":"#2b8cbe",
              "e_scooter_trailer":"#756bb1","autonomous_robot":"#9467bd","cargo_tram":"#ff9896",
              "cargo_bus":"#8c564b","boat":"#ff7f00"}
    for s in segments:
        # Normalize geometry: ensure list of [lat(float), lon(float)] pairs
        geom = s.get("geometry")
        norm = []
        try:
            for p in geom:
                # accept (lat,lon) tuples or [lat,lon]
                if p is None:
                    continue
                if isinstance(p, (list, tuple)) and len(p) >= 2:
                    try:
                        lat = float(p[0])
                        lon = float(p[1])
                        norm.append([lat, lon])
                    except Exception:
                        continue
            if not norm:
                # fallback to start/end if available
                if isinstance(geom, (list, tuple)) and len(geom) >= 2:
                    try:
                        a0 = float(geom[0][0]); b0 = float(geom[0][1])
                        a1 = float(geom[-1][0]); b1 = float(geom[-1][1])
                        norm = [[a0,b0],[a1,b1]]
                    except Exception:
                        norm = []
        except Exception:
            norm = []

        if norm:
            try:
                folium.PolyLine(norm, color=colors.get(s["mode"], "black"), weight=5,
                                tooltip=f"{MODES[s['mode']]['label']} {s['distance_km']:.2f} km").add_to(m)
            except Exception:
                # Log and skip problematic polyline
                import logging
                logging.exception("Failed to add PolyLine for segment")
    st.markdown(f"**{title}**")
    # Try the streamlit_folium component first (preferred). If marshalling fails
    # (non-JSON-serialisable args), fall back to embedding the rendered HTML
    # to avoid streamlit.components.v1.MarshallComponentException.
    try:
        st_folium(m, height=560, use_container_width=True, returned_objects=[], key=key or f"map_{title.replace(' ','_')}")
    except Exception as exc:
        # Log the exception for debugging (visible in Streamlit logs)
        st.warning("Folium component marshalling failed; using HTML fallback. See logs for details.")
        import logging
        logging.exception("st_folium marshalling failed")
        try:
            map_html = m.get_root().render()
            components.html(map_html, height=560)
        except Exception:
            st.error("Failed to render map via HTML fallback.")

def totals_cards(title: str, totals: Dict):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"{title} – Distance (km)", f"{totals['distance_km']:.2f}")
    c2.metric(f"{title} – Time (h)", f"{totals['time_h']:.2f}")
    c3.metric(f"{title} – Emissions (kg CO₂)", f"{totals['co2_kg']:.2f}")
    c4.metric(f"{title} – Cost ($)", f"{totals['cost']:.2f}")

def comparison_cards(baseline: Dict, scenario: Dict):
    def delta(a,b): return (b-a, ( (b-a)/a*100 if a>0 else float('inf') ))
    d_co2, p_co2 = delta(baseline["co2_kg"], scenario["co2_kg"])
    d_cost, p_cost = delta(baseline["cost"], scenario["cost"])
    def sign(val): return "▼" if val < 0 else ("▲" if val > 0 else "→")
    c1, c2 = st.columns(2)
    c1.metric("CO₂ change", f"{scenario['co2_kg']:.2f} kg", f"{sign(d_co2)} {d_co2:+.2f} kg ({p_co2:+.1f}%)")
    c2.metric("Cost change", f"${scenario['cost']:.2f}", f"{sign(d_cost)} {d_cost:+.2f} ({p_cost:+.1f}%)")

# =============================
# SIDEBAR CONTROLS
# =============================
@st.cache_data(show_spinner=True)
def build_graph_and_list():
    graph = build_city_graph(CITIES, MICRO_HUBS)
    names = [c for c in CITY_LIST if c in graph]
    return graph, names

CITY_GRAPH, CITY_NAMES = build_graph_and_list()
if not CITY_NAMES:
    st.error("No cities available after geocoding. Please revise addresses.")
    st.stop()

st.sidebar.header("Controls")
engine = st.sidebar.selectbox("Routing engine (open data)", ["OSRM (open data)","Haversine only"], index=0)

city_name = st.sidebar.selectbox("City", CITY_NAMES, index=0)
city = CITY_GRAPH[city_name]

# Start & Destination
start_address = st.sidebar.text_input("Start address (within city; blank = central hub)", "")
allowed_modes_city = sorted(list(CITY_MODE_CAPS[city_name]["allowed"]))
st.sidebar.markdown("**Allowed modes (this city):** " + ", ".join(MODES[m]["label"] for m in allowed_modes_city))
destination_address = st.sidebar.text_input("Destination address (within city)", "")

# For Baseline
st.sidebar.subheader("Baseline (your current chain)")
st.sidebar.caption('Example: "truck" or "truck → small_van" (use mode keys: truck, elcv, small_van, cargo_bike, e_scooter_trailer, autonomous_robot, cargo_tram, cargo_bus, boat)')
baseline_chain_str = st.sidebar.text_input("Baseline chain", "truck")

use_hub = st.sidebar.checkbox("Route via micro-hub", value=False)
selected_micro_label = None
if use_hub:
    micro_options = ["— Auto (nearest) —"] + [h.name for h in city["micro_hubs"]]
    selected_micro_label = st.sidebar.selectbox("Micro-hub", micro_options, index=0, help="Pick a specific hub or leave Auto for nearest.")

st.sidebar.subheader("Optimizer")
weight_cost = st.sidebar.slider("Best Combined: weight on **Cost**", 0.0, 1.0, 0.5, 0.05, help="0 = prioritize CO₂, 1 = prioritize Cost")

run = st.sidebar.button("Compute")

# =============================
# MAIN FLOW
# =============================
def parse_chain(chain_str: str) -> List[str]:
    parts = [p.strip().lower().replace(" ", "_") for p in chain_str.replace("->","→").split("→")]
    return [p for p in parts if p]

def geocode_or_error(label, addr_value) -> Tuple[Optional[Tuple[float,float]], bool]:
    if not addr_value.strip():
        st.warning(f"Please enter **{label}**.")
        return None, False
    geo = geocode_address(addr_value.strip())
    if not geo:
        st.error(f"Could not geocode **{label}**: {addr_value}")
        return None, False
    return (geo[0], geo[1]), True

def nearest_micro(city_obj, dest):
    best, best_d = None, 1e18
    for h in city_obj["micro_hubs"]:
        d = haversine_km((h.lat, h.lon), dest)
        if d < best_d:
            best, best_d = h, d
    return best

def get_micro_by_name(city_obj, name: str) -> Optional[Node]:
    for h in city_obj["micro_hubs"]:
        if h.name == name:
            return h
    return None

def make_baseline(origin, dest, chain: List[str], via_hub: bool, hub_override: Optional[Node] = None):
    chain = [m for m in chain if m in CITY_MODE_CAPS[city_name]["allowed"] and m in MODES]
    if not chain:
        chain = ["truck"]

    segs: List[Dict] = []
    chosen_hub: Optional[Node] = None

    if via_hub:
        chosen_hub = hub_override or nearest_micro(city, dest)
        d1, g1 = route_with_engine(origin, (chosen_hub.lat, chosen_hub.lon), chain[0], MODES, engine)
        t1, e1, c1 = impact_for_leg(d1, chain[0])
        segs.append({"from":"Start","to":chosen_hub.name,"mode":chain[0],"distance_km":round(d1,3),"time_h":t1,"co2_kg":e1,"cost":c1,"geometry":g1})

        for idx, m in enumerate(chain[1:-1]):
            d_mid = 0.5
            t_mid, e_mid, c_mid = impact_for_leg(d_mid, m)
            segs.append({"from":f"{chosen_hub.name} – Xfer {idx+1}","to":f"{chosen_hub.name} – Xfer {idx+1} end","mode":m,
                         "distance_km":round(d_mid,3),"time_h":t_mid,"co2_kg":e_mid,"cost":c_mid,
                         "geometry":[[chosen_hub.lat, chosen_hub.lon],[chosen_hub.lat+0.001, chosen_hub.lon+0.001]]})

        last_mode = chain[-1] if len(chain)>1 else chain[0]
        d2, g2 = route_with_engine((chosen_hub.lat, chosen_hub.lon), dest, last_mode, MODES, engine)
        t2, e2, c2 = impact_for_leg(d2, last_mode)
        segs.append({"from":chosen_hub.name,"to":"Destination","mode":last_mode,"distance_km":round(d2,3),"time_h":t2,"co2_kg":e2,"cost":c2,"geometry":g2})
    else:
        m0 = chain[0]  
        d, g = route_with_engine(origin, dest, m0, MODES, engine)
        t, e, c = impact_for_leg(d, m0)
        segs.append({"from":"Start","to":"Destination","mode":m0,"distance_km":round(d,3),"time_h":t,"co2_kg":e,"cost":c,"geometry":g})

    totals = {"distance_km":sum(s["distance_km"] for s in segs),
              "time_h":sum(s["time_h"] for s in segs),
              "co2_kg":sum(s["co2_kg"] for s in segs),
              "cost":sum(s["cost"] for s in segs)}
    return segs, totals, chosen_hub

if run:
    origin = (city["central_hub"].lat, city["central_hub"].lon)
    if start_address.strip():
        start_geo, ok1 = geocode_or_error("Start address", start_address)
        if not ok1:
            st.stop()
        origin = start_geo

    dest_geo, ok2 = geocode_or_error("Destination address", destination_address)
    if not ok2:
        st.stop()

    hub_override = None
    if use_hub:
        if selected_micro_label and selected_micro_label != "— Auto (nearest) —":
            hub_override = get_micro_by_name(city, selected_micro_label)

    baseline_chain = [m for m in parse_chain(baseline_chain_str) if m in MODES]
    base_segments, base_totals, base_hub_used = make_baseline(origin, dest_geo, baseline_chain, use_hub, hub_override)

    cA, cB = st.columns(2)
    with cA:
        totals_cards("Baseline", base_totals)
    with cB:
        st.metric("Allowed modes (city)", len(allowed_modes_city))

    render_map(base_segments, origin, dest_geo, city,
               hub=base_hub_used, title="Baseline Route", key="map_baseline",
               show_hub_marker=bool(use_hub and base_hub_used))

    results = search_best_routes(city_name, city, origin, dest_geo, engine,
                                 via_hub=use_hub, fixed_hub=(base_hub_used if use_hub else None))
    if not results["all"]:
        st.error("No feasible candidates found (check routing).")
        st.stop()

    best_co2  = results["min_co2"]
    best_cost = results["min_cost"]
    best_combo = pick_best_combo(results, weight_cost)

    tabs = st.tabs(["Lowest Emissions", "Lowest Cost", "Best Combined"])
    packs = [("Lowest Emissions", best_co2), ("Lowest Cost", best_cost), ("Best Combined", best_combo)]
    chosen_for_esg = None

    for tab, (title, pack) in zip(tabs, packs):
        with tab:
            hub = pack["hub"]; segs = pack["segments"]; totals = pack["totals"]; modes = pack["modes"]
            if use_hub:
                mode_names = f"{MODES[modes[0]]['label']} → {MODES[modes[1]]['label']}"
                st.markdown(f"**Modes**: {mode_names}  •  **Hub**: {hub.name}")
            else:
                mode_names = f"{MODES[modes[0]]['label']}"
                st.markdown(f"**Mode**: {mode_names}  •  **Direct (no hub)**")

            totals_cards(title, totals)
            st.dataframe(pd.DataFrame([{k:v for k,v in s.items() if k!='geometry'} for s in segs]).round(3),
                         use_container_width=True, key=f"df_{title.replace(' ','_')}")
            render_map(segs, origin, dest_geo, city,
                       hub=(hub if use_hub else None), title=title, key=f"map_{title.replace(' ','_')}",
                       show_hub_marker=use_hub)
            if title == "Best Combined":
                chosen_for_esg = (segs, totals)

    st.subheader("Baseline vs Best Combined")
    comparison_cards(base_totals, chosen_for_esg[1])
    render_esg_dashboard((base_segments, base_totals), chosen_for_esg, "Best Combined")
    policy_box(city_name)

else:
    st.info("Pick a **city**, enter a **start** (optional) and **destination** address, choose your **baseline chain**. "
            "Leave 'Route via micro-hub' **off** for direct routing; turn it **on** to use a selected or nearest micro-hub. "
            "Then click **Compute**.")