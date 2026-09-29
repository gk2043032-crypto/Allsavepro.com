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
    version="4.0.0" # Final Production Stable Version
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


def get_dynamic_referer(cdn_url: str) -> str:
    """
    Dynamically generates the correct Referer and Origin based on the CDN URL.
    This ensures Facebook, Instagram, and Rumble all get their correct native headers
    without breaking each other's stream.
    """
    cdn_url_lower = cdn_url.lower()
    if "rmbl" in cdn_url_lower or "rumble" in cdn_url_lower:
        return "https://rumble.com/"
    elif "instagram.com" in cdn_url_lower or "cdninstagram.com" in cdn_url_lower:
        return "https://www.instagram.com/"
    elif "fbcdn.net" in cdn_url_lower or "facebook.com" in cdn_url_lower:
        return "https://www.facebook.com/"
    return ""


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
    with smart fallback proxy routing and Cloudflare impersonate bypass.
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

    # Rumble Shorts URL Fix to standard format
    if "rumble.com/shorts/" in sanitized_url:
        sanitized_url = sanitized_url.replace("/shorts/", "/v/")

    # Base yt-dlp options
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': False, # Important for Rumble lists/shorts
        'nocheckcertificate': True,
        'proxy': NANOSTREAM_PROXY, # Facebook/Instagram के लिए Proxy On
        'socket_timeout': 30,
        'extractor_args': {
            'generic': {
                'impersonate': 'chrome'
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        }
    }

    try:
        # Attempt 1: Proxy के साथ डेटा निकालने की कोशिश (FB/Insta के लिए सुरक्षित)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(sanitized_url, download=False)
    except Exception:
        # Attempt 2: अगर Proxy पर 403 (Cloudflare) एरर आता है (खासकर Rumble पर), तो Proxy हटाकर डायरेक्ट निकालें
        del ydl_opts['proxy']
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(sanitized_url, download=False)
        except Exception as retry_err:
            raise HTTPException(
                status_code=400, 
                detail=f"Extraction failure: {str(retry_err)}"
            )

    # 1. अगर वीडियो किसी लिस्ट या entries के अंदर है, तो मुख्य वीडियो निकालें
    if info and 'entries' in info and info['entries']:
        for entry in info['entries']:
            if entry and (entry.get('url') or entry.get('formats')):
                info = entry
                break

    download_url = info.get("url")
    
    # 2. अगर सीधा URL नहीं है, तो formats में से सही वीडियो (Video Codec के साथ) निकालें
    if not download_url and info.get("formats"):
        for fmt in reversed(info["formats"]):
            if fmt.get("url") and fmt.get("vcodec") != "none":
                download_url = fmt.get("url")
                break
        # अगर फिर भी न मिले, तो कोई भी उपलब्ध url ले लें
        if not download_url:
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


@app.get("/api/stream")
async def stream_media(url: str = Query(..., description="Direct CDN media URL to pipe")):
    """
    Streams media in 64KB chunks with proper dynamic headers and Anti-Blank Video Shield.
    """
    if not is_safe_public_url(url):
        raise HTTPException(
            status_code=403, 
            detail="Access forbidden: Invalid stream source."
        )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    # Dynamic Headers: सिर्फ उस वेबसाइट का हेडर सेट करें जिसका वीडियो है, ताकि दूसरे न टूटें
    dynamic_referer = get_dynamic_referer(url)
    if dynamic_referer:
        headers["Referer"] = dynamic_referer
        headers["Origin"] = dynamic_referer.strip("/")

    timeout = httpx.Timeout(None, connect=20.0)

    # Attempt 1: Proxy के साथ स्ट्रीम कनेक्ट करें
    client = httpx.AsyncClient(proxy=NANOSTREAM_PROXY, follow_redirects=True, timeout=timeout)
    request = client.build_request("GET", url, headers=headers)
    response = await client.send(request, stream=True)
    
    content_type = response.headers.get("content-type", "").lower()

    # ANTI-BLANK VIDEO SHIELD: अगर वीडियो की जगह HTML एरर आ रहा है, तो प्रॉक्सी हटाकर सीधा कनेक्ट करें
    if response.status_code != 200 or "text/html" in content_type:
        await response.aclose()
        await client.aclose()
        
        # Attempt 2: डायरेक्ट स्ट्रीम (बिना प्रॉक्सी)
        client = httpx.AsyncClient(follow_redirects=True, timeout=timeout)
        request = client.build_request("GET", url, headers=headers)
        response = await client.send(request, stream=True)
        
        content_type = response.headers.get("content-type", "").lower()
        
        # अगर फिर भी HTML एरर आता है, तो ब्लैंक वीडियो डाउनलोड करने के बजाय कनेक्शन रोक दें
        if response.status_code != 200 or "text/html" in content_type:
            await response.aclose()
            await client.aclose()
            raise HTTPException(
                status_code=400, 
                detail="CDN blocked the stream. Anti-Blank Video Shield prevented corrupt download."
            )

    async def video_chunk_generator():
        try:
            async for chunk in response.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    download_headers = {
        "Content-Disposition": 'attachment; filename="AllSavePro_Video.mp4"',
        "Content-Type": "video/mp4",
        "Cache-Control": "no-cache",
    }

    return StreamingResponse(video_chunk_generator(), headers=download_headers)
