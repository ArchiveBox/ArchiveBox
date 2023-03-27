from rest_framework import serializers

class CSVSerializer(serializers.Serializer):
    csv_file = serializers.FileField()