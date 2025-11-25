# from django.urls import path
# from . import views

# urlpatterns = [
#     path('health/', views.health_check, name='health_check'),
#     path('load-fuel-data/', views.load_fuel_data, name='load_fuel_data'),
#     path('geocode-stations/', views.geocode_stations, name='geocode_stations'),
#     path('optimize-route/', views.optimize_route, name='optimize_route'),
#     path('cheapest-stations/', views.get_cheapest_stations, name='cheapest_stations'),
# ]

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# Create router and register viewsets
router = DefaultRouter()
router.register(r'fuel-stations', views.FuelStationViewSet, basename='fuel-station')

urlpatterns = [
    # Include router URLs
    path('', include(router.urls)),
    
    # Alternative direct paths for backward compatibility (optional)
    path('health/', views.FuelStationViewSet.as_view({'get': 'health_check'}), name='health_check'),
    path('load-fuel-data/', views.FuelStationViewSet.as_view({'post': 'load_fuel_data'}), name='load_fuel_data'),
    path('geocode-stations/', views.FuelStationViewSet.as_view({'post': 'geocode_stations'}), name='geocode_stations'),
    path('optimize-route/', views.FuelStationViewSet.as_view({'post': 'optimize_route'}), name='optimize_route'),
    path('cheapest-stations/', views.FuelStationViewSet.as_view({'get': 'cheapest_stations'}), name='cheapest_stations'),
]