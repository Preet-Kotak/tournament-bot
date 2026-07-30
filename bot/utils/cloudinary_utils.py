import aiohttp
import logging
import os
from typing import Optional

log = logging.getLogger(__name__)

# Try to import cloudinary, but don't fail if not installed
try:
    import cloudinary
    import cloudinary.uploader
    CLOUDINARY_AVAILABLE = True
except ImportError:
    CLOUDINARY_AVAILABLE = False
    log.warning("Cloudinary package not installed. Install with: pip install cloudinary")

# Initialize Cloudinary (configure once)
def init_cloudinary():
    """Initialize Cloudinary configuration from environment variables"""
    if not CLOUDINARY_AVAILABLE:
        log.warning("Cloudinary package not available. Image uploads will use Discord storage.")
        return False
    
    cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME')
    api_key = os.getenv('CLOUDINARY_API_KEY')
    api_secret = os.getenv('CLOUDINARY_API_SECRET')
    
    if not all([cloud_name, api_key, api_secret]):
        log.warning("Cloudinary credentials not configured. Image uploads will fall back to Discord storage.")
        return False
    
    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True
    )
    log.info("Cloudinary configured successfully")
    return True


async def upload_to_cloudinary(image_url: str, folder: str = "tournament_bases") -> Optional[str]:
    """
    Upload an image to Cloudinary from a URL
    
    Args:
        image_url: The URL of the image to upload
        folder: The folder name in Cloudinary (default: "tournament_bases")
    
    Returns:
        The Cloudinary URL if successful, None otherwise
    """
    if not CLOUDINARY_AVAILABLE:
        log.error("Cloudinary package not installed")
        return None
    
    try:
        # Download the image first
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as resp:
                if resp.status != 200:
                    log.error(f"Failed to download image from {image_url}: HTTP {resp.status}")
                    return None
                image_bytes = await resp.read()
        
        # Upload to Cloudinary using synchronous uploader (in executor to avoid blocking)
        import asyncio
        loop = asyncio.get_event_loop()
        
        result = await loop.run_in_executor(
            None,
            lambda: cloudinary.uploader.upload(
                image_bytes,
                folder=folder,
                resource_type="image"
            )
        )
        
        cloudinary_url = result.get('secure_url')
        if cloudinary_url:
            log.info(f"Successfully uploaded image to Cloudinary: {cloudinary_url}")
            return cloudinary_url
        else:
            log.error("Cloudinary upload succeeded but no URL returned")
            return None
            
    except Exception as e:
        log.error(f"Error uploading to Cloudinary: {e}")
        return None
