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
    version="29.0.0" # Final Dailymotion & Curl-Cffi Impersonation Edition
)

# Enable CORS for cross-origin requests from frontend hosts
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Authenticated NanoStream HTTP Proxy for Facebook & Instagram
NANOSTREAM_PROXY = "http://gk:gk%28GK%29321@nanostream4x.duckdns.org:8080"


def clean_tracking_params(target_url: str) -> str:
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
    try:
        parsed = urllib.parse.urlparse(target_url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254"}
        if hostname.lower() in blocked_hosts:
            return False
        return True
    except Exception:
        return False


def get_dynamic_referer(cdn_url: str) -> str:
    cdn_url_lower = cdn_url.lower()
    if "rmbl" in cdn_url_lower or "rumble" in cdn_url_lower:
        return "https://rumble.com/"
    elif "instagram.com" in cdn_url_lower or "cdninstagram.com" in cdn_url_lower:
        return "https://www.instagram.com/"
    elif "fbcdn.net" in cdn_url_lower or "facebook.com" in cdn_url_lower:
        return "https://www.facebook.com/"
    elif "dailymotion.com" in cdn_url_lower or "dmcdn.net" in cdn_url_lower:
        return "https://www.dailymotion.com/"
    return ""


@app.get("/")
async def home_page():
    return FileResponse("index.html")


@app.get("/health")
def health_check():
    return {"status": "alive"}


@app.get("/api/thumbnail")
async def proxy_thumbnail(url: str = Query(..., description="Image URL to proxy")):
    if not is_safe_public_url(url):
        raise HTTPException(status_code=403, detail="Invalid image source.")
    return {"thumbnail_url": url}


# ==========================================
# Extraction Logic with Curl-Cffi Impersonation for Dailymotion & Rumble
# ==========================================
@app.get("/api/info")
def get_media_info(url: str = Query(..., description="Target media URL to extract")):
    if not url or len(url) < 10 or len(url) > 2048:
        raise HTTPException(status_code=400, detail="Invalid URL length.")

    if not is_safe_public_url(url):
        raise HTTPException(status_code=403, detail="Access forbidden.")

    # Strict YouTube Block Policy
    normalized_url = url.lower()
    if "youtube.com" in normalized_url or "youtu.be" in normalized_url:
        raise HTTPException(status_code=403, detail="Policy restriction: YouTube downloads are strictly prohibited.")

    sanitized_url = clean_tracking_params(url)

    if "rumble.com/shorts/" in sanitized_url:
        sanitized_url = sanitized_url.replace("/shorts/", "/v/")

    is_rumble = "rumble.com" in sanitized_url or "rmbl" in sanitized_url
    is_dailymotion = "dailymotion.com" in sanitized_url or "dai.ly" in sanitized_url

    base_opts = {
        'format': 'best[ext=mp4]/best',
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': False,
        'nocheckcertificate': True,
        'socket_timeout': 20, 
        'retries': 2, 
        'extractor_retries': 2,
        'fragment_retries': 2,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
    }

    # रंबल और डेलीमोशन के लिए curl_cffi आधारित क्रोम इम्पर्सनेशन का उपयोग
    if is_rumble or is_dailymotion:
        strategies = [
            {'proxy': None, 'impersonate': 'chrome'},
            {'proxy': None, 'impersonate': None}
        ]
    else:
        strategies = [
            {'proxy': NANOSTREAM_PROXY, 'impersonate': None},
            {'proxy': None, 'impersonate': None}
        ]
    
    info = None
    extraction_error = None

    for strat in strategies:
        opts = base_opts.copy()
        if strat['proxy']:
            opts['proxy'] = strat['proxy']
        
        if strat['impersonate']:
            opts['impersonate'] = strat['impersonate']
            
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(sanitized_url, download=False)
                if info:
                    break 
        except Exception as e:
            extraction_error = str(e)
            continue 

    if not info:
        raise HTTPException(status_code=400, detail=f"Could not process media. Error: {extraction_error}")

    if 'entries' in info and info['entries']:
        for entry in info['entries']:
            if entry and (entry.get('url') or entry.get('formats')):
                info = entry
                break

    download_url = info.get("url")
    
    if not download_url and info.get("formats"):
        for fmt in reversed(info["formats"]):
            if fmt.get("url") and fmt.get("vcodec") != "none":
                download_url = fmt.get("url")
                break
        if not download_url:
            for fmt in reversed(info["formats"]):
                if fmt.get("url"):
                    download_url = fmt.get("url")
                    break

    if not download_url:
        raise HTTPException(status_code=400, detail="Could not extract direct stream link.")

    raw_thumbnail = info.get("thumbnail") or ""

    return {
        "success": True,
        "title": info.get("title") or "AllSavePro Media",
        "thumbnail": raw_thumbnail,
        "duration": info.get("duration") or 0,
        "download_url": download_url
    }


# ==========================================
# Streaming System
# ==========================================
@app.get("/api/stream")
async def stream_media(url: str = Query(..., description="Direct CDN media URL to pipe")):
    if not is_safe_public_url(url):
        raise HTTPException(status_code=403, detail="Invalid stream source.")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    dynamic_referer = get_dynamic_referer(url)
    if dynamic_referer:
        headers["Referer"] = dynamic_referer
        headers["Origin"] = dynamic_referer.strip("/")

    is_rumble = "rumble.com" in url.lower() or "rmbl" in url.lower()
    is_dailymotion = "dailymotion.com" in url.lower() or "dmcdn.net" in url.lower()

    if is_rumble or is_dailymotion:
        proxies_to_try = [None, NANOSTREAM_PROXY]
    else:
        proxies_to_try = [NANOSTREAM_PROXY, None]

    timeout = httpx.Timeout(None, connect=10.0) 
    client = None
    response = None

    try:
        for proxy_url in proxies_to_try:
            try:
                client = httpx.AsyncClient(proxy=proxy_url, follow_redirects=True, timeout=timeout)
                request = client.build_request("GET", url, headers=headers)
                response = await client.send(request, stream=True)
                content_type = response.headers.get("content-type", "").lower()

                if response.status_code == 200 and "text/html" not in content_type:
                    break 
                
                await response.aclose()
                await client.aclose()
                client = None
                response = None
            except Exception:
                if response:
                    try: await response.aclose()
                    except: pass
                if client:
                    try: await client.aclose()
                    except: pass
                client = None
                response = None

        if not response:
            raise HTTPException(status_code=400, detail="CDN blocked the stream. Please try again.")

        async def video_chunk_generator():
            try:
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    yield chunk
            finally:
                if response:
                    try: await response.aclose()
                    except: pass
                if client:
                    try: await client.aclose()
                    except: pass

        download_headers = {
            "Content-Disposition": 'attachment; filename="AllSavePro_Video.mp4"',
            "Content-Type": "video/mp4",
            "Cache-Control": "no-cache",
        }

        return StreamingResponse(video_chunk_generator(), headers=download_headers)
        
    except HTTPException:
        if response:
            try: await response.aclose()
            except: pass
        if client:
            try: await client.aclose()
            except: pass
        raise
    except Exception:
        if response:
            try: await response.aclose()
            except: pass
        if client:
            try: await client.aclose()
            except: pass
        raise HTTPException(status_code=400, detail="Internal server timeout or processing error.")
