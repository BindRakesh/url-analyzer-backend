from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright
import asyncio
import logging
import validators
from typing import List, Dict
import time
import json
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://urljourney.netlify.app/"],  # Replace Netlify URL later
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

# async def fetch_url_with_playwright(url: str, websocket: WebSocket) -> bool:
#     async with async_playwright() as playwright:
#         browser = None
#         try:
#             logger.info(f"Launching browser for {url}")
#             browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
#             context = await browser.new_context()
#             page = await context.new_page()

#             redirect_chain = []
#             start_time = time.time()

#             async def handle_request(request):
#                 if request.is_navigation_request():
#                     logger.debug(f"Navigation request: {request.url}")

#             async def handle_response(response):
#                 if response.request.is_navigation_request():
#                     hop = {
#                         "url": response.url,
#                         "status": response.status,
#                         "server": get_server_name(response.headers, response.url),
#                         "timestamp": time.time() - start_time
#                     }
#                     if not redirect_chain or redirect_chain[-1]["url"] != hop["url"]:
#                         redirect_chain.append(hop)
#                         logger.debug(f"Added hop: {hop}")

#             page.on("request", handle_request)
#             page.on("response", handle_response)

#             try:
#                 response = await page.goto(url, timeout=30000, wait_until="domcontentloaded")
#             except Exception as nav_error:
#                 logger.warning(f"Navigation timeout for {url}: {nav_error}")
#                 final_url = page.url if page.url else url
#                 result = {
#                     "originalURL": url,
#                     "finalURL": final_url,
#                     "redirectChain": redirect_chain,
#                     "totalTime": time.time() - start_time,
#                     "warning": "Navigation timed out after 30s"
#                 }
#                 await websocket.send_text(json.dumps(result))
#                 return True

#             final_url = page.url

#             if not redirect_chain or redirect_chain[-1]["url"] != final_url:
#                 hop = {
#                     "url": final_url,
#                     "status": response.status if response else 200,
#                     "server": get_server_name(response.headers, final_url) if response else "Unknown",
#                     "timestamp": time.time() - start_time
#                 }
#                 redirect_chain.append(hop)
#                 logger.debug(f"Added final hop: {hop}")

#             if len(redirect_chain) > 10:
#                 logger.warning(f"Possible redirect loop detected for {url}")
#                 redirect_chain.append({"error": "Excessive redirects (limit: 10)"})

#             result = {
#                 "originalURL": url,
#                 "finalURL": final_url,
#                 "redirectChain": redirect_chain,
#                 "totalTime": time.time() - start_time
#             }
#             await websocket.send_text(json.dumps(result))
#             return True
#         except WebSocketDisconnect:
#             logger.info(f"Client disconnected while processing {url}")
#             return False
#         except Exception as e:
#             logger.error(f"Error fetching {url}: {e}")
#             result = {
#                 "originalURL": url,
#                 "finalURL": None,
#                 "redirectChain": redirect_chain if 'redirect_chain' in locals() else [],
#                 "totalTime": None,
#                 "error": "Failed to fetch URL"
#             }
#             try:
#                 await websocket.send_text(json.dumps(result))
#                 return True
#             except WebSocketDisconnect:
#                 logger.info(f"Client disconnected while sending error for {url}")
#                 return False
#         finally:
#             if browser:
#                 try:
#                     await browser.close()
#                     logger.info(f"Browser closed for {url}")
#                 except Exception as e:
#                     logger.error(f"Error closing browser for {url}: {e}")

async def fetch_url_with_playwright(url: str, websocket: WebSocket) -> bool:
    async with async_playwright() as playwright:
        browser = None
        try:
            logger.info(f"Launching browser for {url}")
            browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
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
                # Start waiting for navigation before going to the URL
                navigation_promise = page.wait_for_navigation(timeout=30000)
                response = await page.goto(url, timeout=30000, wait_until="networkidle")
                # Wait for any additional navigation (e.g., client-side redirects)
                await navigation_promise
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
                return True

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
            logger.info(f"Result for {url}: {result}")
            await websocket.send_text(json.dumps(result))
            return True
        except WebSocketDisconnect:
            logger.info(f"Client disconnected while processing {url}")
            return False
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            result = {
                "originalURL": url,
                "finalURL": None,
                "redirectChain": redirect_chain if 'redirect_chain' in locals() else [],
                "totalTime": None,
                "error": "Failed to fetch URL"
            }
            try:
                await websocket.send_text(json.dumps(result))
                return True
            except WebSocketDisconnect:
                logger.info(f"Client disconnected while sending error for {url}")
                return False
        finally:
            if browser:
                try:
                    await browser.close()
                    logger.info(f"Browser closed for {url}")
                except Exception as e:
                    logger.error(f"Error closing browser for {url}: {e}")

async def validate_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    if not validators.url(url):
        raise ValueError(f"Invalid URL: {url}")
    return url

@app.websocket("/analyze")
async def analyze_urls_websocket(websocket: WebSocket):
    logger.info("WebSocket connection attempt")
    await websocket.accept()
    logger.info("WebSocket connection accepted")
    try:
        data = await websocket.receive_json()
        logger.info(f"Received data: {data}")
        urls = list(set(filter(None, data.get("urls", []))))
        if not urls:
            await websocket.send_text(json.dumps({"error": "No valid URLs provided"}))
            return

        validated_urls = [await validate_url(url) for url in urls]
        for url in validated_urls:
            # Check if client is still connected
            try:
                await websocket.send_text(json.dumps({"status": "processing", "url": url}))
            except WebSocketDisconnect:
                logger.info("Client disconnected before processing started")
                return

            # Process URL and stop if client disconnects
            continue_processing = await fetch_url_with_playwright(url, websocket)
            if not continue_processing:
                logger.info("Stopping URL processing due to client disconnection")
                return

            # Add a small delay to allow memory cleanup
            await asyncio.sleep(1)

        await websocket.send_text(json.dumps({"done": True}))
    except WebSocketDisconnect:
        logger.info("Client disconnected during WebSocket operation")
    except ValueError as ve:
        logger.error(f"Validation error: {ve}")
        try:
            await websocket.send_text(json.dumps({"error": "Invalid input"}))
        except WebSocketDisconnect:
            logger.info("Client disconnected while sending validation error")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_text(json.dumps({"error": "Internal server error"}))
        except WebSocketDisconnect:
            logger.info("Client disconnected while sending error")
    finally:
        try:
            await websocket.close()
            logger.info("WebSocket connection closed")
        except Exception as e:
            logger.error(f"Error closing WebSocket: {e}")

@app.get("/test")
async def test():
    return {"status": "OK", "message": "Service operational"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    logger.info(f"Starting Uvicorn on port {port}")
    logger.info(f"Playwright browsers path: {os.getenv('PLAYWRIGHT_BROWSERS_PATH', 'Not set')}")
    uvicorn.run(app, host="0.0.0.0", port=port)