import requests
import time
import sys
import os
import json
from math import radians, cos, sin, asin, sqrt, atan2, degrees
from datetime import datetime
from itertools import cycle
from timezonefinder import TimezoneFinder
import pytz
from colorama import Fore, Style, init
import getpass


init(autoreset=True)



#Set defaults Acquire OpenSky credentials, radius desired

USERNAME = input("Enter OpenSky Username: ").strip()
PASSWORD = getpass.getpass("Enter OpenSky Password: ").strip()
RADIUS_MILES = float(input("Enter tracking radius in miles: ").strip())
REFRESH_SECONDS = 10


# Get Address data and convert into long/lat

def geocode_address(address):
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": address, "format": "json"}
        headers = {"User-Agent": "FlightTracker/1.0"}
        response = requests.get(url, params=params, headers=headers, timeout=10)
        data = response.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except:
        pass
    return None, None

address = input("Enter your address or city (e.g., '948 Broadway, Saugus MA'): ").strip()
MY_LAT, MY_LON = geocode_address(address)
if MY_LAT is None or MY_LON is None:
    print("[WARN] Could not geocode address. Using default location.")
    MY_LAT, MY_LON = 42.4678732, -71.0249055




# Timezone conversion
tf = TimezoneFinder()
timezone_name = tf.timezone_at(lat=MY_LAT, lng=MY_LON)
local_tz = pytz.timezone(timezone_name if timezone_name else "UTC")

#Aircraft type json reference
with open("aircraft_types.json", "r") as f:
    AIRCRAFT_TYPES = json.load(f)
    AIRCRAFT_TYPES.update({
        "EJA": "Embraer Phenom 300",
        "FDX": "McDonnell Douglas MD-11F",
        "UPS": "Boeing 757-200F",
        "ABX": "Boeing 767-200F",
        "GTI": "Boeing 747-400F",
        "KAP": "Cessna 172",
        "LXJ": "Bombardier Challenger 300",
        "N": "Private Aircraft"
    })

with open("airlines_full.json", "r") as f:
    AIRLINES = json.load(f)


aircraft_metadata_cache = {}

def get_aircraft_type(callsign, icao24):
    if icao24 in aircraft_metadata_cache:
        return aircraft_metadata_cache[icao24]

    model = None
    source = ""
    try:
        url = f"https://opensky-network.org/api/metadata/aircraft/icao24/{icao24}"
        response = requests.get(url, auth=(USERNAME, PASSWORD), timeout=10)
        response.raise_for_status()
        data = response.json()
        model = data.get('model')
        if model and model.strip():
            source = "OpenSky"
        else:
            raise ValueError("Empty model from OpenSky")
    except Exception as e:
        prefix = callsign[:3].upper()
        model = AIRCRAFT_TYPES.get(prefix, 'Unknown Type')
        source = "Local Dataset"
        with open("missing_aircraft.log", "a") as log:
            log.write(f"{icao24}\n")

    model_label = f"{model} ({source})"
    aircraft_metadata_cache[icao24] = model_label
    return model_label

def get_airline_name(callsign):
    prefix = callsign[:3].upper()
    return AIRLINES.get(prefix, "Unknown Carrier")

#Math. Thank you chatgpt for saving me a lot of time.

def haversine(lat1, lon1, lat2, lon2):
    R = 3956
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))

def get_direction(lat1, lon1, lat2, lon2):
    dlon = radians(lon2 - lon1)
    lat1 = radians(lat1)
    lat2 = radians(lat2)
    x = sin(dlon) * cos(lat2)
    y = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dlon)
    initial_bearing = atan2(x, y)
    bearing = (degrees(initial_bearing) + 360) % 360
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    idx = round(bearing / 45) % 8
    return directions[idx]

def get_altitude_color(alt):
    if alt == "N/A": return Fore.YELLOW
    if alt < 3000: return Fore.RED
    if alt < 10000: return Fore.GREEN
    return Fore.BLUE

def is_on_ground(altitude, speed):
    return (altitude == "N/A" or (isinstance(altitude, int) and altitude < 100)) and \
           (speed == "N/A" or (isinstance(speed, int) and speed < 40))

def get_flight_status_icon(alt):
    if alt == "N/A": return "🅿️"
    if isinstance(alt, int):
        if alt < 3000: return "🛫"
        if alt < 10000: return "🛬"
        return "✈️"
    return "✈️"

# Create a class flight for persistence in data

