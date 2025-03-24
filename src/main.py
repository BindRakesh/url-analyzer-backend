from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright, Playwright
import asyncio
import logging
import validators
from typing import List, Dict
import time
import json

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(level=logging.DEBUG)  # Set to DEBUG for detailed output
logger = logging.getLogger(__name__)

# Browser pool for performance
_browser_semaphore = asyncio.Semaphore(5)  # Limit to 5 concurrent browser instances

def get_server_name(headers: dict, url: str) -> str:
    """Extract server name from headers with enhanced Akamai detection."""
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

async def fetch_url_with_playwright(url: str, playwright: Playwright, websocket: WebSocket) -> None:
    """Fetch URL using Playwright and send results via WebSocket with full redirect chain."""
    async with _browser_semaphore:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        redirect_chain = []
        start_time = time.time()

        async def handle_request(request):
            if request.is_navigation_request():
                logger.debug(f"Navigation request: {request.url}")
                # We'll populate status and server later from response

        async def handle_response(response):
            if response.request.is_navigation_request():
                hop = {
                    "url": response.url,
                    "status": response.status,
                    "server": get_server_name(response.headers, response.url),
                    "timestamp": time.time() - start_time
                }
                # Avoid duplicates
                if not redirect_chain or redirect_chain[-1]["url"] != hop["url"]:
                    redirect_chain.append(hop)
                    logger.debug(f"Added hop: {hop}")

        page.on("request", handle_request)
        page.on("response", handle_response)

        try:
            response = await page.goto(url, timeout=10000, wait_until="domcontentloaded")
            final_url = page.url

            # Ensure final URL is in the chain if not already captured
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

            await browser.close()

            result = {
                "originalURL": url,
                "finalURL": final_url,
                "redirectChain": redirect_chain,
                "totalTime": time.time() - start_time
            }
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            await browser.close()
            result = {
                "originalURL": url,
                "finalURL": None,
                "redirectChain": redirect_chain if redirect_chain else [],
                "totalTime": None,
                "error": f"Failed to fetch: {str(e)}"
            }

        # Send result over WebSocket
        await websocket.send_text(json.dumps(result))

async def validate_url(url: str) -> str:
    """Ensure URL is valid and formatted correctly."""
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    if not validators.url(url):
        raise ValueError(f"Invalid URL: {url}")
    return url

@app.websocket("/analyze")
async def analyze_urls_websocket(websocket: WebSocket):
    """WebSocket endpoint to analyze URLs in real-time."""
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        urls = list(set(filter(None, data.get("urls", []))))  # Remove duplicates and empty

        if not urls:
            await websocket.send_text(json.dumps({"error": "No valid URLs provided"}))
            await websocket.close()
            return

        validated_urls = [await validate_url(url) for url in urls]

        async with async_playwright() as playwright:
            tasks = [fetch_url_with_playwright(url, playwright, websocket) for url in validated_urls]
            await asyncio.gather(*tasks)

        await websocket.send_text(json.dumps({"done": True}))
        await websocket.close()
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.send_text(json.dumps({"error": f"Server error: {str(e)}"}))
        await websocket.close()

@app.get("/test")
async def test():
    """Health check endpoint."""
    return {"status": "OK", "message": "Service operational"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="192.168.0.132", port=5000)