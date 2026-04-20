#!/usr/bin/env python
"""
Test script for thumbnail generation.
Run with: python test_thumbnail.py
"""
import logging
import os

import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'poromics.settings')
django.setup()

from apps.pore_analysis.models import UploadedImage

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_thumbnail_generation():
    """Test thumbnail generation for existing images."""
    print("Testing thumbnail generation...")
    
    # Get an image that doesn't have a thumbnail yet
    images = UploadedImage.objects.filter(thumbnail__isnull=True)[:1]
    
    if not images:
        print("No images without thumbnails found. Testing with first image...")
        images = UploadedImage.objects.all()[:1]
    
    if not images:
        print("No images found to test with.")
        return
    
    image = images[0] 
    print(f"Testing with image: {image.name}")
    print(f"File path: {image.file.path}")
    print(f"File exists: {os.path.exists(image.file.path)}")
    
    try:
        # Test thumbnail generation
        thumbnail_data = image.generate_thumbnail(save=False)
        if thumbnail_data:
            print(f"✅ Thumbnail generated successfully! Size: {len(thumbnail_data)} bytes")
            
            # Now try to save it
            image.generate_thumbnail(save=True)
            image.save()
            print("✅ Thumbnail saved successfully!")
            
        else:
            print("❌ Thumbnail generation returned None")
            
    except Exception as e:
        print(f"❌ Error during thumbnail generation: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_thumbnail_generation()