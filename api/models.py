from django.db import models


class Trip(models.Model):
    current_location = models.CharField(max_length=255)
    pickup_location = models.CharField(max_length=255)
    dropoff_location = models.CharField(max_length=255)
    current_cycle_used = models.FloatField(help_text="Hours already used in 70hr/8day cycle")
    total_miles = models.FloatField(null=True, blank=True)
    total_days = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Trip: {self.pickup_location} → {self.dropoff_location}"


class RouteStop(models.Model):
    trip = models.ForeignKey(Trip, related_name="stops", on_delete=models.CASCADE)
    stop_type = models.CharField(max_length=50, choices=(
        ("pickup", "Pickup"),
        ("dropoff", "Dropoff"),
        ("fuel", "Fuel Stop"),
        ("rest", "Rest Stop"),
    ))
    name = models.CharField(max_length=255)
    latitude = models.FloatField()
    longitude = models.FloatField()
    order = models.IntegerField()

    def __str__(self):
        return f"{self.stop_type} - {self.name}"


class DailyLog(models.Model):
    trip = models.ForeignKey(Trip, related_name="logs", on_delete=models.CASCADE)
    day_number = models.IntegerField()
    date = models.DateField()
    log_entries = models.JSONField()

    def __str__(self):
        return f"Log Day {self.day_number} for Trip {self.trip.id}"
