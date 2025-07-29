import requests
import datetime
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Trip, RouteStop, DailyLog
from .serializers import TripSerializer

ORS_API_KEY = settings.ORS_API_KEY
STATUS_Y_POSITIONS = {
    "OffDuty": 0,
    "Sleeper": 1,
    "Driving": 2,
    "OnDuty": 3
}

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
        """
        Generate daily log entries for a trip based on HOS rules:
        - 11hr driving/day
        - 10hr sleeper/rest per day
        - 1hr on-duty for pickup/dropoff (first day only)
        - 70hr/8day cycle
        - Each log entry: {start, end, status, y_position}
        """
        driving_hours_total = distance_miles / 50  # 50 mph avg
        available_hours = max(0, 70 - cycle_used)  # Remaining HOS in cycle
        total_hours_needed = driving_hours_total + (1 if driving_hours_total > 0 else 0)  # Driving + pickup/drop duty

        if available_hours <= 1:
            return []  # No usable hours left in the cycle
        
        if total_hours_needed > available_hours:
            driving_hours_total = max(0, available_hours - 1)  # Deduct 1hr for on-duty
            
        days = []
        first_day = True

        while driving_hours_total > 0:
            entries = []
            current_time = 0
            # 1hr on-duty for pickup/dropoff only on first day
            on_duty = 1 if first_day else 0
            if on_duty:
                entries.append({
                    "start": current_time,
                    "end": current_time + on_duty,
                    "status": "OnDuty",
                    "y_position": STATUS_Y_POSITIONS["OnDuty"]
                })
                current_time += on_duty
            driving = round(min(11, driving_hours_total), 2)
            if driving > 0:
                entries.append({
                    "start": current_time,
                    "end": current_time + driving,
                    "status": "Driving",
                    "y_position": STATUS_Y_POSITIONS["Driving"]
                })
                current_time += driving
            # OffDuty is whatever is left after 10hr sleeper, driving, and on_duty
            off_duty = max(0, 24 - (10 + driving + on_duty))
            if off_duty > 0:
                entries.append({
                    "start": current_time,
                    "end": current_time + off_duty,
                    "status": "OffDuty",
                    "y_position": STATUS_Y_POSITIONS["OffDuty"]
                })
                current_time += off_duty
            # 10hr sleeper at end of day
            entries.append({
                "start": current_time,
                "end": 24,
                "status": "Sleeper",
                "y_position": STATUS_Y_POSITIONS["Sleeper"]
            })
            days.append(entries)
            driving_hours_total -= driving
            first_day = False
        return days

