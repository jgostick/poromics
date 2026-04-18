#!/usr/bin/env python
"""
Create a test numpy array file for upload testing.
"""
import numpy as np

# Create a simple 3D boolean array representing a pore structure
test_array = np.random.choice([True, False], size=(50, 50, 50), p=[0.3, 0.7])

# Save it as a .npy file
np.save("test_upload.npy", test_array)

print(f"Created test_upload.npy with shape {test_array.shape} and dtype {test_array.dtype}")
print(f"True values (pores): {np.sum(test_array)} / {test_array.size} ({100*np.sum(test_array)/test_array.size:.1f}%)")