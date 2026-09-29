import ipaddress
import urllib.parse
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
import httpx

app = FastAPI(
    title="AllSavePro Media Engine",
    description="Universal video processing and chunked streaming gateway",
    version="2.0.0"
)

# Enable CORS for cross-origin requests from frontend hosts
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Authenticated NanoStream HTTP Proxy with RFC-compliant URL-encoded password
NANOSTREAM_PROXY = "http://gk:gk%28GK%29321@nanostream4x.duckdns.org:8080"


def clean_tracking_params(target_url: str) -> str:
    """Strips social media tracking parameters that can interfere with extraction."""
    try:
        parsed = urllib.parse.urlparse(target_url)
        tracking_keys = {"utm_source", "utm_medium", "utm_campaign", "fbclid", "igsh", "ref", "s"}
        qs = urllib.parse.parse_qs(parsed.query)
        clean_qs = {k: v for k, v in qs.items() if k.lower() not in tracking_keys}
        new_query = urllib.parse.urlencode(clean_qs, doseq=True)
        return urllib.parse.urlunparse(parsed._replace(query=new_query))
    except Exception:
        return target_url


def is_safe_public_url(target_url: str) -> bool:
    """
    Validates target URL against SSRF, internal network scanning,
    and metadata exploitation attempts.
    """
    try:
        parsed = urllib.parse.urlparse(target_url)
        
        if parsed.scheme not in ("http", "https"):
            return False

        hostname = parsed.hostname
        if not hostname:
            return False

        blocked_hosts = {
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "169.254.169.254",
            "nanostream4x.duckdns.org",
        }
        if hostname.lower() in blocked_hosts:
            return False

        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        except ValueError:
            pass

        return True
    except Exception:
        return False


# सीधे वेबसाइट दिखाने वाला मुख्य एंडपॉइंट (Root Home Route)
@app.get("/")
async def home_page():
    """Serves the index.html frontend directly at the root URL."""
    return FileResponse("index.html")


@app.get("/health")
def health_check():
    """Keep-alive endpoint for Render free tier monitoring."""
    return {"status": "alive"}


@app.get("/api/info")
def get_media_info(url: str = Query(..., description="Target media URL to extract")):
    """
    Extracts direct CDN media links, thumbnails, and metadata via yt-dlp
    routed through the Oracle NanoStream proxy.
    """
    if not url or len(url) < 10 or len(url) > 2048:
        raise HTTPException(
            status_code=400, 
            detail="Invalid URL length: Must be between 10 and 2048 characters."
        )

    if not is_safe_public_url(url):
        raise HTTPException(
            status_code=403, 
            detail="Access forbidden: Target address rejected by security shield."
        )

    normalized_url = url.lower()
    if "youtube.com" in normalized_url or "youtu.be" in normalized_url:
        raise HTTPException(
            status_code=403, 
            detail="Policy restriction: YouTube downloads are strictly prohibited."
        )

    sanitized_url = clean_tracking_params(url)

    # Clean, robust, and universal yt-dlp options without restrictive constraints
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': True,
        'nocheckcertificate': True,
        'proxy': NANOSTREAM_PROXY,
        'socket_timeout': 30,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(sanitized_url, download=False)

            download_url = info.get("url")
            if not download_url and info.get("formats"):
                for fmt in reversed(info["formats"]):
                    if fmt.get("url"):
                        download_url = fmt.get("url")
                        break

            if not download_url:
                raise HTTPException(
                    status_code=400, 
                    detail="Could not extract direct stream link from this source."
                )

            return {
                "success": True,
                "title": info.get("title") or "AllSavePro Media",
                "thumbnail": info.get("thumbnail") or "",
                "duration": info.get("duration") or 0,
                "download_url": download_url
            }
    except HTTPException:
        raise
    except Exception as extraction_err:
        raise HTTPException(
            status_code=400, 
            detail=f"Extraction failure: {str(extraction_err)}"
        )


@app.get("/api/stream")
async def stream_media(url: str = Query(..., description="Direct CDN media URL to pipe")):
    """
    Streams media in 64KB chunks to bypass hotlink restrictions
    while maintaining memory under 10MB on Render's 512MB RAM tier.
    """
    if not is_safe_public_url(url):
        raise HTTPException(
            status_code=403, 
            detail="Access forbidden: Invalid stream source."
        )

    async def video_chunk_generator():
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }

        stream_timeout = httpx.Timeout(None, connect=25.0)

        async with httpx.AsyncClient(
            proxy=NANOSTREAM_PROXY, 
            follow_redirects=True, 
            timeout=stream_timeout
        ) as client:
            async with client.stream("GET", url, headers=headers) as response:
                if response.status_code != 200:
                    raise HTTPException(
                        status_code=response.status_code, 
                        detail="CDN rejected media chunk stream request."
                    )
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    yield chunk

    download_headers = {
        "Content-Disposition": 'attachment; filename="AllSavePro_Video.mp4"',
        "Content-Type": "video/mp4",
    }

    return StreamingResponse(video_chunk_generator(), headers=download_headers)
