#!/usr/bin/env python
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'poromics.settings')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()
users = User.objects.filter(email='test@example.com')
print(f"Found {users.count()} users with email test@example.com")

for user in users:
    user.set_password('testpass123')
    user.save()
    print(f"Password set for user: {user.email} (ID: {user.id})")
    
# Also list all users
print("All users:")
for user in User.objects.all():
    print(f"  - {user.email} (ID: {user.id}, superuser: {user.is_superuser})")