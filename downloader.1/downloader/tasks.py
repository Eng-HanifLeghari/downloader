from celery import shared_task
import yt_dlp
import os
import glob
import time
import random

from django.conf import settings

# Global rate limiting
last_download_time = {}
download_count = {}

@shared_task
def download_video_task(url, download_type):
    try:
        print(f"Received in Celery: URL={url}, Type={download_type}")
        
        # Rate limiting: Wait between downloads from same domain
        domain = extract_domain(url)
        current_time = time.time()
        
        if domain in last_download_time:
            time_since_last = current_time - last_download_time[domain]
            if time_since_last < 10:  # Wait at least 10 seconds between downloads from same domain
                wait_time = 10 - time_since_last + random.uniform(1, 3)  # Add random delay
                print(f"Rate limiting: waiting {wait_time:.1f} seconds for {domain}")
                time.sleep(wait_time)
        
        # Track download count per domain
        if domain not in download_count:
            download_count[domain] = 0
        download_count[domain] += 1
        last_download_time[domain] = time.time()
        
        # Reset count every hour (simple reset)
        if download_count[domain] > 20:  # Reset after 20 downloads
            print(f"Resetting download count for {domain}")
            download_count[domain] = 0
            time.sleep(random.uniform(5, 15))  # Longer wait after reset
        
        # Create downloads directory if it doesn't exist
        downloads_dir = os.path.join(settings.BASE_DIR, 'downloads')
        os.makedirs(downloads_dir, exist_ok=True)
        
        # Enhanced user agents rotation
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/121.0'
        ]
        
        selected_ua = random.choice(user_agents)
        
        # Configure options based on download type
        if download_type == 'audio':
            ydl_opts = {
                'format': 'bestaudio[ext=m4a]/bestaudio/best',
                'outtmpl': os.path.join(downloads_dir, '%(title)s.%(ext)s'),
                'quiet': False,
                'noplaylist': True,
                'geo_bypass': True,
                'socket_timeout': 45,  # Increased timeout
                'fragment_retries': 5,  # More retries
                'retries': 5,
                'retry_sleep': 2,  # Sleep between retries
                'user_agent': selected_ua,
                'referer': get_referer(url),
                'sleep_interval': random.uniform(1, 3),  # Random sleep between fragments
                'max_sleep_interval': 5,
                'headers': get_headers(selected_ua),
                'http_chunk_size': 1048576,  # 1MB chunks to be less aggressive
            }
        else:  # video download
            ydl_opts = {
                'format': 'best[height<=720]/best',
                'outtmpl': os.path.join(downloads_dir, '%(title)s.%(ext)s'),
                'quiet': False,
                'noplaylist': True,
                'geo_bypass': True,
                'merge_output_format': 'mp4',
                'socket_timeout': 45,  # Increased timeout
                'fragment_retries': 5,  # More retries
                'retries': 5,
                'retry_sleep': 2,  # Sleep between retries
                'user_agent': selected_ua,
                'referer': get_referer(url),
                'sleep_interval': random.uniform(1, 3),  # Random sleep between fragments
                'max_sleep_interval': 5,
                'headers': get_headers(selected_ua),
                'http_chunk_size': 1048576,  # 1MB chunks to be less aggressive
                'extractor_args': {
                    'tiktok': {
                        'webpage_url_extractor': True
                    },
                    'twitter': {
                        'api': 'syndication'  # Use syndication API for Twitter
                    }
                }
            }

        # Add random delay before starting download
        initial_delay = random.uniform(0.5, 2.0)
        time.sleep(initial_delay)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            
            # For audio downloads, check for mp3 file
            if download_type == 'audio':
                base_path = os.path.splitext(file_path)[0]
                mp3_path = base_path + '.mp3'
                if os.path.exists(mp3_path):
                    file_path = mp3_path

            # Check if file exists and is not empty
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                return {
                    'status': 'success',
                    'file_path': file_path,
                    'title': info.get("title"),
                    'thumbnail': info.get('thumbnail'),
                    'duration': info.get('duration'),
                    'uploader': info.get('uploader'),
                }
            else:
                # Try to find any downloaded file in the directory (excluding .part files)
                video_id = info.get('id', '')
                title_words = info.get('title', '').replace(' ', '_').split('_')[:3]
                
                for filename in os.listdir(downloads_dir):
                    # Skip partial files
                    if filename.endswith('.part'):
                        continue
                        
                    file_path_candidate = os.path.join(downloads_dir, filename)
                    
                    # Check if this file matches our download
                    if (video_id and video_id in filename) or \
                       any(word in filename for word in title_words if len(word) > 2):
                        if os.path.getsize(file_path_candidate) > 0:
                            return {
                                'status': 'success',
                                'file_path': file_path_candidate,
                                'title': info.get("title"),
                                'thumbnail': info.get('thumbnail'),
                                'duration': info.get('duration'),
                                'uploader': info.get('uploader'),
                            }
                
                # Clean up any partial files for this download
                title_clean = info.get('title', '').replace(' ', '_')
                part_pattern = os.path.join(downloads_dir, f"*{title_clean}*.part")
                for part_file in glob.glob(part_pattern):
                    try:
                        os.remove(part_file)
                        print(f"Cleaned up partial file: {part_file}")
                    except:
                        pass
                
                return {'status': 'error', 'error': 'Download failed or file was not created properly'}

    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        if 'HTTP Error 429' in error_msg or 'rate limit' in error_msg.lower():
            return {'status': 'error', 'error': 'Rate limited. Please wait a few minutes before trying again.'}
        elif 'HTTP Error 403' in error_msg or 'blocked' in error_msg.lower():
            return {'status': 'error', 'error': 'Access blocked. Try again later or use a different video.'}
        else:
            return {'status': 'error', 'error': f'Download error: {error_msg}'}
    except Exception as e:
        print(f"Error in download_video_task: {str(e)}")
        return {'status': 'error', 'error': str(e)}

def extract_domain(url):
    """Extract domain from URL for rate limiting"""
    try:
        if 'youtube.com' in url or 'youtu.be' in url:
            return 'youtube'
        elif 'tiktok.com' in url:
            return 'tiktok'
        elif 'twitter.com' in url or 'x.com' in url:
            return 'twitter'
        elif 'instagram.com' in url:
            return 'instagram'
        else:
            # Extract general domain
            from urllib.parse import urlparse
            return urlparse(url).netloc
    except:
        return 'unknown'

def get_referer(url):
    """Get appropriate referer based on URL"""
    if 'youtube.com' in url or 'youtu.be' in url:
        return 'https://www.youtube.com/'
    elif 'tiktok.com' in url:
        return 'https://www.tiktok.com/'
    elif 'twitter.com' in url or 'x.com' in url:
        return 'https://x.com/'
    elif 'instagram.com' in url:
        return 'https://www.instagram.com/'
    else:
        return None

def get_headers(user_agent):
    """Generate realistic headers"""
    return {
        'User-Agent': user_agent,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Cache-Control': 'max-age=0'
    }
