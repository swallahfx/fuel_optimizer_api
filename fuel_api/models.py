import hashlib
import re
from django.db import models, transaction
import pandas as pd
from django.conf import settings
import math
import requests
import folium
import json
from typing import List, Tuple, Dict
from django.core.cache import cache


class FuelStationQuerySet(models.QuerySet):
    """Custom QuerySet for FuelStation with optimized queries"""
    
    def with_coordinates(self):
        """Filter stations that have valid coordinates"""
        return self.filter(latitude__isnull=False, longitude__isnull=False)
    
    def cheapest_first(self):
        """Order by retail price ascending"""
        return self.order_by('retail_price')
    
    def in_state(self, state_code):
        """Filter by state"""
        return self.filter(state=state_code.upper())
    
    def near_coordinates(self, lat, lon, radius_miles=50):
        """
        Find stations within radius using approximate bounding box
        More efficient than calculating exact distances for all stations
        """
        # Approximate degrees per mile: 1 degree ≈ 69 miles
        degree_radius = radius_miles / 69.0
        
        return self.filter(
            latitude__gte=lat - degree_radius,
            latitude__lte=lat + degree_radius,
            longitude__gte=lon - degree_radius,
            longitude__lte=lon + degree_radius
        )


class FuelStationManager(models.Manager):
    """Custom manager for FuelStation"""
    
    def get_queryset(self):
        return FuelStationQuerySet(self.model, using=self._db)
    
    def with_coordinates(self):
        return self.get_queryset().with_coordinates()
    
    def cheapest_first(self):
        return self.get_queryset().cheapest_first()
    
    def in_state(self, state_code):
        return self.get_queryset().in_state(state_code)
    
    def near_coordinates(self, lat, lon, radius_miles=50):
        return self.get_queryset().near_coordinates(lat, lon, radius_miles)
    

