from rest_framework import serializers

class DownloadRequestSerializer(serializers.Serializer):
    url = serializers.URLField()
    media_type = serializers.ChoiceField(choices=['video', 'audio'])
