from io import BytesIO

import imageio.v3 as iio
import numpy as np
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.pore_analysis.models import UploadedImage
from apps.teams.helpers import create_default_team_for_user
from apps.users.models import CustomUser


class UploadImageViewTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="upload-user@example.com",
            email="upload-user@example.com",
            password="pass123",
        )
        self.team = create_default_team_for_user(self.user, team_name="Upload Team")
        self.client.force_login(self.user)
        self.url = reverse("pore_analysis_team:upload_image", kwargs={"team_slug": self.team.slug})

    def _post_upload(self, upload_file, **extra_fields):
        payload = {
            "file": upload_file,
            "name": "Sample Upload",
            "description": "",
            "voxel_size": "",
            **extra_fields,
        }
        return self.client.post(self.url, payload, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def _make_npy_file(self, array, filename="sample.npy"):
        buffer = BytesIO()
        np.save(buffer, array, allow_pickle=False)
        return SimpleUploadedFile(filename, buffer.getvalue(), content_type="application/octet-stream")

    def _make_tiff_file(self, array, filename="sample.tiff"):
        buffer = BytesIO()
        iio.imwrite(buffer, array, extension=".tiff", plugin="tifffile")
        return SimpleUploadedFile(filename, buffer.getvalue(), content_type="image/tiff")

    def test_upload_npy_success(self):
        array = np.ones((5, 6, 7), dtype=bool)
        upload_file = self._make_npy_file(array)

        response = self._post_upload(upload_file)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertIn("redirect_url", body)
        self.assertEqual(UploadedImage.objects.count(), 1)
        image = UploadedImage.objects.first()
        self.assertEqual(image.dimensions, [5, 6, 7])

    def test_upload_raw_success(self):
        depth, height, width = 3, 4, 5
        raw = (np.arange(depth * height * width, dtype=np.uint16) % 17).tobytes()
        upload_file = SimpleUploadedFile("sample.raw", raw, content_type="application/octet-stream")

        response = self._post_upload(
            upload_file,
            raw_width=str(width),
            raw_height=str(height),
            raw_depth=str(depth),
            raw_dtype="uint16",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertEqual(UploadedImage.objects.count(), 1)
        image = UploadedImage.objects.first()
        self.assertEqual(image.dimensions, [depth, height, width])

    def test_upload_tiff_success(self):
        array = (np.arange(5 * 6 * 7, dtype=np.uint16) % 11).reshape((5, 6, 7))
        upload_file = self._make_tiff_file(array)

        response = self._post_upload(upload_file)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertEqual(UploadedImage.objects.count(), 1)

        image = UploadedImage.objects.first()
        self.assertEqual(image.dimensions, [5, 6, 7])
        self.assertTrue(image.file.name.endswith(".npy"))

        with image.file.open("rb") as handle:
            stored = np.load(handle, allow_pickle=False)

        np.testing.assert_array_equal(stored, array)

    def test_upload_raw_missing_metadata_fails(self):
        raw = b"\x00\x01\x02\x03"
        upload_file = SimpleUploadedFile("missing-meta.raw", raw, content_type="application/octet-stream")

        response = self._post_upload(upload_file, raw_width="2", raw_height="2", raw_dtype="uint8")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertIn("Depth is required", body["message"])
        self.assertEqual(UploadedImage.objects.count(), 0)

    def test_upload_raw_size_mismatch_fails(self):
        raw = b"\x00\x01\x02\x03\x04"
        upload_file = SimpleUploadedFile("bad-size.raw", raw, content_type="application/octet-stream")

        response = self._post_upload(
            upload_file,
            raw_width="2",
            raw_height="2",
            raw_depth="1",
            raw_dtype="uint8",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertIn("RAW size does not match dimensions/dtype", body["message"])
        self.assertEqual(UploadedImage.objects.count(), 0)

    def test_upload_stl_returns_coming_soon(self):
        upload_file = SimpleUploadedFile("mesh.stl", b"solid demo", content_type="model/stl")

        response = self._post_upload(upload_file)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertIn("coming soon", body["message"].lower())
        self.assertEqual(UploadedImage.objects.count(), 0)

    def test_upload_invalid_tiff_fails(self):
        upload_file = SimpleUploadedFile("broken.tiff", b"not-a-real-tiff", content_type="image/tiff")

        response = self._post_upload(upload_file)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertIn("Invalid TIFF file", body["message"])
        self.assertEqual(UploadedImage.objects.count(), 0)

    def test_upload_unsupported_extension_fails(self):
        upload_file = SimpleUploadedFile("not-allowed.txt", b"hello", content_type="text/plain")

        response = self._post_upload(upload_file)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertIn("Unsupported file extension", body["message"])
        self.assertEqual(UploadedImage.objects.count(), 0)
