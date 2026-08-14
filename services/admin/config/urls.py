"""URL configuration for RT-FADS Admin control plane."""

from django.contrib import admin
from django.urls import path

urlpatterns = [
    path('admin/', admin.site.urls),
]
