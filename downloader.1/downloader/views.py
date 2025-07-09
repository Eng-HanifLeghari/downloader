import os
import glob
import time
import json
import uuid
import random
import asyncio
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
        return 'tiktok'
    elif 'twitter.com' in url or 'x.com' in url:
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
# Download Worker
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
            'verbose': True,
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
                'outtmpl': os.path.join(downloads_dir, f'{task_id}.%(ext)s'),
                'merge_output_format': None,
            })

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            if not os.path.exists(file_path):
                print(f"yt-dlp finished but file not found at {file_path}. Info: {info}")
                return {'status': 'error', 'error': 'Download process completed but no file was generated.'}
            return {
                'status': 'success',
                'file_path': file_path,
                'title': info.get('title', 'Unknown Title'),
                'ext': info.get('ext', 'mp4')
            }
    except yt_dlp.utils.DownloadError as e:
        print(f"yt-dlp Download Error: {e}")
        return {'status': 'error', 'error': f"Video download failed: {str(e)}"}
    except Exception as e:
        print(f"General download error: {e}")
        return {'status': 'error', 'error': f"An unexpected error occurred: {str(e)}"}

# ----------------------------
# Views

@csrf_exempt
async def start_download(request):
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

    # Rate limiting
    download_history.setdefault(domain, []).append(current_time)
    download_history[domain] = [t for t in download_history[domain] if current_time - t < 300]
    if len(download_history[domain]) >= 5:
        return JsonResponse(
            {'message': 'Rate limit exceeded for this domain. Please wait a few minutes before trying again.'},
            status=429)

    task_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    task_future = loop.create_task(asyncio.to_thread(_sync_download_video, url, media_type, task_id))

    active_downloads[task_id] = {
        'domain': domain,
        'start_time': current_time,
        'future': task_future,
        'status': 'pending',
        'result': None,
        'media_type': media_type,
    }

    download_url = request.build_absolute_uri(reverse('download_file', args=[task_id]))
    return JsonResponse({'task_id': task_id, 'download_url': download_url})

@csrf_exempt
async def check_status(request, task_id):
    task = active_downloads.get(task_id)
    if not task:
        return JsonResponse({'status': 'not_found', 'error': 'Task not found or has expired.'}, status=404)
    future = task['future']
    if future.done():
        try:
            result = await future
            task['result'] = result
            task['status'] = result.get('status')
            if result.get('status') == 'success':
                return JsonResponse({'status': 'success'})
            else:
                return JsonResponse({'status': 'failed', 'error': result.get('error', 'Download failed.')})
        except Exception as e:
            task['status'] = 'failed'
            print(f"Error retrieving task result for {task_id}: {e}")
            return JsonResponse({'status': 'failed', 'error': f"Internal server error checking status: {str(e)}"})
    else:
        return JsonResponse({'status': 'pending'})

@csrf_exempt
async def download_file(request, task_id):
    task = active_downloads.get(task_id)
    if not task:
        return JsonResponse({'message': 'Download task not found or has been cleaned up.'}, status=404)
    if task['status'] != 'success':
        return JsonResponse({'message': 'Download not ready yet or failed. Please check status first.'}, status=400)
    file_path = task['result'].get('file_path')
    if not file_path or not os.path.exists(file_path):
        return JsonResponse({'message': 'File missing on server. It might have been deleted already.'}, status=404)
    try:
        file_ext = task['result'].get('ext') or os.path.splitext(file_path)[1][1:]
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type or not (mime_type.startswith('video/') or mime_type.startswith('audio/')):
            if file_ext == 'mp4':
                mime_type = 'video/mp4'
            elif file_ext == 'webm':
                mime_type = 'video/webm'
            elif file_ext == 'ogg':
                mime_type = 'video/ogg'
            elif file_ext == 'mp3':
                mime_type = 'audio/mpeg'
            elif file_ext == 'm4a':
                mime_type = 'audio/mp4'
            else:
                print(f"Warning: Could not determine specific MIME type for {file_path}. Using application/octet-stream.")
                mime_type = 'application/octet-stream'
        with open(file_path, 'rb') as f:
            response = FileResponse(f, content_type=mime_type)
            filename = os.path.basename(file_path)
            response['Content-Disposition'] = f'inline; filename="{filename}"'
            response['X-Content-Type-Options'] = 'nosniff'
        async def cleanup_after_response():
            await asyncio.sleep(2)
            try:
                os.remove(file_path)
                print(f"Successfully deleted: {file_path}")
            except Exception as e:
                print(f"Failed to delete {file_path}: {e}")
            finally:
                active_downloads.pop(task_id, None)
        asyncio.create_task(cleanup_after_response())
        return response
    except FileNotFoundError:
        return JsonResponse({'message': 'File not found on server (check file path or race condition).'}, status=404)
    except Exception as e:
        print(f"Error in download_file view: {e}")
        return JsonResponse({'message': f'Server error processing file: {str(e)}'}, status=500)

def index(request):
    return render(request, 'home.html')