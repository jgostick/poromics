"""Management command to generate thumbnails for existing images."""

from django.core.management.base import BaseCommand
from django.db import models

from apps.pore_analysis.models import UploadedImage


class Command(BaseCommand):
    help = 'Generate thumbnails for existing images that do not have them'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Regenerate thumbnails even if they already exist',
        )

    def handle(self, *args, **options):
        force = options['force']
        
        # Get images without thumbnails, or all images if force is True
        if force:
            images = UploadedImage.objects.all()
            self.stdout.write(f"Regenerating thumbnails for all {images.count()} images...")
        else:
            images = UploadedImage.objects.filter(
                models.Q(thumbnail__isnull=True) | models.Q(thumbnail='')
            )
            self.stdout.write(f"Generating thumbnails for {images.count()} images without thumbnails...")

        success_count = 0
        error_count = 0

        for image in images:
            try:
                # Generate thumbnail
                result = image.generate_thumbnail(save=True)
                if result:
                    image.save()
                    success_count += 1
                    self.stdout.write(f"Generated thumbnail for: {image.name}")
                else:
                    error_count += 1
                    self.stdout.write(
                        self.style.WARNING(f"Failed to generate thumbnail for: {image.name}")
                    )
            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(f"Error generating thumbnail for {image.name}: {e}")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Thumbnail generation complete: {success_count} successful, {error_count} failed"
            )
        )