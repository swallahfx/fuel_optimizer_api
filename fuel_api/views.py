from datetime import datetime
import json
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from django.http import JsonResponse
from django.db import transaction
from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from .models import FuelStation, RouteOptimizer
from .serializers import (
    RouteRequestSerializer, 
    RouteResponseSerializer,
    FuelStationSerializer
)
import time
import numpy as np
from django.core.cache import cache
import hashlib
import json



class FuelStationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for fuel station operations including route optimization
    """
    queryset = FuelStation.objects.select_related().prefetch_related()
    serializer_class = FuelStationSerializer
    
    def get_queryset(self):
        """Optimize queryset with select_related for better performance"""
        return FuelStation.objects.filter(
            latitude__isnull=False,
            longitude__isnull=False
        ).only(
            'opis_id', 'name', 'address', 'city', 'state', 
            'retail_price', 'latitude', 'longitude'
        ).order_by('retail_price')

    @extend_schema(
        summary="Health Check",
        description="Simple health check endpoint with system status",
        responses={200: {
            'type': 'object',
            'properties': {
                'status': {'type': 'string'},
                'timestamp': {'type': 'number'},
                'fuel_stations_count': {'type': 'integer'}
            }
        }}
    )
    @action(detail=False, methods=['get'])
    def health_check(self, request):
        """Simple health check endpoint"""
        # Use optimized count query
        count = FuelStation.objects.filter(
            latitude__isnull=False,
            longitude__isnull=False
        ).count()
        
        return Response({
            'status': 'healthy',
            'timestamp': time.time(),
            'fuel_stations_count': count
        })

    @extend_schema(
        summary="Load Fuel Data",
        description="Load fuel station data from CSV (admin endpoint)",
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'message': {'type': 'string'},
                    'status': {'type': 'string'}
                }
            },
            500: {
                'type': 'object',
                'properties': {
                    'error': {'type': 'string'},
                    'status': {'type': 'string'}
                }
            }
        }
    )
    @action(detail=False, methods=['post'])
    def load_fuel_data(self, request):
        """Load fuel station data from CSV (admin endpoint)"""
        try:
            with transaction.atomic():
                count = FuelStation.load_from_csv()
            return Response({
                'message': f'Successfully loaded {count} fuel stations',
                'status': 'success'
            })
        except Exception as e:
            return Response({
                'error': str(e),
                'status': 'error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @extend_schema(
        summary="Geocode Stations",
        description="Geocode fuel stations that don't have coordinates (admin endpoint)",
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'message': {'type': 'string'},
                    'status': {'type': 'string'}
                }
            },
            500: {
                'type': 'object',
                'properties': {
                    'error': {'type': 'string'},
                    'status': {'type': 'string'}
                }
            }
        }
    )
    @action(detail=False, methods=['post'])
    def geocode_stations(self, request):
        """Geocode fuel stations (admin endpoint)"""
        try:
            with transaction.atomic():
                count = FuelStation.geocode_stations()
            return Response({
                'message': f'Successfully geocoded {count} stations',
                'status': 'success'
            })
        except Exception as e:
            return Response({
                'error': str(e),
                'status': 'error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


    @extend_schema(
        summary="Optimize Route",
        description="Main endpoint for route optimization with fuel stops",
        request=RouteRequestSerializer,
        responses={
            200: RouteResponseSerializer,
            400: {
                'type': 'object',
                'properties': {
                    'error': {'type': 'string'},
                    'status': {'type': 'string'}
                }
            },
            500: {
                'type': 'object',
                'properties': {
                    'error': {'type': 'string'},
                    'status': {'type': 'string'}
                }
            }
        }
    )
    @action(detail=False, methods=['post'])
    def optimize_route(self, request):
        """
        Main endpoint for route optimization with fuel stops
        
        POST /api/fuel-stations/optimize_route/
        {
            "start_location": "New York, NY",
            "end_location": "Los Angeles, CA"
        }
        """
        # Validate input
        serializer = RouteRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        start_location = serializer.validated_data['start_location'].strip()
        end_location = serializer.validated_data['end_location'].strip()

        # CREATE A UNIQUE CACHE KEY FROM THE TWO LOCATIONS (case + space insensitive)
        cache_key = f"route_opt:{hashlib.md5(f'{start_location.lower()}|{end_location.lower()}'.encode()).hexdigest()}"

        # # TRY TO GET FROM CACHE FIRST
        cached_result = cache.get(cache_key)
        if cached_result:
            print(f"CACHE HIT for {start_location} → {end_location}")
            return Response(cached_result, status=status.HTTP_200_OK)

        print(f"CACHE MISS — computing route {start_location} → {end_location}")
        
        try:
            optimizer = RouteOptimizer()
            
            # Step 1: Geocode locations
            start_coords = optimizer.geocode_location(start_location)
            end_coords = optimizer.geocode_location(end_location)
            
            if not start_coords or not end_coords:
                return Response({
                    'error': 'Unable to geocode one or both locations. Please check the location names.',
                    'status': 'error'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Step 2: Get route from routing service
            route_data = optimizer.get_route_from_openrouteservice(start_coords, end_coords)

            if not route_data or 'routes' not in route_data:
                print("Routing API unavailable — using straight-line approximation for demo")
                
                # Use your existing Haversine method for distance
                total_distance_miles = optimizer.calculate_distance(
                    start_coords[0], start_coords[1], end_coords[0], end_coords[1]
                )
                total_distance_meters = total_distance_miles * 1609.34  # Convert to meters for compatibility
                duration_seconds = int(total_distance_miles * 3600 / 65)  # Assume 65 mph average speed
                
                # Generate fake route coords: 21 points along straight line (good enough for fuel stops)
                route_coords = []
                for i in range(21):
                    t = i / 20.0
                    lat = start_coords[0] + t * (end_coords[0] - start_coords[0])
                    lon = start_coords[1] + t * (end_coords[1] - start_coords[1])
                    route_coords.append((lat, lon))
                
                # Fake route_data to match your parsing code
                route_data = {
                    'routes': [{
                        'distance': total_distance_meters,
                        'duration': duration_seconds,
                        'geometry': {
                            'type': 'LineString',
                            'coordinates': [(lon, lat) for lat, lon in route_coords]  # [lon, lat] as expected
                        }
                    }]
                }
            
            route = route_data['routes'][0]
            total_distance_meters = route['distance']
            total_distance_miles = total_distance_meters * 0.000621371  # Convert to miles
            duration_seconds = route['duration']
            

            geometry = route['geometry']
            if geometry['type'] != 'LineString':
                raise ValueError("Expected LineString geometry")

            # Convert [lon, lat] → [lat, lon]
            route_coords = [(lat, lon) for lon, lat in geometry['coordinates']]


            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"route_coords_{timestamp}.json"
            filepath = f"/tmp/{filename}"

            with open(filepath, 'w') as f:
                json.dump(route_coords, f, indent=2)  # indent=2 for pretty formatting


            encoded_polyline =  f"http://localhost:8000{filepath}"
            
            # Step 3: Find optimal fuel stops with optimized queries
            fuel_stops = self._find_optimized_fuel_stops(route_coords, optimizer)
            
            # Step 4: Calculate fuel costs
            fuel_cost_summary = optimizer.calculate_total_fuel_cost(fuel_stops, total_distance_miles)
            
            # Step 5: Create map
            map_html = optimizer.create_route_map(start_coords, end_coords, route_coords, fuel_stops)
            
            # Step 6: Format response
            hours = duration_seconds // 3600
            minutes = (duration_seconds % 3600) // 60
            drive_time = f"{int(hours)}h {int(minutes)}m"

            formatted_fuel_stops = []
            for stop in fuel_stops:
                station_dict = {
                    'opis_id': stop['station'].opis_id,
                    'name': stop['station'].name,
                    'address': stop['station'].address,
                    'city': stop['station'].city,
                    'state': stop['station'].state,
                    'retail_price': float(stop['station'].retail_price),
                    'latitude': stop['station'].latitude,
                    'longitude': stop['station'].longitude
                }
                # Add optional fields if they exist
                if 'gallons' in stop:
                    station_dict['gallons'] = stop['gallons']
                if 'cost_at_station' in stop:
                    station_dict['cost_at_station'] = stop['cost_at_station']
                    
                formatted_fuel_stops.append(station_dict)
            
            # Save encoded polyline to database
            
            response_data = {
                'start_coordinates': list(start_coords),
                'end_coordinates': list(end_coords),
                'total_distance_miles': round(total_distance_miles, 1),
                'estimated_drive_time': drive_time,
                'fuel_stops': formatted_fuel_stops,
                'fuel_cost_summary': fuel_cost_summary,
                'map_html': map_html,
                'route_coordinates': encoded_polyline
            }

            cache.set(cache_key, response_data, timeout=3600)  # Cache for 1 hour
            print(f"CACHED result for {start_location} → {end_location}")

            return Response(response_data, status=status.HTTP_200_OK)
        
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({
                'error': f'Internal server error: {str(e)}',
                'status': 'error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _find_optimized_fuel_stops__(self, route_coords, optimizer):
        """Optimized version of find_fuel_stops_along_route with better ORM queries"""
        if len(route_coords) < 2:
            return []
            
        fuel_stops = []
        total_distance = 0
        
        # Calculate total route distance first
        for i in range(len(route_coords) - 1):
            segment_dist = optimizer.calculate_distance(
                route_coords[i][0], route_coords[i][1],
                route_coords[i + 1][0], route_coords[i + 1][1]
            )
            total_distance += segment_dist
        
        # Get optimized queryset with only needed fields
        stations_queryset = self.get_queryset().only(
            'opis_id', 'name', 'address', 'city', 'state',
            'retail_price', 'latitude', 'longitude'
        )[:1000]  # Limit to top 1000 cheapest stations
        
        # Convert to list for better performance in loops
        all_stations = list(stations_queryset)
        
        # Determine number of stops needed
        num_stops_needed = max(1, int(total_distance / 400))
        if total_distance > 1000:
            num_stops_needed = max(2, int(total_distance / 450))
            
        # For each stop, find best station
        for stop_num in range(num_stops_needed):
            target_distance = (stop_num + 1) * (total_distance / (num_stops_needed + 1))
            
            # Find the route coordinate closest to target distance
            accumulated_distance = 0
            best_coord = None
            
            for i in range(len(route_coords) - 1):
                segment_dist = optimizer.calculate_distance(
                    route_coords[i][0], route_coords[i][1],
                    route_coords[i + 1][0], route_coords[i + 1][1]
                )
                
                if accumulated_distance + segment_dist >= target_distance:
                    best_coord = route_coords[i]
                    break
                    
                accumulated_distance += segment_dist
            
            if not best_coord:
                best_coord = route_coords[len(route_coords) // 2]
                
            # Find closest cheap station
            best_station = None
            best_distance = float('inf')
            max_detour_miles = 100 if total_distance > 2000 else 50
            
            for station in all_stations:
                distance_to_station = optimizer.calculate_distance(
                    best_coord[0], best_coord[1],
                    station.latitude, station.longitude
                )
                
                
                if distance_to_station <= max_detour_miles:
                    if not best_station or station.retail_price < best_station.retail_price:
                        best_station = station
                        best_distance = distance_to_station
                    elif (station.retail_price == best_station.retail_price and 
                          distance_to_station < best_distance):
                        best_station = station
                        best_distance = distance_to_station
            
            if best_station:
                fuel_stops.append({
                    'station': best_station,
                    'distance_from_route': best_distance,
                    'cumulative_distance': target_distance
                })
            elif all_stations:
                # Fallback to cheapest station
                fallback_station = all_stations[0]
                fuel_stops.append({
                    'station': fallback_station,
                    'distance_from_route': 25.0,
                    'cumulative_distance': target_distance
                })
        
        return fuel_stops
    
    

    def _find_optimized_fuel_stops(self, route_coords, optimizer):
        if len(route_coords) < 2:
            return []

        # Pre-calculate segment distances and cumulative
        cumulative = [0.0]
        for i in range(len(route_coords) - 1):
            lat1, lon1 = route_coords[i]
            lat2, lon2 = route_coords[i + 1]
            d = optimizer.calculate_distance(lat1, lon1, lat2, lon2)
            cumulative.append(cumulative[-1] + d)

        total_distance = cumulative[-1]
        if total_distance == 0:
            return []

        num_stops = max(1, int(total_distance / 400))
        if total_distance > 1500:
            num_stops = max(3, int(total_distance / 450))

        # Get top 1000 cheapest stations
        stations = list(FuelStation.objects.filter(
            latitude__isnull=False,
            longitude__isnull=False,
            retail_price__isnull=False
        ).order_by('retail_price')[:1000])

        if not stations:
            return []

        # NumPy arrays
        lats = np.array([s.latitude for s in stations], dtype=np.float64)
        lons = np.array([s.longitude for s in stations], dtype=np.float64)
        prices = np.array([float(s.retail_price) for s in stations], dtype=np.float64)
        station_objs = np.array(stations)
        cos_lats = np.cos(np.radians(lats))

        # Target points along route
        target_distances = [(i + 1) * total_distance / (num_stops + 1) for i in range(num_stops)]
        target_coords = []
        for dist in target_distances:
            idx = min(range(len(cumulative)), key=lambda i: abs(cumulative[i] - dist))
            target_coords.append(route_coords[idx])

        fuel_stops = []
        used = set()

        for idx, (lat, lon) in enumerate(target_coords):
            # Vectorized Haversine
            dlat = np.radians(lats - lat)
            dlon = np.radians(lons - lon)
            a = np.sin(dlat / 2)**2 + np.cos(np.radians(lat)) * cos_lats * np.sin(dlon / 2)**2
            c = 2 * np.arcsin(np.minimum(1, np.sqrt(a)))
            distances_mi = 3959.0 * c

            mask = distances_mi <= 80
            candidates = np.where(mask)[0]
            candidates = [i for i in candidates if i not in used]

            if candidates:
                scores = prices[candidates] + distances_mi[candidates] * 0.02
                best_i = candidates[int(np.argmin(scores))]
            else:
                # Fallback: cheapest unused
                available = [i for i in range(len(stations)) if i not in used]
                if not available:
                    continue
                best_i = min(available, key=lambda i: prices[i])

            used.add(best_i)
            station = station_objs[best_i]
            detour = round(float(distances_mi[best_i]), 1)

            fuel_stops.append({
                'station': station,
                'distance_from_route': detour,
                'cumulative_distance': target_distances[idx]
            })

        return fuel_stops

    def _find_optimized_fuel_stops___(self, route_coords, optimizer):
        """Find fuel stops actually along the route with simplified spatial logic"""
        if len(route_coords) < 2:
            return []
            
        fuel_stops = []
        total_distance = 0
        
        # Calculate total route distance
        for i in range(len(route_coords) - 1):
            segment_dist = optimizer.calculate_distance(
                route_coords[i][0], route_coords[i][1],
                route_coords[i + 1][0], route_coords[i + 1][1]
            )
            total_distance += segment_dist
        
        print(f"DEBUG: Total route distance: {total_distance:.1f} miles")
        
        # Get all stations with coordinates (simplify the query first)
        all_stations = list(FuelStation.objects.filter(
            latitude__isnull=False,
            longitude__isnull=False
        ).order_by('retail_price')[:500])  # Get top 500 cheapest
        
        print(f"DEBUG: Found {len(all_stations)} stations with coordinates")
        
        if not all_stations:
            print("DEBUG: No stations found with coordinates!")
            return []
        
        # Determine number of stops needed
        fuel_range = 400  # miles
        num_stops_needed = max(1, int(total_distance / fuel_range))
        if total_distance > 1500:
            num_stops_needed = max(3, int(total_distance / 450))
            
        print(f"DEBUG: Need {num_stops_needed} fuel stops")
        
        # Track used stations
        used_stations = set()
        
        # Calculate cumulative distances along route
        cumulative_distances = [0]
        for i in range(len(route_coords) - 1):
            segment_dist = optimizer.calculate_distance(
                route_coords[i][0], route_coords[i][1],
                route_coords[i + 1][0], route_coords[i + 1][1]
            )
            cumulative_distances.append(cumulative_distances[-1] + segment_dist)
        
        for stop_num in range(num_stops_needed):
            # Calculate target distance for this stop
            target_distance = (stop_num + 1) * (total_distance / (num_stops_needed + 1))
            
            # Find route coordinate closest to target distance
            target_coord = None
            min_diff = float('inf')
            
            for i, cum_dist in enumerate(cumulative_distances):
                diff = abs(cum_dist - target_distance)
                if diff < min_diff:
                    min_diff = diff
                    if i < len(route_coords):
                        target_coord = route_coords[i]
            
            if not target_coord:
                target_coord = route_coords[len(route_coords) // 2]  # fallback
                
            print(f"DEBUG: Stop {stop_num + 1} target coord: {target_coord}")
            
            # Find best station near this coordinate
            best_station = None
            best_score = float('inf')
            search_radius = 200  # Start with larger radius
            
            for station in all_stations:
                # Skip used stations
                if station.opis_id in used_stations:
                    continue
                    
                # Calculate distance to this route point
                distance = optimizer.calculate_distance(
                    target_coord[0], target_coord[1],
                    station.latitude, station.longitude
                )
                
                if distance <= search_radius:
                    # Score based on price + distance (prioritize price)
                    price_score = float(station.retail_price) * 100  # Weight price heavily
                    distance_score = distance  # Distance in miles
                    total_score = price_score + distance_score
                    
                    if total_score < best_score:
                        best_station = station
                        best_score = total_score
            
            if best_station:
                distance_from_route = optimizer.calculate_distance(
                    target_coord[0], target_coord[1],
                    best_station.latitude, best_station.longitude
                )
                
                print(f"DEBUG: Selected {best_station.name} in {best_station.city}, {best_station.state}")
                print(f"DEBUG: Price: ${best_station.retail_price}, Distance: {distance_from_route:.1f} miles")
                
                used_stations.add(best_station.opis_id)
                fuel_stops.append({
                    'station': best_station,
                    'distance_from_route': distance_from_route,
                    'cumulative_distance': target_distance
                })
            else:
                print(f"DEBUG: No station found for stop {stop_num + 1} within {search_radius} miles")
                # Try fallback with any unused cheapest station
                for station in all_stations:
                    if station.opis_id not in used_stations:
                        print(f"DEBUG: Using fallback station: {station.name} in {station.city}, {station.state}")
                        used_stations.add(station.opis_id)
                        fuel_stops.append({
                            'station': station,
                            'distance_from_route': 50.0,  # estimate
                            'cumulative_distance': target_distance
                        })
                        break
        
        print(f"DEBUG: Final fuel stops found: {len(fuel_stops)}")
        return fuel_stops


    @extend_schema(
        summary="Get Cheapest Stations",
        description="Get cheapest fuel stations with optional filtering",
        parameters=[
            OpenApiParameter(
                name='limit',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Number of stations to return (default: 10)',
                required=False
            ),
            OpenApiParameter(
                name='state',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Filter by state code (e.g., CA, TX)',
                required=False
            )
        ],
        responses={200: FuelStationSerializer(many=True)}
    )
    @action(detail=False, methods=['get'])
    def cheapest_stations(self, request):
        """Get cheapest fuel stations (optimized for testing/debugging)"""
        limit = int(request.GET.get('limit', 10))
        state = request.GET.get('state')
        
        # Start with optimized base queryset
        queryset = self.get_queryset()
        
        if state:
            queryset = queryset.filter(state=state.upper())
        
        # Use only() for better performance - select only needed fields
        stations = queryset.only(
            'name', 'city', 'state', 'retail_price', 'address'
        )[:limit]
        
        # Serialize efficiently
        data = []
        for station in stations:
            data.append({
                'name': station.name,
                'city': station.city,
                'state': station.state,
                'price': float(station.retail_price),
                'address': station.address
            })
        
        return Response(data)