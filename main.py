import ipaddress
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
import httpx

app = FastAPI(
    title="AllSavePro Media Engine",
    description="Universal video processing and chunked streaming gateway",
    version="1.0.0"
)

# Enable CORS for cross-origin requests from frontend hosts (e.g., Vercel, Netlify)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Authenticated NanoStream HTTP Proxy hosted on Oracle Cloud
NANOSTREAM_PROXY = "http://gk:gk(GK)321@nanostream4x.duckdns.org:8080"


def is_safe_public_url(target_url: str) -> bool:
    """
    Validates target URL against SSRF, internal network scanning,
    and metadata exploitation attempts.
    """
    try:
        parsed = urlparse(target_url)
        
        # Only standard web transfer protocols are allowed
        if parsed.scheme not in ("http", "https"):
            return False

        hostname = parsed.hostname
        if not hostname:
            return False

        # Block localhost, cloud metadata services, and internal endpoints
        blocked_hosts = {
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "169.254.169.254",          # Cloud instance metadata service
            "nanostream4x.duckdns.org",   # Prevent proxy loopback targeting
        }
        if hostname.lower() in blocked_hosts:
            return False

        # If hostname is an IP literal, verify it belongs to a public space
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        except ValueError:
            # Hostname is a valid domain name (e.g., instagram.com, tiktokcdn.com)
            pass

        return True
    except Exception:
        return False


@app.get("/health")
def health_check():
    """
    Lightweight keep-alive endpoint for ping services (e.g., UptimeRobot)
    to prevent Render from idling out. Consumes near-zero resources.
    """
    return {"status": "alive"}


@app.get("/api/info")
def get_media_info(url: str = Query(..., description="Target media URL to extract")):
    """
    Extracts direct CDN media links, thumbnails, and metadata via yt-dlp
    routed through the Oracle NanoStream proxy without downloading video content.
    """
    # Strict length constraints to mitigate buffer overflow & malformed payload attacks
    if not url or len(url) < 15 or len(url) > 450:
        raise HTTPException(
            status_code=400, 
            detail="Invalid URL length: Must be between 15 and 450 characters."
        )

    # Validate against internal network SSRF attempts
    if not is_safe_public_url(url):
        raise HTTPException(
            status_code=403, 
            detail="Access forbidden: Target address rejected by security shield."
        )

    # Enforce YouTube policy restriction on the backend layer
    normalized_url = url.lower()
    if "youtube.com" in normalized_url or "youtu.be" in normalized_url:
        raise HTTPException(
            status_code=403, 
            detail="Policy restriction: YouTube downloads are strictly prohibited."
        )

    # yt-dlp engine extraction profile
    ydl_opts = {
        'format': 'best[ext=mp4]/best',   # Prefer consolidated MP4 stream
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,            # Extract metadata and URLs only
        'noplaylist': True,               # Prevent playlist batch dumps
        'proxy': NANOSTREAM_PROXY,        # Route all outgoing requests via Oracle IP
        'http_headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/122.0.0.0 Safari/537.36'
            ),
            'Accept-Language': 'en-US,en;q=0.9',
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            # Retrieve the direct media download URL
            download_url = info.get("url")
            if not download_url and info.get("formats"):
                download_url = info["formats"][-1].get("url")

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
            detail=f"Extraction failure: Media might be private or platform is unsupported."
        )


@app.get("/api/stream")
async def stream_media(url: str = Query(..., description="Direct CDN media URL to pipe")):
    """
    Streams media in 64KB chunks to trigger native browser 'Save File' dialog.
    Keeps memory usage under 10MB to maintain stability on Render's 512MB RAM tier.
    """
    # Security check on stream target
    if not is_safe_public_url(url):
        raise HTTPException(
            status_code=403, 
            detail="Access forbidden: Invalid stream source."
        )

    async def video_chunk_generator():
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        }

        # Connection timeout is 20s, but stream read is unlimited to allow large downloads
        stream_timeout = httpx.Timeout(None, connect=20.0)

        # Pipe through the same NanoStream proxy to preserve CDN authorization tokens
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
                # Stream 64KB buffer chunks directly to client
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    yield chunk

    # Headers forcing native browser save dialog
    download_headers = {
        "Content-Disposition": 'attachment; filename="AllSavePro_Video.mp4"',
        "Content-Type": "video/mp4",
    }

    return StreamingResponse(video_chunk_generator(), headers=download_headers)
