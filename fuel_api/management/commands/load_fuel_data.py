from django.core.management.base import BaseCommand
from fuel_api.models import FuelStation


class Command(BaseCommand):
    help = 'Load fuel station data from CSV file'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Loading fuel station data...'))
        
        count = FuelStation.load_from_csv()
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully loaded {count} fuel stations')
        )
        
        # Try to geocode some stations
        self.stdout.write('Geocoding sample stations...')
        geocoded = FuelStation.geocode_stations()
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully geocoded {geocoded} stations')
        )
