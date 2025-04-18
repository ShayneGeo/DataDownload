import yt_dlp
import os

def download_youtube_as_mp3(urls):
    ffmpeg_folder = r"C:\Users\magst\Desktop\YOUTUBETOMP3\STUFF\ffmpeg-2025-04-14-git-3b2a9410ef-essentials_build\bin"
    os.environ["PATH"] += os.pathsep + ffmpeg_folder

    print("ffmpeg.exe in PATH?", os.path.isfile(os.path.join(ffmpeg_folder, "ffmpeg.exe")))
    print("ffprobe.exe in PATH?", os.path.isfile(os.path.join(ffmpeg_folder, "ffprobe.exe")))

    ydl_opts = {
        'format': 'bestaudio/best',
        'ffmpeg_location': ffmpeg_folder,
        'outtmpl': r'C:\Users\magst\Desktop\YOUTUBETOMP3\SONGS\%(title)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for url in urls:
            try:
                ydl.download([url])
            except Exception as e:
                print(f"Failed to download {url}: {e}")

# List of YouTube video URLs
video_urls = [
    "https://www.youtube.com/watch?v=v8hBfdqwoh0",
    "https://www.youtube.com/watch?v=dUYghJd1zp4&list=PL-jxOp0oAuWv7MPdFjsZYbpW_pYYzC62b",
    "https://www.youtube.com/watch?v=ZCNKLYsz1zI&list=PL-jxOp0oAuWv7MPdFjsZYbpW_pYYzC62b&index=2",
    "https://www.youtube.com/watch?v=LEb4vS160Sw&list=PL-jxOp0oAuWv7MPdFjsZYbpW_pYYzC62b&index=3",
    "https://www.youtube.com/watch?v=8XVSJKh0TMk&list=PL-jxOp0oAuWv7MPdFjsZYbpW_pYYzC62b&index=5",
    "https://www.youtube.com/watch?v=RLqo708UjTw&list=PL-jxOp0oAuWv7MPdFjsZYbpW_pYYzC62b&index=6",
    "https://www.youtube.com/watch?v=q0jWUzXolrc&list=PL-jxOp0oAuWv7MPdFjsZYbpW_pYYzC62b&index=15",
    "https://www.youtube.com/watch?v=PERH69riQHc&list=PL-jxOp0oAuWv7MPdFjsZYbpW_pYYzC62b&index=17",
    "https://www.youtube.com/watch?v=sR5M5eGujRM&list=PL-jxOp0oAuWv7MPdFjsZYbpW_pYYzC62b&index=25",
    "https://www.youtube.com/watch?v=kuggtL-bQzc&list=PL-jxOp0oAuWv7MPdFjsZYbpW_pYYzC62b&index=53",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",


]

download_youtube_as_mp3(video_urls)