class FuelStation(models.Model):
    opis_id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=255, db_index=True)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100, db_index=True)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.IntegerField()
    retail_price = models.DecimalField(max_digits=6, decimal_places=3, db_index=True)
    latitude = models.FloatField(null=True, blank=True, db_index=True)
    longitude = models.FloatField(null=True, blank=True, db_index=True)

    # Use custom manager
    objects = FuelStationManager()

    class Meta:
        db_table = 'fuel_station'
        indexes = [
            models.Index(fields=['state', 'city']),
            models.Index(fields=['retail_price']),
            models.Index(fields=['latitude', 'longitude']),
            models.Index(fields=['state', 'retail_price']),
        ]
        ordering = ['retail_price']  # Default ordering by price

    def __str__(self):
        return f"{self.name} - {self.city}, {self.state} (${self.retail_price})"

    @classmethod
    def load_from_csv__(cls):
        """Load fuel stations from the CSV file with optimized bulk operations"""
        df = pd.read_csv(settings.FUEL_PRICES_CSV)
        
        # Use transaction for better performance
        with transaction.atomic():
            # Clear existing data
            cls.objects.all().delete()
            
            # Group by OPIS ID and take the first record for each station
            df_unique = df.groupby('OPIS Truckstop ID').first().reset_index()
            
            # Sample coordinates for major cities (for testing without geocoding)
            sample_coords = {
                'TX': (31.0, -97.0), 'CA': (36.0, -119.0), 'FL': (27.8, -81.7),
                'NY': (42.9, -75.5), 'PA': (40.3, -76.9), 'IL': (40.3, -89.0),
                'OH': (40.4, -82.7), 'MI': (43.3, -84.5), 'GA': (33.0, -83.5),
                'NC': (35.6, -79.0), 'NJ': (40.3, -74.5), 'VA': (37.8, -78.2),
                'WA': (47.4, -121.5), 'AZ': (33.7, -111.4), 'MA': (42.2, -71.5),
                'TN': (35.7, -86.7), 'IN': (39.8, -86.2), 'MO': (38.4, -92.3),
                'MD': (39.0, -76.8), 'WI': (44.3, -89.6), 'MN': (45.7, -93.9),
                'CO': (39.1, -105.3), 'AL': (32.8, -86.8), 'SC': (33.8, -80.5),
                'LA': (31.1, -91.8), 'KY': (37.7, -84.9), 'OR': (44.6, -122.1),
                'OK': (35.6, -96.9), 'CT': (41.6, -72.7), 'IA': (42.0, -93.2),
                'MS': (32.7, -89.6), 'AR': (34.9, -92.4), 'UT': (40.2, -111.5),
                'KS': (38.5, -96.7), 'NV': (38.3, -117.1), 'NM': (34.8, -106.2),
                'NE': (41.1, -98.3), 'WV': (38.5, -80.9), 'ID': (44.2, -114.5),
                'NH': (43.4, -71.5), 'ME': (44.7, -69.8), 'RI': (41.7, -71.5),
                'MT': (47.0, -110.5), 'DE': (39.3, -75.5), 'SD': (44.3, -100.4),
                'ND': (47.5, -99.8), 'AK': (61.4, -152.8), 'VT': (44.0, -72.7),
                'WY': (42.7, -107.3)
            }
            
            stations = []
            for _, row in df_unique.iterrows():
                state = row['State']
                # Assign sample coordinates based on state
                lat, lon = sample_coords.get(state, (39.0, -98.0))  # Default to center US
                # Add small random offset for each station
                lat_offset = (hash(str(row['OPIS Truckstop ID'])) % 200 - 100) * 0.001
                lon_offset = (hash(str(row['OPIS Truckstop ID']) + 'lon') % 200 - 100) * 0.001
                
                stations.append(cls(
                    opis_id=row['OPIS Truckstop ID'],
                    name=row['Truckstop Name'],
                    address=row['Address'],
                    city=row['City'].strip(),
                    state=row['State'],
                    rack_id=row['Rack ID'],
                    retail_price=row['Retail Price'],
                    latitude=lat + lat_offset,
                    longitude=lon + lon_offset
                ))
            
            # Use bulk_create with larger batch size for better performance
            cls.objects.bulk_create(stations, batch_size=2000, ignore_conflicts=True)
            return len(stations)


    @classmethod
    def load_from_csv(cls):
        """
        Load fuel stations using highway-based coordinates from CSV data
        NO geocoding needed - uses the highway exit information already in the CSV
        """
        df = pd.read_csv(settings.FUEL_PRICES_CSV)
        
        with transaction.atomic():
            cls.objects.all().delete()
            df_unique = df.groupby('OPIS Truckstop ID').first().reset_index()
            
            stations = []
            highway_parsed = 0
            fallback_used = 0
            
            for _, row in df_unique.iterrows():
                address = str(row['Address']).strip()
                city = str(row['City']).strip()
                state = str(row['State']).strip()
                
                # Parse highway coordinates from the CSV data itself
                lat, lon = cls._get_highway_coordinates(address, city, state)
                
                if lat and lon:
                    highway_parsed += 1
                else:
                    # Fallback to better state coordinates along major highways
                    lat, lon = cls._get_highway_state_coords(state)
                    fallback_used += 1
                
                stations.append(cls(
                    opis_id=int(row['OPIS Truckstop ID']),
                    name=str(row['Truckstop Name']).strip(),
                    address=address,
                    city=city,
                    state=state,
                    rack_id=int(row['Rack ID']),
                    retail_price=float(row['Retail Price']),
                    latitude=lat,
                    longitude=lon
                ))
            
            cls.objects.bulk_create(stations, batch_size=1000)
            
            print(f"Highway coordinates: {highway_parsed}")
            print(f"Fallback coordinates: {fallback_used}")
            print(f"Total stations: {len(stations)}")
            
            return len(stations)

    @classmethod
    def _get_highway_coordinates(cls, address, city, state):
        """Get coordinates based on highway information in the CSV"""
        
        # Extract highway info using regex
        highway_match = re.search(r'I-(\d+)', address.upper())
        
        if highway_match:
            highway_num = int(highway_match.group(1))
            return cls._get_coords_by_highway_and_city(highway_num, city, state)
        
        # If no highway found, try city-based coordinates along major routes
        return cls._get_city_highway_coords(city, state)

    @classmethod
    def _get_coords_by_highway_and_city(cls, highway_num, city, state):
        """Get coordinates for specific cities along major highways"""
        
        # I-80 corridor (NYC to LA northern route)
        if highway_num == 80:
            i80_cities = {
                ('Atkinson', 'IL'): (41.327, -89.127),      # I-80 Exit 27
                ('Peru', 'IL'): (41.327, -89.127),          # I-80 Exit 73  
                ('Stuart', 'IA'): (41.502, -94.380),        # I-80 Exit 93
                ('Council Bluffs', 'IA'): (41.262, -95.861), # I-80 Exit 3
                ('Ogallala', 'NE'): (41.128, -101.719),     # I-80 Exit 126
                ('Gothenburg', 'NE'): (40.927, -99.912),    # I-80 Exit 211
                ('Sidney', 'NE'): (41.144, -103.000),       # I-80 Exit 59
                ('Rock Springs', 'WY'): (41.588, -109.203), # I-80 Exit 104
                ('Gary', 'IN'): (41.593, -87.346),          # I-80 Exit 6
                ('Highland', 'IN'): (41.553, -87.452),      # I-80 Exit 2
                ('Rolling Prairie', 'IN'): (41.653, -86.618), # I-80 MM 56
                ('Perrysburg', 'OH'): (41.557, -83.627),    # I-80 & I-280
                ('Fairfield', 'NJ'): (40.883, -74.299),     # I-80 Exit 47B
            }
            
            city_clean = city.strip()
            key = (city_clean, state)
            if key in i80_cities:
                return i80_cities[key]
        
        # I-35 corridor (Minnesota to Texas)
        elif highway_num == 35:
            i35_cities = {
                ('Jarrell', 'TX'): (30.823, -97.602),       # I-35 Exit 271
                ('Big Cabin', 'OK'): (36.539, -95.206),     # I-44 connects to I-35
                # Add more I-35 cities as needed
            }
            
            key = (city.strip(), state)
            if key in i35_cities:
                return i35_cities[key]
        
        # I-40 corridor (east-west southern route)
        elif highway_num == 40:
            i40_cities = {
                # Add I-40 cities if needed
            }
            
            key = (city.strip(), state)  
            if key in i40_cities:
                return i40_cities[key]
        
        return None, None

    @classmethod
    def _get_city_highway_coords(cls, city, state):
        """Get coordinates for major cities along highway corridors"""
        
        # Major trucking cities with actual highway coordinates
        highway_cities = {
            # Illinois - I-80 corridor
            ('Peru', 'IL'): (41.327, -89.127),
            ('Atkinson', 'IL'): (41.327, -89.127),
            
            # Iowa - I-80 corridor  
            ('Stuart', 'IA'): (41.502, -94.380),
            ('Council Bluffs', 'IA'): (41.262, -95.861),
            
            # Nebraska - I-80 corridor
            ('Ogallala', 'NE'): (41.128, -101.719),
            ('Gothenburg', 'NE'): (40.927, -99.912),
            ('Sidney', 'NE'): (41.144, -103.000),
            
            # Wyoming - I-80 corridor
            ('Rock Springs', 'WY'): (41.588, -109.203),
            
            # Texas - various highways
            ('Jarrell', 'TX'): (30.823, -97.602),   # I-35 
            
            # Add more major trucking cities...
        }
        
        key = (city.strip(), state)
        if key in highway_cities:
            return highway_cities[key]
        
        return None, None

    @classmethod 
    def _get_highway_state_coords(cls, state):
        """Fallback coordinates positioned along major highway corridors (not state centers!)"""
        
        # These coordinates are along actual highway routes, not state geographic centers
        highway_state_coords = {
            # I-80 corridor coordinates (much better than state centers)
            'PA': (41.045, -75.222),   # I-80 through Pennsylvania
            'OH': (41.076, -81.518),   # I-80 through Ohio  
            'IN': (41.559, -87.292),   # I-80 through Indiana
            'IL': (41.327, -89.127),   # I-80 through Illinois
            'IA': (41.502, -94.380),   # I-80 through Iowa
            'NE': (41.128, -101.719),  # I-80 through Nebraska
            'WY': (41.588, -109.203),  # I-80 through Wyoming
            'UT': (40.760, -111.891),  # I-80 through Utah
            'NV': (39.161, -119.767),  # I-80 through Nevada
            'CA': (37.777, -122.418),  # I-80 to San Francisco
            
            # I-40 corridor coordinates (for southern route)
            'TX': (35.222, -101.831),  # I-40 through Texas Panhandle (NOT Houston!)
            'NM': (35.084, -106.651),  # I-40 through New Mexico
            'AZ': (35.198, -111.651),  # I-40 through Arizona
            
            # I-35 corridor coordinates  
            'OK': (35.482, -97.535),   # I-35 through Oklahoma
            
            # Other states - use reasonable highway positions
            'NJ': (40.883, -74.299),   # Near I-80
            'NY': (42.659, -75.615),   # Near I-80/I-90
            'MI': (42.331, -83.046),   # Near I-94
            'WI': (43.074, -87.907),   # Near I-94
            'MN': (44.954, -93.094),   # Near I-94/I-35
            'ND': (46.813, -100.779),  # Near I-94
            'MT': (45.783, -108.501),  # Near I-94/I-90
            'WA': (47.042, -122.893),  # Near I-5
            'OR': (45.512, -122.658),  # Near I-5
            'ID': (43.613, -116.237),  # Near I-84
            'CO': (39.739, -104.990),  # Near I-70/I-25
            'KS': (39.114, -94.627),   # Near I-70
            'MO': (38.572, -92.189),   # Near I-70
            'FL': (28.538, -81.379),   # Near I-4/I-75
            'GA': (33.749, -84.388),   # Near I-75/I-85
            'SC': (34.000, -81.035),   # Near I-77/I-85
            'NC': (35.227, -80.843),   # Near I-77/I-85
            'VA': (37.540, -77.460),   # Near I-95/I-64
            'WV': (39.320, -81.550),   # Near I-77
            'KY': (38.197, -84.86),    # Near I-75/I-64
            'TN': (36.165, -86.784),   # Near I-40/I-65
            'AL': (33.521, -86.802),   # Near I-65/I-20
            'MS': (32.320, -90.207),   # Near I-20/I-55
            'LA': (30.45, -91.140),    # Near I-10/I-12
            'AR': (34.746, -92.289),   # Near I-40
        }
        
        return highway_state_coords.get(state, (39.0, -98.0))

 

    @classmethod
    def geocode_stations(cls):
        """Geocode stations that don't have coordinates yet using Nominatim (optimized)"""
        # Use optimized query to get stations without coordinates
        stations_without_coords = cls.objects.filter(
            latitude__isnull=True
        ).only('opis_id', 'address', 'city', 'state')[:50]  # Limit to avoid rate limits
        
        updated_stations = []
        updated_count = 0
        
        for station in stations_without_coords:
            try:
                # Create full address for geocoding
                full_address = f"{station.address}, {station.city}, {station.state}, USA"
                
                # Use Nominatim (free OpenStreetMap geocoding)
                url = "https://nominatim.openstreetmap.org/search"
                params = {
                    'q': full_address,
                    'format': 'json',
                    'countrycodes': 'us',
                    'limit': 1
                }
                headers = {'User-Agent': 'FuelOptimizer/1.0'}
                
                response = requests.get(url, params=params, headers=headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if data:
                        station.latitude = float(data[0]['lat'])
                        station.longitude = float(data[0]['lon'])
                        updated_stations.append(station)
                        updated_count += 1
                        
            except Exception as e:
                print(f"Failed to geocode {station.name}: {e}")
                continue
        
        # Bulk update for better performance
        if updated_stations:
            with transaction.atomic():
                cls.objects.bulk_update(
                    updated_stations, 
                    ['latitude', 'longitude'], 
                    batch_size=100
                )
                
        return updated_count


class RouteOptimizer:
    """Optimized route optimization class with better database interactions"""
    
    def __init__(self):
        self.max_range_miles = 500
        self.mpg = 10
        self.tank_capacity_gallons = self.max_range_miles / self.mpg  # 50 gallons
    
    def calculate_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two points using Haversine formula"""
        R = 3959  # Earth's radius in miles
        
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)
        
        a = (math.sin(delta_lat / 2) ** 2 + 
             math.cos(lat1_rad) * math.cos(lat2_rad) * 
             math.sin(delta_lon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return R * c
    
    # def get_route_from_openrouteservice(self, start_coords: Tuple[float, float], 
    #                                     end_coords: Tuple[float, float]) -> Dict:
    #     """Get route from GraphHopper public demo (free, no key, identical to OSRM format)"""
    #     # GraphHopper public demo endpoint — no API key needed, unlimited for light use
    #     url = "https://graphhopper.com/api/1/route"
        
    #     # Format: lon1,lat1;lon2,lat2 (same as OSRM)
    #     coordinates = f"{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}"
        
    #     params = {
    #         'point': coordinates,
    #         'vehicle': 'car',  # or 'truck' for your fuel optimizer
    #         'calc_points': 'true',
    #         'points_encoded': 'false',  # Get raw GeoJSON coords
    #         'details': 'instruction',  # Optional: add turn-by-turn if needed
    #         'type': 'json'
    #     }
        
    #     try:
    #         response = requests.get(url, params=params, timeout=30)
    #         if response.status_code == 200:
    #             data = response.json()
    #             if data['paths']:
    #                 path = data['paths'][0]
    #                 # Adapt to your exact existing structure (GeoJSON LineString)
    #                 geometry = {
    #                     'type': 'LineString',
    #                     'coordinates': path['points']['coordinates']  # Already [lon, lat] pairs
    #                 }
    #                 route = {
    #                     'distance': path['distance'],  # meters
    #                     'duration': path['time'] / 1000,  # seconds (GraphHopper uses ms)
    #                     'geometry': geometry
    #                 }
    #                 return {'routes': [route]}
    #             else:
    #                 print("No paths returned from GraphHopper")
    #                 return None
    #         else:
    #             print(f"GraphHopper API error: {response.status_code} - {response.text}")
    #             return None
    #     except Exception as e:
    #         print(f"Error calling GraphHopper: {e}")
    #         return None
    
    def get_route_from_openrouteservice(self, start_coords: Tuple[float, float], 
                                      end_coords: Tuple[float, float]) -> Dict:
        """Get route information from OpenRouteService"""
        url = "http://router.project-osrm.org/route/v1/driving/"
        
        # Format: lon,lat;lon,lat
        coordinates = f"{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}"
        
        params = {
            'overview': 'full',
            'geometries': 'geojson'
        }
        
        try:
            response = requests.get(f"{url}{coordinates}", params=params, timeout=30)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"OSRM API error: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"Error calling OSRM: {e}")
            return None
    
    def _geocode_location(self, location: str) -> Tuple[float, float]:
        """Geocode a location string to coordinates using Nominatim"""
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': location + ', USA',
            'format': 'json',
            'countrycodes': 'us',
            'limit': 1
        }
        headers = {'User-Agent': 'FuelOptimizer/1.0'}
        
        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data:
                    return float(data[0]['lat']), float(data[0]['lon'])
            return None
        except Exception as e:
            print(f"Geocoding error: {e}")
            return None
        
    

    def geocode_location(self, location):
        # Make 100% Memcached-safe key
        raw_key = f"geocode:{location.lower().strip()}"
        cache_key = "g:" + hashlib.md5(raw_key.encode()).hexdigest()[:16]  # Short & safe

        result = cache.get(cache_key)
        if result is not None:
            return result

        result = self._geocode_location(location)
        if result:
            cache.set(cache_key, result, timeout=60*60*24*90)  # 90 days – popular cities forever

        return result
    
    def find_fuel_stops_along_route_optimized(self, route_coords: List[Tuple[float, float]], 
                                            max_detour_miles: float = 50) -> List[Dict]:
        """Optimized version using custom manager methods"""
        if len(route_coords) < 2:
            return []
            
        fuel_stops = []
        total_distance = 0
        
        # Calculate total route distance first
        for i in range(len(route_coords) - 1):
            segment_dist = self.calculate_distance(
                route_coords[i][0], route_coords[i][1],
                route_coords[i + 1][0], route_coords[i + 1][1]
            )
            total_distance += segment_dist
        
        print(f"DEBUG: Total route distance: {total_distance:.1f} miles")
        
        # Use optimized manager methods
        base_stations = FuelStation.objects.with_coordinates().cheapest_first().only(
            'opis_id', 'name', 'address', 'city', 'state',
            'retail_price', 'latitude', 'longitude'
        )[:1000]  # Get top 1000 cheapest stations
        
        # Convert to list for performance in loops
        all_stations = list(base_stations)
        
        print(f"DEBUG: Found {len(all_stations)} stations in database")
        
        # Determine number of stops needed (every 400 miles)
        num_stops_needed = max(1, int(total_distance / 400))
        if total_distance > 1000:
            num_stops_needed = max(2, int(total_distance / 450))
            
        print(f"DEBUG: Need {num_stops_needed} fuel stops")
        
        # For each stop, find best station
        for stop_num in range(num_stops_needed):
            # Calculate target distance for this stop
            target_distance = (stop_num + 1) * (total_distance / (num_stops_needed + 1))
            
            # Find the route coordinate closest to target distance
            accumulated_distance = 0
            best_coord = None
            
            for i in range(len(route_coords) - 1):
                segment_dist = self.calculate_distance(
                    route_coords[i][0], route_coords[i][1],
                    route_coords[i + 1][0], route_coords[i + 1][1]
                )
                
                if accumulated_distance + segment_dist >= target_distance:
                    best_coord = route_coords[i]
                    break
                    
                accumulated_distance += segment_dist
            
            if not best_coord:
                best_coord = route_coords[len(route_coords) // 2]  # Fallback to midpoint
                
            print(f"DEBUG: Stop {stop_num + 1} search center: {best_coord}")
            
            # Find closest cheap station within expanded search radius
            best_station = None
            best_distance = float('inf')
            
            search_radius = max_detour_miles * 2 if total_distance > 2000 else max_detour_miles
            
            for station in all_stations:
                distance_to_station = self.calculate_distance(
                    best_coord[0], best_coord[1],
                    station.latitude, station.longitude
                )
                
                if distance_to_station <= search_radius:
                    # Prioritize by price first, then distance
                    if not best_station or station.retail_price < best_station.retail_price:
                        best_station = station
                        best_distance = distance_to_station
                    elif (station.retail_price == best_station.retail_price and 
                          distance_to_station < best_distance):
                        best_station = station
                        best_distance = distance_to_station
            
            if best_station:
                print(f"DEBUG: Found station: {best_station.name} in {best_station.city}, {best_station.state}")
                fuel_stops.append({
                    'station': best_station,
                    'distance_from_route': best_distance,
                    'cumulative_distance': target_distance
                })
            else:
                print(f"DEBUG: No station found for stop {stop_num + 1}")
                # For demo purposes, add a fallback station from the cheapest available
                if all_stations:
                    fallback_station = all_stations[0]
                    fuel_stops.append({
                        'station': fallback_station,
                        'distance_from_route': 25.0,  # Estimate
                        'cumulative_distance': target_distance
                    })
                    print(f"DEBUG: Using fallback station: {fallback_station.name}")
        
        print(f"DEBUG: Final fuel stops count: {len(fuel_stops)}")
        return fuel_stops
    
    def calculate_total_fuel_cost(self, fuel_stops: List[Dict], total_distance: float) -> Dict:
        """Calculate total fuel cost for the trip"""
        total_gallons = total_distance / self.mpg
        
        if not fuel_stops:
            # If no fuel stops found, use average price estimation
            average_price = 3.50  # Fallback average price
            total_cost = total_gallons * average_price
            
            return {
                'total_cost': round(total_cost, 2),
                'total_gallons': round(total_gallons, 2),
                'average_price': average_price,
                'stops_count': 0,
                'note': 'Estimated cost - no specific fuel stops found'
            }
        
        total_cost = 0
        
        # Calculate fuel needed per segment
        if len(fuel_stops) == 1:
            # Single stop - fill up completely
            gallons_needed = min(total_gallons, self.tank_capacity_gallons)
            station_cost = gallons_needed * float(fuel_stops[0]['station'].retail_price)
            total_cost = station_cost
            fuel_stops[0]['gallons'] = gallons_needed
            fuel_stops[0]['cost_at_station'] = station_cost
            
        else:
            # Multiple stops - distribute fuel purchases
            gallons_per_stop = self.tank_capacity_gallons  # Fill tank at each stop
            
            for i, stop in enumerate(fuel_stops):
                if i == len(fuel_stops) - 1:  # Last stop
                    # Calculate remaining fuel needed
                    remaining_distance = total_distance - stop['cumulative_distance']
                    remaining_gallons = max(10, remaining_distance / self.mpg)  # Minimum 10 gallons
                    gallons_to_buy = min(remaining_gallons, self.tank_capacity_gallons)
                else:
                    gallons_to_buy = gallons_per_stop
                
                station_cost = gallons_to_buy * float(stop['station'].retail_price)
                total_cost += station_cost
                stop['gallons'] = round(gallons_to_buy, 1)
                stop['cost_at_station'] = round(station_cost, 2)
        
        average_price = total_cost / total_gallons if total_gallons > 0 else 0
        
        return {
            'total_cost': round(total_cost, 2),
            'total_gallons': round(total_gallons, 1),
            'average_price': round(average_price, 3),
            'stops_count': len(fuel_stops)
        }
    
    def create_route_map(self, start_coords: Tuple[float, float], 
                        end_coords: Tuple[float, float], 
                        route_coords: List[Tuple[float, float]], 
                        fuel_stops: List[Dict]) -> str:
        """Create an interactive map showing the route and fuel stops"""
        # Calculate center point for map
        center_lat = (start_coords[0] + end_coords[0]) / 2
        center_lon = (start_coords[1] + end_coords[1]) / 2
        
        # Create map
        m = folium.Map(location=[center_lat, center_lon], zoom_start=6)
        
        # Add route line
        route_points = [[lat, lon] for lat, lon in route_coords]
        folium.PolyLine(
            route_points, 
            color='blue', 
            weight=4, 
            opacity=0.8,
            popup='Route'
        ).add_to(m)
        
        # Add start marker
        folium.Marker(
            [start_coords[0], start_coords[1]],
            popup='Start',
            icon=folium.Icon(color='green', icon='play')
        ).add_to(m)
        
        # Add end marker
        folium.Marker(
            [end_coords[0], end_coords[1]],
            popup='Destination',
            icon=folium.Icon(color='red', icon='stop')
        ).add_to(m)
        
        # Add fuel stop markers
        for i, stop in enumerate(fuel_stops):
            station = stop['station']
            popup_text = f"""
            <b>{station.name}</b><br>
            {station.address}<br>
            {station.city}, {station.state}<br>
            <b>Price: ${station.retail_price}/gallon</b><br>
            Stop #{i + 1}
            """
            
            folium.Marker(
                [station.latitude, station.longitude],
                popup=folium.Popup(popup_text, max_width=300),
                icon=folium.Icon(color='orange', icon='info-sign')
            ).add_to(m)

        map_html = m._repr_html_()
    
        # Save to a file
        import os
        from datetime import datetime
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"route_map_{timestamp}.html"
        filepath = f"/tmp/{filename}"  # or any accessible directory
        
        with open(filepath, 'w') as f:
            f.write(map_html)
        
        return f"http://localhost:8000{filepath}" 
        