from rest_framework import serializers
from .models import Trip, RouteStop, DailyLog

class RouteStopSerializer(serializers.ModelSerializer):
    class Meta:
        model = RouteStop
        fields = ['stop_type', 'name', 'latitude', 'longitude', 'order']

class DailyLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyLog
        fields = ['day_number', 'date', 'log_entries']

class TripSerializer(serializers.ModelSerializer):
    stops = RouteStopSerializer(many=True, read_only=True)
    logs = DailyLogSerializer(many=True, read_only=True)

    class Meta:
        model = Trip
        fields = [
            'id',
            'current_location',
            'pickup_location',
            'dropoff_location',
            'current_cycle_used',
            'total_miles',
            'total_days',
            'stops',
            'logs',
            'created_at',
        ]
