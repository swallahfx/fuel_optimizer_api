from rest_framework import serializers
from .models import FuelStation


class FuelStationSerializer(serializers.ModelSerializer):
    """Optimized serializer for FuelStation model"""
    
    class Meta:
        model = FuelStation
        fields = [
            'opis_id', 'name', 'address', 'city', 'state', 
            'retail_price', 'latitude', 'longitude'
        ]
        read_only_fields = fields  # All fields are read-only for this API


class RouteRequestSerializer(serializers.Serializer):
    """Serializer for route optimization requests"""
    start_location = serializers.CharField(
        max_length=255, 
        help_text="Starting location (e.g., 'New York, NY')",
        style={'placeholder': 'New York, NY'}
    )
    end_location = serializers.CharField(
        max_length=255, 
        help_text="Destination location (e.g., 'Los Angeles, CA')",
        style={'placeholder': 'Los Angeles, CA'}
    )
    
    def validate_start_location(self, value):
        """Validate start location"""
        if not value or len(value.strip()) < 3:
            raise serializers.ValidationError(
                "Start location must be at least 3 characters long"
            )
        return value.strip()
    
    def validate_end_location(self, value):
        """Validate end location"""
        if not value or len(value.strip()) < 3:
            raise serializers.ValidationError(
                "End location must be at least 3 characters long"
            )
        return value.strip()
    
    def validate(self, data):
        """Cross-field validation"""
        if data.get('start_location', '').lower() == data.get('end_location', '').lower():
            raise serializers.ValidationError(
                "Start and end locations cannot be the same"
            )
        return data


class FuelStopDetailSerializer(serializers.Serializer):
    """Detailed serializer for individual fuel stops"""
    opis_id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    address = serializers.CharField(read_only=True)
    city = serializers.CharField(read_only=True)
    state = serializers.CharField(read_only=True)
    retail_price = serializers.DecimalField(max_digits=6, decimal_places=3, read_only=True)
    latitude = serializers.FloatField(read_only=True)
    longitude = serializers.FloatField(read_only=True)
    distance_from_route = serializers.FloatField(read_only=True)
    cumulative_distance = serializers.FloatField(read_only=True)
    gallons = serializers.FloatField(required=False, read_only=True)
    cost_at_station = serializers.FloatField(required=False, read_only=True)


class FuelStopSerializer(serializers.Serializer):
    """Serializer for fuel stops in route response"""
    station = FuelStationSerializer(read_only=True)
    distance_from_route = serializers.FloatField(read_only=True)
    cumulative_distance = serializers.FloatField(read_only=True)
    gallons = serializers.FloatField(required=False, read_only=True)
    cost_at_station = serializers.FloatField(required=False, read_only=True)


class FuelCostSummarySerializer(serializers.Serializer):
    """Serializer for fuel cost summary"""
    total_cost = serializers.FloatField(read_only=True)
    total_gallons = serializers.FloatField(read_only=True)
    average_price = serializers.FloatField(read_only=True)
    stops_count = serializers.IntegerField(read_only=True)
    note = serializers.CharField(required=False, read_only=True)


class RouteResponseSerializer(serializers.Serializer):
    """Comprehensive serializer for route optimization response"""
    start_coordinates = serializers.ListField(
        child=serializers.FloatField(),
        read_only=True,
        help_text="[latitude, longitude] of start location"
    )
    end_coordinates = serializers.ListField(
        child=serializers.FloatField(),
        read_only=True,
        help_text="[latitude, longitude] of end location"
    )
    total_distance_miles = serializers.FloatField(
        read_only=True,
        help_text="Total distance of the route in miles"
    )
    estimated_drive_time = serializers.CharField(
        read_only=True,
        help_text="Estimated drive time (e.g., '5h 30m')"
    )
    fuel_stops = FuelStopDetailSerializer(
        many=True, 
        read_only=True,
        help_text="List of recommended fuel stops along the route"
    )
    fuel_cost_summary = FuelCostSummarySerializer(
        read_only=True,
        help_text="Summary of total fuel costs for the trip"
    )
    map_html = serializers.CharField(
        read_only=True,
        help_text="HTML content for interactive map display"
    )
    route_coordinates = serializers.ListField(
        child=serializers.ListField(child=serializers.FloatField()),
        required=False,
        read_only=True,
        help_text="Array of [latitude, longitude] pairs defining the route path"
    )


class CheapestStationsQuerySerializer(serializers.Serializer):
    """Serializer for cheapest stations query parameters"""
    limit = serializers.IntegerField(
        default=10,
        min_value=1,
        max_value=100,
        help_text="Number of stations to return (1-100, default: 10)"
    )
    state = serializers.CharField(
        max_length=2,
        required=False,
        help_text="Filter by state code (e.g., 'CA', 'TX')"
    )
    
    def validate_state(self, value):
        """Validate state code"""
        if value:
            value = value.upper().strip()
            if len(value) != 2:
                raise serializers.ValidationError("State code must be exactly 2 characters")
        return value


class CheapestStationResponseSerializer(serializers.Serializer):
    """Serializer for cheapest stations response"""
    name = serializers.CharField(read_only=True)
    city = serializers.CharField(read_only=True)
    state = serializers.CharField(read_only=True)
    price = serializers.FloatField(read_only=True)
    address = serializers.CharField(read_only=True)


class HealthCheckResponseSerializer(serializers.Serializer):
    """Serializer for health check response"""
    status = serializers.CharField(read_only=True)
    timestamp = serializers.FloatField(read_only=True)
    fuel_stations_count = serializers.IntegerField(read_only=True)


class LoadDataResponseSerializer(serializers.Serializer):
    """Serializer for load data response"""
    message = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)


class GeocodeResponseSerializer(serializers.Serializer):
    """Serializer for geocode response"""
    message = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)


class ErrorResponseSerializer(serializers.Serializer):
    """Serializer for error responses"""
    error = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    details = serializers.DictField(required=False, read_only=True)