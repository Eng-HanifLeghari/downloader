import os
import glob
import time
import json
import uuid
import random
import mimetypes

from django.conf import settings
from django.http import JsonResponse, FileResponse, HttpResponseNotAllowed
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

import yt_dlp

# In-memory task state
active_downloads = {}
download_history = {}

# ----------------------------
# Cleanup partial files
def cleanup_partial_files():
    downloads_dir = os.path.join(settings.BASE_DIR, 'downloads')
    if os.path.exists(downloads_dir):
        part_files = glob.glob(os.path.join(downloads_dir, '*.part'))
        for f in part_files:
            try:
                os.remove(f)
            except Exception as e:
                print(f"Failed to remove {f}: {e}")

# ----------------------------
# Utility functions
def extract_domain_from_url(url):
    if 'youtube.com' in url or 'youtu.be' in url:
        return 'youtube'
    elif 'tiktok.com' in url:
        return 'twitter'
    elif 'instagram.com' in url:
        return 'instagram'
    elif 'facebook.com' in url:
        return 'facebook'
    return 'other'

def get_referer(url):
    if 'youtube' in url:
        return 'https://www.youtube.com/'
    if 'tiktok' in url:
        return 'https://www.tiktok.com/'
    if 'twitter' in url or 'x.com' in url:
        return 'https://x.com/'
    if 'instagram' in url:
        return 'https://www.instagram.com/'
    if 'facebook' in url:
        return 'https://www.facebook.com/'
    return None

def get_headers(user_agent):
    return {
        'User-Agent': user_agent,
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive',
    }

# ----------------------------
# Download video sync (no asyncio)
def _sync_download_video(url, download_type, task_id):
    try:
        downloads_dir = os.path.join(settings.BASE_DIR, 'downloads')
        os.makedirs(downloads_dir, exist_ok=True)

        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36'
        ]
        ua = random.choice(user_agents)

        options = {
            'outtmpl': os.path.join(downloads_dir, f'{task_id}.%(ext)s'),
            'noplaylist': True,
            'quiet': False,
            'user_agent': ua,
            'referer': get_referer(url),
            'headers': get_headers(ua),
            'merge_output_format': 'mp4',
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best[height<=720]/best',
            'retries': 3,
            'timeout': 60,
            'no_warnings': True,
        }

        if download_type == 'audio':
            options.update({
                'format': 'bestaudio/best',
                'extractaudio': True,
                'audioformat': 'mp3',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'merge_output_format': None,
            })

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)

            # Handle merged file path
            if download_type == 'video':
                file_path = os.path.splitext(file_path)[0] + '.mp4'

            if not os.path.exists(file_path):
                return {'status': 'error', 'error': 'Download finished but file not found.'}

            return {
                'status': 'success',
                'file_path': file_path,
                'title': info.get('title', 'Unknown Title'),
                'ext': os.path.splitext(file_path)[1][1:]  # e.g., 'mp4'
            }

    except yt_dlp.utils.DownloadError as e:
        return {'status': 'error', 'error': f"Video download failed: {str(e)}"}
    except Exception as e:
        return {'status': 'error', 'error': f"Unexpected error: {str(e)}"}

# ----------------------------
# Views

@csrf_exempt
def start_download(request):
    if request.method == 'GET':
        cleanup_partial_files()
        return render(request, 'home.html')

    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    try:
        data = json.loads(request.body.decode('utf-8'))
        url = data.get('url')
        media_type = data.get('media_type')
    except Exception as e:
        return JsonResponse({'message': f'Invalid JSON payload: {e}'}, status=400)

    if not url or not media_type:
        return JsonResponse({'message': 'Missing URL or media_type in request.'}, status=400)

    domain = extract_domain_from_url(url)
    current_time = time.time()

    # Simple rate limiting (5 per domain in 5 minutes)
    download_history.setdefault(domain, []).append(current_time)
    download_history[domain] = [t for t in download_history[domain] if current_time - t < 300]
    if len(download_history[domain]) >= 5:
        return JsonResponse({'message': 'Rate limit exceeded. Try again later.'}, status=429)

    task_id = str(uuid.uuid4())

    # SYNC DOWNLOAD (no asyncio)
    result = _sync_download_video(url, media_type, task_id)

    active_downloads[task_id] = {
        'domain': domain,
        'start_time': current_time,
        'status': result.get('status'),
        'result': result,
        'media_type': media_type,
    }

    if result.get('status') == 'success':
        download_url = request.build_absolute_uri(reverse('download_file', args=[task_id]))
        return JsonResponse({
            'status': 'success',
            'task_id': task_id,
            'download_url': download_url,
            'title': result.get('title'),
            'ext': result.get('ext')
        })
    else:
        return JsonResponse({'status': 'error', 'error': result.get('error')}, status=400)

@csrf_exempt
def download_file(request, task_id):
    task = active_downloads.get(task_id)
    if not task:
        return JsonResponse({'message': 'Download task not found.'}, status=404)
    if task['status'] != 'success':
        return JsonResponse({'message': 'Download not ready or failed.'}, status=400)

    file_path = task['result'].get('file_path')
    print("file_path", file_path)
    if not file_path or not os.path.exists(file_path):
        return JsonResponse({'message': 'File not found.'}, status=404)

    try:
        file_ext = task['result'].get('ext')
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = 'application/octet-stream'

        with open(file_path, 'rb') as f:
            response = FileResponse(open(file_path, 'rb'), as_attachment=True)
            filename = os.path.basename(file_path)
            response['Content-Disposition'] = f'inline; filename="{filename}"'
            response['X-Content-Type-Options'] = 'nosniff'

        # Optional cleanup
        try:
            os.remove(file_path)
            active_downloads.pop(task_id, None)
        except Exception as e:
            print(f"Failed to delete file: {e}")

        return response

    except Exception as e:
        return JsonResponse({'message': f'Error serving file: {str(e)}'}, status=500)

def index(request):
    return render(request, 'home.html')
