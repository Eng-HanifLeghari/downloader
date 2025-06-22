# from django.shortcuts import render
# from django.views.decorators.csrf import csrf_exempt
# import yt_dlp
# import json
# from django.http import FileResponse
# import os
# from rest_framework.decorators import api_view
# from rest_framework.response import Response
# from rest_framework import status
#
#
# def download_youtube_video(url: str, download_type: str):
#     try:
#         # Options for downloading video or audio
#         ydl_opts = {
#             'format': 'best' if download_type == 'video' else 'bestaudio/best',
#             'outtmpl': 'downloads/%(title)s.%(ext)s',
#             'skip_download': True if download_type == 'url' else False,
#             'quiet': True,
#             'noplaylist': True,
#             'geo_bypass': True,
#             'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
#         }
#
#         with yt_dlp.YoutubeDL(ydl_opts) as ydl:
#             # Extract video info from the URL
#             info = ydl.extract_info(url, download=download_type != 'url')
#
#             # Prepare file path for downloaded file if media_type is not 'url'
#             file_path = None
#             if download_type != 'url':
#                 file_path = ydl.prepare_filename(info)
#
#             formats = info.get("formats", [])
#             best_format = max(formats, key=lambda f: f.get('height') or 0) if formats else {}
#
#             # Return video URL, file path, and other video details
#             return {
#                 'file_path': file_path,
#                 'title': info.get("title"),
#                 'video_url': best_format.get("url") if best_format else info.get("url"),  # Direct video URL
#                 'formats': formats,
#                 'thumbnail': info.get('thumbnail'),
#                 'duration': info.get('duration'),
#                 'uploader': info.get('uploader'),
#             }
#
#     except Exception as e:
#         print(f"Error: {str(e)}")
#         return None
#
#
# @csrf_exempt
# @api_view(['POST', 'GET'])
# def download(request):
#     url = request.data.get('url')
#     media_type = request.data.get('media_type')
#
#     if not url or not media_type:
#         return Response({'message': 'Please provide a valid URL and media type'}, status=status.HTTP_400_BAD_REQUEST)
#
#     try:
#         video_info = download_youtube_video(url, media_type)
#
#         if not video_info:
#             return Response({'message': 'Processing failed'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#         # If media_type is 'url', just return the direct video URL in JSON
#         if media_type == 'url':
#             return Response({
#                 # 'title': video_info.get("title"),
#                 'video_url': video_info.get("video_url"),
#                 # 'thumbnail': video_info.get("thumbnail"),
#                 # 'duration': video_info.get("duration"),
#                 # 'uploader': video_info.get("uploader"),
#             })
#
#         # Otherwise, handle video/audio download
#         file_path = video_info.get('file_path')
#         if file_path and os.path.exists(file_path):
#             file_name = os.path.basename(file_path)
#             response = FileResponse(open(file_path, 'rb'), as_attachment=True, filename=file_name,
#                                     content_type='application/octet-stream')
#             return response
#
#         return Response({'message': 'Downloaded file not found'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#     except Exception as e:
#         return Response({'message': f'An error occurred: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#
# def index(request):
#     return render(request, 'home.html')

from django.http import FileResponse
from django.shortcuts import render
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from downloader.tasks import download_video_task
from celery.result import AsyncResult
import os

from .tasks import download_video_task
from celery.result import AsyncResult
from django.conf import settings

@api_view(['POST'])
def start_download(request):
    url = request.data.get('url')
    media_type = request.data.get('media_type')

    if not url or not media_type:
        return Response({'message': 'Missing URL or media_type'}, status=400)

    download_video_task.delay(url, media_type)
    return Response({'task_id': ''})


@api_view(['GET'])
def check_status(request, task_id):
    task = AsyncResult(task_id)

    if task.state == 'PENDING':
        return Response({'status': 'pending'})
    elif task.state == 'FAILURE':
        return Response({'status': 'failed', 'error': str(task.info)})
    elif task.state == 'SUCCESS':
        result = task.result
        if result.get('status') == 'success' and os.path.exists(result.get('file_path')):
            download_url = request.build_absolute_uri(f"/api/download/file/{task_id}/")
            return Response({'status': 'success', 'download_url': download_url})
        else:
            return Response({'status': 'error', 'error': 'Download failed or file not found'})
    else:
        return Response({'status': task.state.lower()})


@api_view(['GET'])
def download_file(request, task_id):
    task = AsyncResult(task_id)
    if not task or task.state != 'SUCCESS':
        return Response({'message': 'File not ready'}, status=400)

    result = task.result
    file_path = result.get('file_path')

    if file_path and os.path.exists(file_path):
        filename = os.path.basename(file_path)
        return FileResponse(open(file_path, 'rb'), as_attachment=True, filename=filename)
    else:
        return Response({'message': 'File not found'}, status=404)



def index(request):
    return render(request, 'home.html')