class Flight:
    def __init__(self, state):
        self.icao24 = state[0]
        self.callsign = state[1].strip() if state[1] else "N/A"
        self.origin_country = state[2]
        self.update(state)

    def update(self, state):
        self.latitude = state[6]
        self.longitude = state[5]
        self.altitude_ft = round(state[7] * 3.28084) if state[7] else "N/A"
        self.velocity_mph = round(state[9] * 2.23694) if state[9] else "N/A"
        self.heading = round(state[10]) if state[10] else "N/A"
        self.distance_miles = round(haversine(MY_LAT, MY_LON, self.latitude, self.longitude), 2)
        self.direction = get_direction(MY_LAT, MY_LON, self.latitude, self.longitude)
        self.aircraft_type = get_aircraft_type(self.callsign, self.icao24)
        self.airline = get_airline_name(self.callsign)
        self.status_icon = get_flight_status_icon(self.altitude_ft)

    def display(self):
        color = get_altitude_color(self.altitude_ft)
        status = ""
        if is_on_ground(self.altitude_ft, self.velocity_mph):
            status = f"\n  {Fore.YELLOW}🛬 Status: Probably on the runway{Style.RESET_ALL}"

        return f"""
{self.status_icon} {Fore.CYAN}{self.callsign}{Style.RESET_ALL} | {self.origin_country} | {self.distance_miles} mi
  Registration: {self.callsign}
  Airline: {self.airline}
  Aircraft: {self.aircraft_type}
  Direction: {self.direction}
  ICAO24: {self.icao24}
  Position: ({self.latitude:.4f}, {self.longitude:.4f})
  Altitude: {color}{self.altitude_ft} ft{Style.RESET_ALL} | Speed: {Fore.GREEN}{self.velocity_mph} mph{Style.RESET_ALL} | Heading: {Fore.YELLOW}{self.heading}°{Style.RESET_ALL}{status}
""".strip()


# Set the tracker loop

def get_bounds(lat, lon, radius_miles):
    lat_delta = radius_miles / 69
    lon_delta = radius_miles / (69 * cos(radians(lat)))
    return lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta

def fetch_flights(lamin, lamax, lomin, lomax):
    url = f"https://opensky-network.org/api/states/all?lamin={lamin}&lamax={lamax}&lomin={lomin}&lomax={lomax}"
    try:
        response = requests.get(url, auth=(USERNAME, PASSWORD), timeout=10)
        response.raise_for_status()
        return response.json().get("states", [])
    except:
        return []

def is_duplicate(flight, seen):
    for other in seen:
        if flight.callsign == other.callsign and \
           abs(flight.latitude - other.latitude) < 0.01 and \
           abs(flight.longitude - other.longitude) < 0.01:
            return True
    return False

def main_loop():
    seen_planes = set()
    flights_in_bounds = {}
    previous_cycle = set()
    spinner = cycle("|/-\\")

    while True:
        lamin, lamax, lomin, lomax = get_bounds(MY_LAT, MY_LON, RADIUS_MILES)
        now_local = datetime.now(local_tz).strftime('%Y-%m-%d %H:%M:%S %Z')
        states = fetch_flights(lamin, lamax, lomin, lomax)

        active = {}
        new_alerts = []
        departures = []
        current_cycle = set()
        display_flights = []

        for state in states:
            try:
                lat, lon = state[6], state[5]
                if lat is None or lon is None:
                    continue
                distance = haversine(MY_LAT, MY_LON, lat, lon)
                if distance > RADIUS_MILES:
                    continue
                icao24 = state[0]
                current_cycle.add(icao24)
                if icao24 not in seen_planes:
                    new_alerts.append((state[1] or "N/A", round(distance, 1)))
                    seen_planes.add(icao24)

                if icao24 in flights_in_bounds:
                    flights_in_bounds[icao24].update(state)
                else:
                    flights_in_bounds[icao24] = Flight(state)
                active[icao24] = flights_in_bounds[icao24]
            except:
                continue

        departures = previous_cycle - current_cycle
        previous_cycle = current_cycle
        flights_in_bounds = active

        header = (f"🛬 {now_local} - Tracking {len(active)} active plane(s) within {RADIUS_MILES} miles."
                  if active else
                  f"🛰️ {now_local} - No planes in the designated bounding box. Scanning...")

        for _ in range(REFRESH_SECONDS * 5):
            sys.stdout.write(f"\r{next(spinner)} {header.ljust(80)}")
            sys.stdout.flush()
            time.sleep(0.2)

        os.system('cls' if os.name == 'nt' else 'clear')
        print(header)

        if new_alerts:
            for callsign, dist in new_alerts:
                print(f"{Fore.GREEN}🔔 New Arrival: {callsign.strip()} entered airspace ({dist} mi){Style.RESET_ALL}")

        if departures:
            for icao in departures:
                print(f"{Fore.CYAN}👋 Departure: Aircraft {icao} has left the area{Style.RESET_ALL}")

        if active:
            print("\n🛫 Active Planes in Bounds:\n")
            for flight in sorted(active.values(), key=lambda f: (is_on_ground(f.altitude_ft, f.velocity_mph), f.distance_miles)):
                if not is_duplicate(flight, display_flights):
                    print(flight.display())
                    print(Fore.MAGENTA + "-" * 60 + Style.RESET_ALL)
                    display_flights.append(flight)

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        print("\nExiting.")