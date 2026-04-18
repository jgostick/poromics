import uuid
import os
from decimal import Decimal
from django.db import models
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.conf import settings
from apps.teams.models import BaseTeamModel
from apps.utils.models import BaseModel
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
from io import BytesIO
try:
    import porespy as ps
except ImportError:
    ps = None

User = get_user_model()


class UploadedImage(BaseTeamModel):
    """Represents a volumetric image uploaded by a user for analysis."""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, help_text="User-provided name for the image")
    description = models.TextField(blank=True, help_text="Optional description of the image")
    file = models.FileField(upload_to='uploaded_images/', help_text="The .npy file containing the boolean array")
    thumbnail = models.ImageField(upload_to='image_thumbnails/', null=True, blank=True, help_text="Generated thumbnail image")
    file_size = models.PositiveIntegerField(help_text="File size in bytes")
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='uploaded_images')
    
    # Image metadata
    dimensions = models.JSONField(help_text="Array shape as [x, y, z]")
    voxel_size = models.FloatField(null=True, blank=True, help_text="Voxel size in micrometers")
    metrics = models.JSONField(default=dict, blank=True, help_text="Image metrics")
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Uploaded Image'
        verbose_name_plural = 'Uploaded Images'
        
    def __str__(self):
        return f"{self.name} ({self.uploaded_by.email})"
    
    @property
    def file_size_mb(self):
        """Return file size in MB for display."""
        return round(self.file_size / (1024 * 1024), 2)
    
    @property
    def total_voxels(self):
        """Calculate total number of voxels in the image."""
        if self.dimensions:
            total = 1
            for dim in self.dimensions:
                total *= dim
            return total
        return 0
    
    def generate_thumbnail(self, save=True):
        """Generate a thumbnail using porespy visualization."""
        import logging
        logger = logging.getLogger(__name__)
        
        if not ps:
            error_msg = "Porespy not available for thumbnail generation"
            logger.error(error_msg)
            print(error_msg)
            return None
            
        try:
            logger.info(f"Starting thumbnail generation for {self.name}")
            
            # Load the numpy array
            logger.info(f"Loading array from {self.file.path}")
            with self.file.open('rb') as f:
                image_array = np.load(f)
            
            logger.info(f"Array loaded with shape: {image_array.shape}, dtype: {image_array.dtype}")
            
            # Generate X-ray view using porespy
            if len(image_array.shape) == 3:
                logger.info("Generating xray view for 3D array")
                # For 3D arrays, use porespy's xray visualization
                xray_img = ps.visualization.xray(image_array)
            elif len(image_array.shape) == 2:
                logger.info("Using 2D array directly")
                # For 2D arrays, just use the array directly
                xray_img = image_array
            else:
                error_msg = f"Invalid array dimensions: {image_array.shape}"
                logger.error(error_msg)
                print(error_msg)
                return None
            
            logger.info(f"Xray image generated with shape: {xray_img.shape}")
            
            # Set matplotlib backend before importing pyplot
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            from io import BytesIO
            from django.core.files.base import ContentFile
            
            # Clear any existing figures
            plt.clf()
            
            # Create matplotlib figure
            logger.info("Creating matplotlib figure")
            fig, ax = plt.subplots(figsize=(4, 4), dpi=100)
            ax.imshow(xray_img, cmap='gray')
            ax.axis('off')
            plt.tight_layout(pad=0)
            
            # Save to BytesIO buffer
            logger.info("Saving figure to buffer")
            buffer = BytesIO()
            canvas = FigureCanvasAgg(fig)
            canvas.print_png(buffer)
            buffer.seek(0)
            plt.close(fig)
            
            logger.info(f"Buffer created with {len(buffer.getvalue())} bytes")
            
            if save:
                # Save thumbnail to model
                thumbnail_name = f"{self.id}_thumbnail.png"
                logger.info(f"Saving thumbnail as {thumbnail_name}")
                self.thumbnail.save(
                    thumbnail_name,
                    ContentFile(buffer.getvalue()),
                    save=False
                )
                logger.info("Thumbnail saved successfully")
            
            return buffer.getvalue()
            
        except ImportError as e:
            error_msg = f"Import error generating thumbnail for {self.name}: {e}"
            logger.error(error_msg)
            print(error_msg)
            return None
        except FileNotFoundError as e:
            error_msg = f"File not found for thumbnail generation {self.name}: {e}"
            logger.error(error_msg)
            print(error_msg)
            return None
        except Exception as e:
            error_msg = f"Unexpected error generating thumbnail for {self.name}: {type(e).__name__}: {e}"
            logger.error(error_msg, exc_info=True)  # This will include the full traceback
            print(error_msg)
            import traceback
            traceback.print_exc()  # Print full traceback to console
            return None
        
    def compute_metrics(self, save=True):
        """Load image array and compute all metrics, store in model."""
        try:
            with self.file.open('rb') as f:
                image_array = np.load(f, allow_pickle=False)
            
            from .analysis.metrics import get_image_metrics
            self.metrics = get_image_metrics(image_array)
            
            if save:
                self.save(update_fields=['metrics'])
            
            return self.metrics
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to compute metrics for {self.name}: {e}")
            return {}


