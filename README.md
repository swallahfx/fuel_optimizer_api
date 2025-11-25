# Fuel Optimizer API Documentation (Docker)

## Overview
The Fuel Optimizer API calculates optimal fuel stops along a route between two US locations, considering fuel prices and vehicle constraints. The application runs in a containerized environment using Docker with Redis caching for optimal performance.

## Vehicle Assumptions
- Maximum range: 500 miles per tank
- Fuel efficiency: 10 miles per gallon
- Tank capacity: 50 gallons

## Docker Setup and Installation

### Prerequisites
- Docker and Docker Compose installed
- At least 2GB RAM available for containers

### Quick Start

1. **Clone and navigate to project:**
```bash
git clone <your-repo>
cd fuel-optimizer-api
```

2. **Create environment file:**
```bash
cp .env.example .env
```

3. **Configure environment variables in `.env`:**
```env
# Django settings
DEBUG=True
SECRET_KEY=your-super-secret-key-change-this-in-production
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0

# Database
DATABASE_URL=postgresql://fuel_user:fuel_pass@db:5432/fuel_optimizer

# Redis Cache
REDIS_URL=redis://redis:6379/0
```

4. **Build and start services:**
```bash
# Build and start all services
docker-compose up --build

# View logs
docker-compose logs -f web

# Check service status
docker-compose ps
```

5. **Initialize database:**
```bash
# Run migrations
docker-compose exec web python manage.py migrate

# Load fuel station data
docker-compose exec web python manage.py load_fuel_data

# Create superuser (optional)
docker-compose exec web python manage.py createsuperuser
```

## API Endpoints

### 1. Health Check
**GET** `/api/health/`

Returns API status and fuel station count.

**Response:**
```json
{
    "status": "healthy",
    "timestamp": 1700000000.0,
    "fuel_stations_count": 6738
}
```

#### Swagger Docuemtation at:
**GET** `/api/docs/`
**Interactive Documentation UI for the APIs**

### 2. Route Optimization (Main Endpoint)
**POST** `/api/fuel-stations/optimize_route/`

Calculate optimal route with fuel stops. **Features Redis caching** for identical requests.

**Request:**
```json
{
    "start_location": "New York, NY",
    "end_location": "Los Angeles, CA"
}
```

**Response:**
```json
{
    "start_coordinates": [40.7128, -74.0060],
    "end_coordinates": [34.0522, -118.2437],
    "total_distance_miles": 2445.7,
    "estimated_drive_time": "36h 15m",
    "fuel_stops": [
        {
            "opis_id": 12345,
            "name": "PILOT TRAVEL CENTER #123",
            "address": "I-80, EXIT 126",
            "city": "Council Bluffs",
            "state": "IA",
            "retail_price": 3.199,
            "latitude": 41.2619,
            "longitude": -95.8608,
            "gallons": 50.0,
            "cost_at_station": 159.95
        }
    ],
    "fuel_cost_summary": {
        "total_cost": 623.80,
        "total_gallons": 244.6,
        "average_price": 3.251,
        "stops_count": 4
    },
    "map_html": "http://localhost:8000/tmp/route_map_20251125_114236.html",
    "route_coordinates": "http://localhost:8000/tmp/route_coords_20251125_114236.json"
}
```

### 3. Cheapest Stations (Testing Endpoint)
**GET** `/api/cheapest-stations/?limit=10&state=TX`

Get cheapest fuel stations for testing purposes.

**Parameters:**
- `limit` (optional): Number of stations to return (default: 10)
- `state` (optional): Filter by state code (e.g., TX, CA)

## Architecture

```
┌─────────────────┐    ┌──────────────┐    ┌─────────────────┐
│   Client App    │────│ Nginx (Prod) │────│  Load Balancer  │
│  (Web/Mobile)   │    │   Reverse    │    │   (Optional)    │
└─────────────────┘    │    Proxy     │    └─────────────────┘
                       └──────────────┘             │
                               │                    │
                               ▼                    ▼
                    ┌──────────────────────────────────────┐
                    │         Docker Network               │
                    │                                      │
                    │  ┌──────────────┐ ┌─────────────────┐│
                    │  │ Django Web   │ │   PostgreSQL    ││
                    │  │  Container   │ │   Database      ││
                    │  │   (3 proc)   │ │   Container     ││
                    │  └──────────────┘ └─────────────────┘│
                    │         │                            │
                    │         ▼                            │
                    │  ┌──────────────┐                    │
                    │  │    Redis     │                    │
                    │  │    Cache     │                    │
                    │  │  Container   │                    │
                    │  └──────────────┘                    │
                    └──────────────────────────────────────┘
                               │
                               ▼
                    ┌──────────────────┐
                    │  External APIs   │
                    │ - OSRM Routing   │
                    │ - Nominatim Geo  │
                    └──────────────────┘
```

## Error Handling

The API returns appropriate HTTP status codes:
- `200`: Success (cached or computed)
- `400`: Invalid request (bad location names, validation errors)
- `500`: Internal server error (routing failures, database errors)

Error responses include descriptive messages:
```json
{
    "error": "Unable to geocode one or both locations. Please check the location names.",
    "status": "error"
}
```

## Rate Limits

Current implementation uses free APIs with reasonable defaults:
- **OSRM routing**: No strict limits for reasonable usage
- **Nominatim geocoding**: 1 request/second limit
- **Redis caching**: Eliminates repeated API calls

This documentation provides a complete guide for running the Fuel Optimizer API in a Docker environment with proper caching, monitoring, and production deployment strategies.
