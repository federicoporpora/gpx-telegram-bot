import xml.etree.ElementTree as ET
from datetime import datetime
from math import radians, cos, sin, asin, sqrt
import os
import sys
from typing import List, Optional, Tuple, Dict

# Constants for Namespaces
NS_GPX = {
    "gpx": "http://www.topografix.com/GPX/1/1",
    "gpxtpx": "http://www.garmin.com/xmlschemas/TrackPointExtension/v1"
}

# Register namespaces to avoid "ns0" prefixes in output
ET.register_namespace("", NS_GPX["gpx"])
ET.register_namespace("gpxtpx", NS_GPX["gpxtpx"])

def parse_time(t: str) -> datetime:
    """
    Parses a timestamp string into a datetime object.
    Handles 'Z' notation and fractional seconds.
    """
    t = t.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(t)
    except ValueError:
        # Handle cases with fractional seconds that might break fromisoformat
        if "." in t:
            t = t.split(".")[0] + "+00:00"
        return datetime.fromisoformat(t)

def format_time_tcx(dt: datetime) -> str:
    """Formats datetime object to TCX compatible string."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

def haversine(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees).
    Returns distance in meters.
    """
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    r = 6371000  # Radius of Earth in meters
    return c * r

def load_hr_data(path: str) -> List[Tuple[datetime, int]]:
    """
    Loads Heart Rate data from a GPX file.
    Returns a list of tuples: (datetime, heart_rate).
    """
    if not os.path.exists(path):
        return []
    
    tree = ET.parse(path)
    root = tree.getroot()
    pts = []
    
    for trkpt in root.findall(".//gpx:trkpt", NS_GPX):
        time_el = trkpt.find("gpx:time", NS_GPX)
        if time_el is None: 
            continue 
            
        t = parse_time(time_el.text)
        hr_el = trkpt.find(".//gpxtpx:hr", NS_GPX)
        
        # Extract HR if present
        hr = int(hr_el.text) if hr_el is not None else None
        if hr: 
            pts.append((t, hr))
            
    return pts

def get_closest_hr(target_time: datetime, hr_data: List[Tuple[datetime, int]]) -> Optional[int]:
    """
    Finds the heart rate value with the timestamp closest to the target_time.
    Returns None if no data point is within 5 seconds.
    """
    if not hr_data: 
        return None
        
    best_hr = None
    min_diff = 5.0 # Max tolerance in seconds
    
    for t, hr in hr_data:
        diff = abs((target_time - t).total_seconds())
        if diff < min_diff:
            min_diff = diff
            best_hr = hr
        # Optimization: if match is very close, stop searching
        if diff < 0.5: 
            break
            
    return best_hr

def create_tcx(points: List[Dict], start_time: datetime, total_duration_sec: float, total_dist_meters: float, out_file: str):
    """Generates the final TCX file with corrected distance and merged HR."""
    
    header = f"""<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity Sport="Running">
      <Id>{format_time_tcx(start_time)}</Id>
      <Lap StartTime="{format_time_tcx(start_time)}">
        <TotalTimeSeconds>{total_duration_sec}</TotalTimeSeconds>
        <DistanceMeters>{total_dist_meters}</DistanceMeters>
        <Intensity>Active</Intensity>
        <TriggerMethod>Manual</TriggerMethod>
        <Track>
"""
    footer = """        </Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>
"""
    with open(out_file, "w") as f:
        f.write(header)
        for p in points:
            t_str = format_time_tcx(p['time'])
            lat = p['lat']
            lon = p['lon']
            ele = p['ele']
            dist = p['dist_calculated']
            hr = p['hr']
            cad = p.get('cad')
            
            f.write(f"          <Trackpoint>\n")
            f.write(f"            <Time>{t_str}</Time>\n")
            f.write(f"            <Position>\n")
            f.write(f"              <LatitudeDegrees>{lat}</LatitudeDegrees>\n")
            f.write(f"              <LongitudeDegrees>{lon}</LongitudeDegrees>\n")
            f.write(f"            </Position>\n")
            f.write(f"            <AltitudeMeters>{ele}</AltitudeMeters>\n")
            f.write(f"            <DistanceMeters>{dist:.2f}</DistanceMeters>\n")
            if hr:
                f.write(f"            <HeartRateBpm>\n")
                f.write(f"              <Value>{hr}</Value>\n")
                f.write(f"            </HeartRateBpm>\n")
            if cad is not None:
                f.write(f"            <Cadence>{cad}</Cadence>\n")
            f.write(f"          </Trackpoint>\n")
        f.write(footer)