class AnalysisType(models.TextChoices):
    """Available types of pore analysis."""
    NETWORK_EXTRACTION = 'network_extraction', _('Pore Network Extraction')
    PERMEABILITY = 'permeability', _('Permeability Calculation')
    DIFFUSIVITY = 'diffusivity', _('Diffusivity Calculation')
    MORPHOLOGY = 'morphology', _('Morphological Analysis')
    VISUALIZATION = 'visualization', _('3D Visualization')
    FULL_SUITE = 'full_suite', _('Complete Analysis Suite')


class JobStatus(models.TextChoices):
    """Status of an analysis job."""
    PENDING = 'pending', _('Pending')
    PROCESSING = 'processing', _('Processing')
    COMPLETED = 'completed', _('Completed')
    FAILED = 'failed', _('Failed')
    CANCELLED = 'cancelled', _('Cancelled')


class AnalysisJob(BaseTeamModel):
    """Represents an analysis job running on an uploaded image."""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    image = models.ForeignKey(UploadedImage, on_delete=models.CASCADE, related_name='analysis_jobs')
    analysis_type = models.CharField(max_length=50, choices=AnalysisType.choices)
    status = models.CharField(max_length=20, choices=JobStatus.choices, default=JobStatus.PENDING)
    
    # Job metadata
    started_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='started_jobs')
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Processing details
    parameters = models.JSONField(default=dict, blank=True, help_text="Submitted analysis parameters")
    celery_task_id = models.CharField(max_length=100, null=True, blank=True, help_text="Celery task ID")
    progress_percentage = models.PositiveSmallIntegerField(default=0, help_text="Job completion percentage")
    error_message = models.TextField(blank=True, help_text="Error details if job failed")
    
    # Cost tracking
    estimated_cost = models.DecimalField(max_digits=8, decimal_places=2, help_text="Estimated cost in USD")
    actual_cost = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, help_text="Actual cost charged")
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Analysis Job'
        verbose_name_plural = 'Analysis Jobs'
        
    def __str__(self):
        return f"{self.get_analysis_type_display()} - {self.image.name} ({self.get_status_display()})"
    
    @property
    def duration(self):
        """Return job duration if completed."""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None


class AnalysisResult(BaseModel):
    """Stores results from completed analyses."""
    
    job = models.OneToOneField(AnalysisJob, on_delete=models.CASCADE, related_name='result')
    
    # Result files
    network_file = models.FileField(upload_to='analysis_results/', null=True, blank=True, 
                                   help_text="Extracted pore network file")
    visualization_file = models.FileField(upload_to='analysis_results/', null=True, blank=True,
                                         help_text="3D visualization file")
    report_file = models.FileField(upload_to='analysis_results/', null=True, blank=True,
                                  help_text="Analysis report PDF")
    
    # Computed metrics
    metrics = models.JSONField(default=dict, help_text="Analysis metrics and properties")
    
    class Meta:
        verbose_name = 'Analysis Result'
        verbose_name_plural = 'Analysis Results'
        
    def __str__(self):
        return f"Results for {self.job}"


class CreditTransaction(BaseTeamModel):
    """Tracks credit purchases and usage for billing."""
    
    TRANSACTION_TYPES = [
        ('purchase', _('Credit Purchase')),
        ('usage', _('Analysis Usage')),
        ('refund', _('Refund')),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='credit_transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=8, decimal_places=2, help_text="Amount in USD (positive=credit, negative=debit)")
    
    # Related objects
    analysis_job = models.ForeignKey(AnalysisJob, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='credit_transactions')
    
    # Transaction metadata
    description = models.CharField(max_length=200, help_text="Description of the transaction")
    stripe_charge_id = models.CharField(max_length=100, null=True, blank=True, help_text="Stripe charge ID for purchases")
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Credit Transaction'
        verbose_name_plural = 'Credit Transactions'
        
    def __str__(self):
        symbol = '+' if self.amount >= 0 else ''
        return f"{symbol}${self.amount} - {self.description} ({self.user.email})"
