import gpxpy
import gpxpy.gpx
from staticmap import StaticMap, Line
import requests
from datetime import datetime, timedelta
import math
import os

def generate_map(gpx_path, output_image_path, style='dark', color='#FC4C02'):
    try:
        with open(gpx_path, 'r') as f:
            gpx = gpxpy.parse(f)
            
        coordinates = []
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    coordinates.append((point.longitude, point.latitude))
                    
        if not coordinates:
            return False
            
        if style == 'transparent':
            from PIL import Image, ImageDraw
            import math
            def mercator(lon, lat):
                r_major = 6378137.000
                x = r_major * math.radians(lon)
                scale = x/lon if lon != 0 else r_major * (math.pi/180.0)
                y = 180.0/math.pi * math.log(math.tan(math.pi/4.0 + lat * (math.pi/180.0)/2.0)) * scale
                return x, y
            
            pts = [mercator(lon, lat) for lon, lat in coordinates]
            min_x = min(p[0] for p in pts)
            max_x = max(p[0] for p in pts)
            min_y = min(p[1] for p in pts)
            max_y = max(p[1] for p in pts)
            
            w, h = 800, 800
            pad = 50
            diff_x = max_x - min_x
            diff_y = max_y - min_y
            if diff_x == 0 or diff_y == 0: return False
            scale = min((w - 2*pad) / diff_x, (h - 2*pad) / diff_y)
            
            img = Image.new("RGBA", (w, h), (0,0,0,0))
            draw = ImageDraw.Draw(img)
            pixels = []
            for x, y in pts:
                px = int(pad + (x - min_x) * scale)
                py = int(h - pad - (y - min_y) * scale)
                pixels.append((px, py))
            draw.line(pixels, fill=color, width=6, joint="curve")
            img.save(output_image_path)
            return True

        templates = {
            'dark': 'https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
            'light': 'https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
            'topo': 'https://a.tile.opentopomap.org/{z}/{x}/{y}.png',
            'satellite': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
        }
        url = templates.get(style, templates['dark'])
        m = StaticMap(800, 800, url_template=url)
        line = Line(coordinates, color, 4)
        m.add_line(line)
        
        image = m.render()
        image.save(output_image_path)
        return True
    except Exception as e:
        print(f"Error generating map: {e}")
        return False

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000 # meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def crop_gpx(gpx_path, start_km, end_km, output_path):
    try:
        with open(gpx_path, 'r') as f:
            gpx = gpxpy.parse(f)
            
        total_dist = 0
        prev_pt = None
        
        # First pass to calculate total distance
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    if prev_pt:
                        total_dist += haversine(prev_pt.latitude, prev_pt.longitude, point.latitude, point.longitude)
                    prev_pt = point
                    
        total_km = total_dist / 1000
        if start_km + end_km >= total_km:
            return False # Invalid crop
            
        target_end_km = total_km - end_km
        
        current_dist = 0
        prev_pt = None
        
        for track in gpx.tracks:
            for segment in track.segments:
                new_points = []
                for point in segment.points:
                    if prev_pt:
                        current_dist += haversine(prev_pt.latitude, prev_pt.longitude, point.latitude, point.longitude) / 1000
                    prev_pt = point
                    
                    if current_dist >= start_km and current_dist <= target_end_km:
                        new_points.append(point)
                segment.points = new_points
                
        with open(output_path, 'w') as f:
            f.write(gpx.to_xml())
        return True
    except Exception as e:
        print(f"Error cropping gpx: {e}")
        return False

def fix_time(gpx_path, target_minutes, output_path):
    try:
        with open(gpx_path, 'r') as f:
            gpx = gpxpy.parse(f)
            
        start_time = None
        end_time = None
        points = []
        
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    if point.time:
                        if not start_time:
                            start_time = point.time
                        end_time = point.time
                        points.append(point)
                        
        if not points or not start_time or not end_time:
            return False
            
        actual_duration = (end_time - start_time).total_seconds()
        target_duration = target_minutes * 60
        
        if actual_duration == 0: return False
        
        ratio = target_duration / actual_duration
        
        for point in points:
            delta = (point.time - start_time).total_seconds()
            point.time = start_time + timedelta(seconds=delta * ratio)
            
        with open(output_path, 'w') as f:
            f.write(gpx.to_xml())
        return True
    except Exception as e:
        print(f"Error fixing time: {e}")
        return False

def merge_sequential(gpx_paths, output_path):
    try:
        merged_gpx = gpxpy.gpx.GPX()
        merged_track = gpxpy.gpx.GPXTrack()
        merged_gpx.tracks.append(merged_track)
        merged_segment = gpxpy.gpx.GPXTrackSegment()
        merged_track.segments.append(merged_segment)
        
        all_points = []
        for path in gpx_paths:
            with open(path, 'r') as f:
                gpx = gpxpy.parse(f)
                for track in gpx.tracks:
                    for segment in track.segments:
                        for point in segment.points:
                            all_points.append(point)
                            
        # sort by time
        all_points.sort(key=lambda p: p.time if p.time else datetime.min.replace(tzinfo=p.time.tzinfo if p.time else None))
        merged_segment.points = all_points
        
        with open(output_path, 'w') as f:
            f.write(merged_gpx.to_xml())
        return True
    except Exception as e:
        print(f"Error merging sequentially: {e}")
        return False

def fix_elevation(gpx_path, output_path):
    try:
        with open(gpx_path, 'r') as f:
            gpx = gpxpy.parse(f)
            
        points = []
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    points.append(point)
                    
        if not points: return False
        
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i:i+batch_size]
            lats = ",".join(str(p.latitude) for p in batch)
            lons = ",".join(str(p.longitude) for p in batch)
            
            url = f"https://api.open-meteo.com/v1/elevation?latitude={lats}&longitude={lons}"
            res = requests.get(url)
            if res.status_code == 200:
                data = res.json()
                elevations = data.get('elevation', [])
                for p, elev in zip(batch, elevations):
                    if elev is not None:
                        p.elevation = elev
                        
        with open(output_path, 'w') as f:
            f.write(gpx.to_xml())
        return True
    except Exception as e:
        print(f"Error fixing elevation: {e}")
        return False