def main():
    if len(sys.argv) < 2:
        print("ERROR: Target distance is missing!")
        print("Usage: python gpx_hr_merger.py <distance_km>")
        return

    try:
        dist_input = sys.argv[1].replace(",", ".")
        target_km = float(dist_input)
    except ValueError:
        print(f"ERROR: '{sys.argv[1]}' is not a valid number.")
        return

    # Configuration files
    file_gps = "GPS.gpx"
    file_hr = "HR.gpx"
    file_out = "output_fixed.tcx"

    print(f"--- Target Distance: {target_km} km ---")

    if not os.path.exists(file_gps) or not os.path.exists(file_hr):
        print(f"ERROR: Ensure that '{file_gps}' and '{file_hr}' are in the current directory.")
        return

    # 1. Load Heart Rate Data
    hr_data = load_hr_data(file_hr)
    print(f"Loaded {len(hr_data)} heart rate points.")

    # 2. Parse GPS Data
    tree = ET.parse(file_gps)
    root = tree.getroot()
    track_points = []
    
    prev_lat = None
    prev_lon = None
    raw_accumulated_dist = 0.0
    found_points = 0
    last_cad = None

    for trkpt in root.findall(".//gpx:trkpt", NS_GPX):
        lat = float(trkpt.get("lat"))
        lon = float(trkpt.get("lon"))
        
        ele_el = trkpt.find("gpx:ele", NS_GPX)
        ele = float(ele_el.text) if ele_el is not None else 0.0
        
        time_el = trkpt.find("gpx:time", NS_GPX)
        if time_el is None: 
            continue
            
        found_points += 1
        t = parse_time(time_el.text)
        
        cad_el = trkpt.find(".//gpxtpx:cad", NS_GPX)
        if cad_el is not None:
            # TCX wants cadence in RPM, while GPX saves in SPM, so I divide it by two
            last_cad = int(cad_el.text) // 2
        
        step_dist = 0.0
        if prev_lat is not None:
            step_dist = haversine(prev_lon, prev_lat, lon, lat)
        
        raw_accumulated_dist += step_dist
        
        # Sync HR data based on timestamp
        track_points.append({
            "lat": lat, "lon": lon, "ele": ele, "time": t,
            "raw_dist": raw_accumulated_dist,
            "hr": get_closest_hr(t, hr_data),
            "cad": last_cad
        })
        prev_lat, prev_lon = lat, lon

    if not track_points:
        print("ERROR: No track points found. Please check GPS.gpx validity.")
        return

    # 3. Calculate Ratio and Rescale
    total_gps_dist = track_points[-1]["raw_dist"]
    print(f"Original GPS Distance: {total_gps_dist/1000:.3f} km")
    
    target_meters = target_km * 1000
    ratio = target_meters / total_gps_dist if total_gps_dist > 0 else 1.0
    print(f"Correction Factor: {ratio:.4f}")

    for p in track_points:
        p["dist_calculated"] = p["raw_dist"] * ratio

    # 4. Generate Output
    start_t = track_points[0]["time"]
    end_t = track_points[-1]["time"]
    duration = (end_t - start_t).total_seconds()
    
    create_tcx(track_points, start_t, duration, target_meters, file_out)
    print(f"Success! Created file: {file_out}")

if __name__ == "__main__":
    main()
