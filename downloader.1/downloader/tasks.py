from celery import shared_task
import yt_dlp
import os

from django.conf import settings


@shared_task
def download_video_task(url, download_type):
    try:
        print(f"Received in Celery: URL={url}, Type={download_type}")
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',
            'outtmpl': os.path.join(settings.BASE_DIR, 'downloads', '%(id)s.%(ext)s'),
            'quiet': True,
            'noplaylist': True,
            'geo_bypass': True,
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4'
            }],
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)

            formats = info.get("formats", [])
            best_format = max(formats, key=lambda f: f.get('height') or 0) if formats else {}

            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                return {
                    'status': 'success',
                    'file_path': file_path,
                    'title': info.get("title"),
                    'video_url': best_format.get("url") if best_format else info.get("url"),
                    'thumbnail': info.get('thumbnail'),
                    'duration': info.get('duration'),
                    'uploader': info.get('uploader'),
                }
            else:
                return {'status': 'error', 'error': 'File was empty or not found'}


    except Exception as e:
        return {'status': 'error', 'error': str(e)}
