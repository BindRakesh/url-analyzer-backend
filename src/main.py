from fastapi import FastAPI, HTTPException, Request, WebSocket, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyQuery
from playwright.async_api import async_playwright
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import asyncio
import logging
import validators
from typing import List, Dict
import time
import json
import os

app = FastAPI()

# Rate limiting setup
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# API key setup (using query param for WebSocket compatibility)
API_KEY = "secret-api-key-mai-nahi-bataunga"  # Replace with a secure key
api_key_query = APIKeyQuery(name="api_key")

async def verify_api_key(api_key: str = Depends(api_key_query)):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return api_key

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://urljourney.netlify.app/"],  # Replace with your Netlify URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def get_server_name(headers: dict, url: str) -> str:
    for key in headers:
        if key.lower() == "server":
            server_value = headers[key].lower()
            if "akamai" in server_value or "ghost" in server_value:
                return "Akamai"
            return headers[key]
    logger.debug(f"Headers for {url}: {json.dumps(headers, indent=2)}")
    if any(key.lower().startswith("x-akamai") for key in headers) or "akamai" in url.lower():
        return "Akamai"
    return "Unknown"

async def fetch_url_with_playwright(url: str, websocket: WebSocket) -> None:
    """Fetch URL using Playwright and send results via WebSocket with full redirect chain."""
    async with async_playwright() as playwright:
        browser = None
        try:
            logger.info(f"Launching browser for {url}")
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            redirect_chain = []
            start_time = time.time()

            async def handle_request(request):
                if request.is_navigation_request():
                    logger.debug(f"Navigation request: {request.url}")

            async def handle_response(response):
                if response.request.is_navigation_request():
                    hop = {
                        "url": response.url,
                        "status": response.status,
                        "server": get_server_name(response.headers, response.url),
                        "timestamp": time.time() - start_time
                    }
                    if not redirect_chain or redirect_chain[-1]["url"] != hop["url"]:
                        redirect_chain.append(hop)
                        logger.debug(f"Added hop: {hop}")

            page.on("request", handle_request)
            page.on("response", handle_response)

            try:
                response = await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            except Exception as nav_error:
                logger.warning(f"Navigation timeout for {url}: {nav_error}")
                final_url = page.url if page.url else url
                result = {
                    "originalURL": url,
                    "finalURL": final_url,
                    "redirectChain": redirect_chain,
                    "totalTime": time.time() - start_time,
                    "warning": "Navigation timed out after 30s"
                }
                await websocket.send_text(json.dumps(result))
                return

            final_url = page.url

            if not redirect_chain or redirect_chain[-1]["url"] != final_url:
                hop = {
                    "url": final_url,
                    "status": response.status if response else 200,
                    "server": get_server_name(response.headers, final_url) if response else "Unknown",
                    "timestamp": time.time() - start_time
                }
                redirect_chain.append(hop)
                logger.debug(f"Added final hop: {hop}")

            if len(redirect_chain) > 10:
                logger.warning(f"Possible redirect loop detected for {url}")
                redirect_chain.append({"error": "Excessive redirects (limit: 10)"})

            result = {
                "originalURL": url,
                "finalURL": final_url,
                "redirectChain": redirect_chain,
                "totalTime": time.time() - start_time
            }
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            result = {
                "originalURL": url,
                "finalURL": None,
                "redirectChain": redirect_chain if 'redirect_chain' in locals() else [],
                "totalTime": None,
                "error": "Failed to fetch URL"
            }
        finally:
            if browser:
                await browser.close()

        await websocket.send_text(json.dumps(result))

async def validate_url(url: str) -> str:
    """Ensure URL is valid and formatted correctly."""
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    if not validators.url(url):
        raise ValueError("Invalid URL format")
    return url

@app.websocket("/analyze")
@limiter.limit("15/minute")  # 15 requests per minute per IP
async def analyze_urls_websocket(websocket: WebSocket, api_key: str = Depends(verify_api_key)):
    """WebSocket endpoint to analyze URLs in real-time."""
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        urls = list(set(filter(None, data.get("urls", []))))
        if not urls:
            await websocket.send_text(json.dumps({"error": "No valid URLs provided"}))
            return

        validated_urls = [await validate_url(url) for url in urls]
        for url in validated_urls:
            await fetch_url_with_playwright(url, websocket)

        await websocket.send_text(json.dumps({"done": True}))
    except ValueError as ve:
        logger.error(f"Validation error: {ve}")
        await websocket.send_text(json.dumps({"error": "Invalid input"}))
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.send_text(json.dumps({"error": "Internal server error"}))
    finally:
        await websocket.close()

@app.get("/test")
async def test():
    """Health check endpoint."""
    return {"status": "OK", "message": "Service operational"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    logger.info(f"Starting Uvicorn on port {port}")
    logger.info(f"Playwright browsers path: {os.getenv('PLAYWRIGHT_BROWSERS_PATH', 'Not set')}")
    uvicorn.run(app, host="0.0.0.0", port=port)