import requests
import datetime
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Trip, RouteStop, DailyLog
from .serializers import TripSerializer

ORS_API_KEY = settings.ORS_API_KEY

class TripPlannerView(APIView):
    def post(self, request):
        data = request.data
        current_location = data.get('current_location')
        pickup_location = data.get('pickup_location')
        dropoff_location = data.get('dropoff_location')
        current_cycle_used = float(data.get('current_cycle_used', 0))

        # Validate inputs
        if not all([current_location, pickup_location, dropoff_location]):
            return Response({"error": "All locations are required."}, status=status.HTTP_400_BAD_REQUEST)
        if current_cycle_used < 0 or current_cycle_used > 70:
            return Response({"error": "Current cycle used must be between 0 and 70."}, status=status.HTTP_400_BAD_REQUEST)

        # Step 1: Geocode & Get route
        try:
            coords = self._geocode_locations([current_location, pickup_location, dropoff_location])
            route_url = "https://api.openrouteservice.org/v2/directions/driving-hgv"
            body = {"coordinates": coords}
            headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}
            route_resp = requests.post(route_url, json=body, headers=headers).json()
            distance_km = route_resp['routes'][0]['summary']['distance'] / 1000
            distance_miles = round(distance_km * 0.621371, 2)
        except Exception as e:
            return Response({"error": "Failed to fetch route."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Step 2: Calculate stops
        stops = self._calculate_stops(coords, distance_miles)

        # Step 3: Generate ELD logs
        logs = self._generate_daily_logs(distance_miles, current_cycle_used)

        # Step 4: Save trip
        trip = Trip.objects.create(
            current_location=current_location,
            pickup_location=pickup_location,
            dropoff_location=dropoff_location,
            current_cycle_used=current_cycle_used,
            total_miles=distance_miles,
            total_days=len(logs)
        )

        # Save stops
        for idx, stop in enumerate(stops):
            RouteStop.objects.create(
                trip=trip,
                stop_type=stop['type'],
                name=stop['name'],
                latitude=stop['lat'],
                longitude=stop['lng'],
                order=idx
            )

        # Save daily logs
        for idx, day in enumerate(logs):
            DailyLog.objects.create(
                trip=trip,
                day_number=idx + 1,
                date=datetime.date.today() + datetime.timedelta(days=idx),
                log_entries=day
            )

        serializer = TripSerializer(trip)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def _geocode_locations(self, locations):
        """Convert addresses to [lng, lat] using ORS geocoding"""
        coords = []
        for loc in locations:
            url = f"https://api.openrouteservice.org/geocode/search?api_key={ORS_API_KEY}&text={loc}"
            resp = requests.get(url).json()
            coords.append(resp['features'][0]['geometry']['coordinates'])
        return coords

    def _calculate_stops(self, coords, distance_miles):
        """Add pickup, dropoff, fuel stops every 1000 miles"""
        stops = [
            {"type": "pickup", "name": "Pickup Location", "lat": coords[1][1], "lng": coords[1][0]},
            {"type": "dropoff", "name": "Dropoff Location", "lat": coords[2][1], "lng": coords[2][0]},
        ]
        num_fuel_stops = int(distance_miles // 1000)
        for i in range(num_fuel_stops):
            stops.append({
                "type": "fuel",
                "name": f"Fuel Stop {i+1}",
                "lat": coords[1][1],
                "lng": coords[1][0]
            })
        return stops

    def _generate_daily_logs(self, distance_miles, cycle_used):
        """Generate logs with HOS: 11hr driving/day, 10hr rest, 1hr pickup/drop"""
        driving_hours_total = distance_miles / 50  # 50 mph avg
        days = []
        while driving_hours_total > 0:
            day_hours = []
            on_duty = 1 if len(days) == 0 or driving_hours_total <= 11 else 0
            driving = min(11, driving_hours_total)
            off_duty = 24 - (driving + on_duty + 10)
            day_hours.append({"start": 0, "end": on_duty, "status": "OnDuty"})
            day_hours.append({"start": on_duty, "end": on_duty + driving, "status": "Driving"})
            day_hours.append({"start": on_duty + driving, "end": 24 - 10, "status": "OffDuty"})
            day_hours.append({"start": 24 - 10, "end": 24, "status": "Sleeper"})
            days.append(day_hours)
            driving_hours_total -= driving
        return days
