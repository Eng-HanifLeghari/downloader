from django.http import FileResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
import os
import glob
import time
from .tasks import download_video_task
from celery.result import AsyncResult
from django.conf import settings


active_downloads = {}
download_history = {}

def cleanup_partial_files():
    """Clean up any .part files in the downloads directory"""
    downloads_dir = os.path.join(settings.BASE_DIR, 'downloads')
    if os.path.exists(downloads_dir):
        part_files = glob.glob(os.path.join(downloads_dir, '*.part'))
        for part_file in part_files:
            try:
                os.remove(part_file)
                print(f"Cleaned up partial file: {part_file}")
            except Exception as e:
                print(f"Failed to remove {part_file}: {e}")

def extract_domain_from_url(url):
    """Extract domain for tracking"""
    if 'youtube.com' in url or 'youtu.be' in url:
        return 'youtube'
    elif 'tiktok.com' in url:
        return 'tiktok'
    elif 'twitter.com' in url or 'x.com' in url:
        return 'twitter'
    elif 'instagram.com' in url:
        return 'instagram'
    else:
        return 'other'

@csrf_exempt
@api_view(['POST', 'GET'])
def start_download(request):
    if request.method == 'GET':
        # Clean up any partial files before showing the page
        cleanup_partial_files()
        return render(request, 'home.html')
    
    url = request.data.get('url')
    media_type = request.data.get('media_type')

    if not url or not media_type:
        return Response({'message': 'Missing URL or media_type'}, status=400)

    # Check rate limiting
    domain = extract_domain_from_url(url)
    current_time = time.time()
    
    # Check if too many recent downloads from this domain
    if domain in download_history:
        recent_downloads = [t for t in download_history[domain] if current_time - t < 300]  # 5 minutes
        if len(recent_downloads) >= 5:  # Max 5 downloads per 5 minutes per domain
            return Response({
                'message': f'Rate limit exceeded for {domain}. Please wait a few minutes before trying again.'
            }, status=429)
    
    # Check if there's an active download from the same domain
    active_domain_downloads = [d for d in active_downloads.values() if d['domain'] == domain and current_time - d['start_time'] < 120]  # 2 minutes
    if len(active_domain_downloads) >= 2:  # Max 2 concurrent downloads per domain
        return Response({
            'message': f'Too many active downloads from {domain}. Please wait for current downloads to complete.'
        }, status=429)

    task = download_video_task.delay(url, media_type)
    
    # Track the download
    active_downloads[task.id] = {
        'domain': domain,
        'start_time': current_time,
        'url': url
    }
    
    # Add to history
    if domain not in download_history:
        download_history[domain] = []
    download_history[domain].append(current_time)
    
    # Clean old history (keep only last 24 hours)
    download_history[domain] = [t for t in download_history[domain] if current_time - t < 86400]
    
    return Response({'task_id': task.id})

@csrf_exempt
@api_view(['GET'])
def check_status(request, task_id):
    task = AsyncResult(task_id)
    
    # Clean up from active downloads if completed
    if task_id in active_downloads and task.state in ['SUCCESS', 'FAILURE']:
        del active_downloads[task_id]

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
            return Response({'status': 'error', 'error': result.get('error', 'Download failed or file not found')})
    else:
        return Response({'status': task.state.lower()})

@csrf_exempt
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