import requests
from bs4 import BeautifulSoup
import re
import time

BASE_URL = "https://wiki.coigame.com"

# --- Your building list ---
buildings = [
    "Air Separator","Alloy Mixer","Aluminum Cell","Anaerobic Digester",
    "Arc Furnace","Arc Furnace II","Assembly I","Assembly II","Assembly III",
    "Assembly IV","Assembly V","Baking Unit","Basic Distiller","Blast Furnace",
    "Blast Furnace II","Boiler","Boiler (Electric)","Boiler (Gas)","Burner (Solid)",
    "Chemical Plant","Chemical Plant II","Chicken Farm","Coal Maker","Compactor",
    "Concrete Mixer","Concrete Mixer II","Concrete Mixer III","Cooled Caster",
    "Cooled Caster II","Cooling Tower","Cooling Tower (Large)",
    "Copper Electrolysis","Cracking Unit","Crusher","Crusher (Large)",
    "Crystallizer","Data Center","Diamond Reactor","Diesel Generator",
    "Diesel Generator II","Distillation (Stage I)","Distillation (Stage II)",
    "Distillation (Stage III)","Electrolyzer","Electrolyzer II",
    "Enrichment Plant","Evaporation Pond","Evaporation Pond (Heated)",
    "Exhaust Scrubber","Farm","Fast Breeder Reactor","Fermentation Tank",
    "Flare","Food Processor","Gas Injection Pump","Glass Maker",
    "Glass Maker II","Gold Furnace","Greenhouse","Greenhouse II",
    "Groundwater Pump","High-Pressure Turbine","High-Pressure Turbine II",
    "Hydrogen Reformer","Incineration Plant","Irrigated Farm","Kiln",
    "Lens Polisher","Liquid Dump","Low-Pressure Turbine",
    "Low-Pressure Turbine II","Maintenance Depot",
    "Maintenance Depot (Basic)","Maintenance II Depot",
    "Maintenance III Depot","Metal Caster","Metal Caster II",
    "Microchip Machine","Microchip Machine II","Mill","Mixer","Mixer II",
    "Nuclear Reactor","Nuclear Reactor II","Nuclear Reprocessing Plant",
    "Oil Pump","Oxygen Furnace","Oxygen Furnace II","Polymerization Plant",
    "Power Generator","Power Generator (Large)","Rainwater Harvester",
    "Research Lab I","Research Lab II","Research Lab III","Research Lab IV",
    "Rotary Kiln","Rotary Kiln (Gas)","Rubber Maker","Seawater Pump",
    "Seawater Pump (Tall)","Settling Tank","Shredder","Silicon Reactor",
    "Smoke Stack","Smoke Stack (Large)","Sour Water Stripper",
    "Super-Pressure Turbine","Thermal Desalinator","Waste Sorting Plant",
    "Wastewater Treatment","Water Chiller"
]

# --- Convert building name to wiki URL ---
def name_to_url(name):
    # Replace spaces with underscores
    url_name = name.replace(" ", "_")

    # Remove parentheses formatting for wiki
    url_name = re.sub(r"\((.*?)\)", r"\1", url_name)

    return f"{BASE_URL}/{url_name}"

# --- Extract footprint ---
def get_footprint(url):
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        # Find all rows
        rows = soup.select("table.table tr")

        for row in rows:
            cols = row.find_all("td")
            if len(cols) != 2:
                continue

            key = cols[0].get_text(strip=True)
            val = cols[1].get_text(strip=True)

            if key == "Footprint":
                match = re.search(r"(\d+)\s*x\s*(\d+)", val)
                if match:
                    w, h = int(match.group(1)), int(match.group(2))
                    return w * h

        return None

    except Exception as e:
        print(f"Error for {url}: {e}")
        return None


# --- Main loop ---
results = {}

for b in buildings:
    url = name_to_url(b)
    area = get_footprint(url)
    results[b] = area

    print(f"{b}: {area}")
    time.sleep(0.5)  # be polite to the wiki

# --- Final dictionary ---
print("\nFinal dictionary:")
print(results)