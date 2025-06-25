from django.conf import settings
from django.conf.urls.static import static
from django.urls import path
from . import views

urlpatterns = [
    path('api/download/', views.index, name='index'),  # Home page for the downloader form
    path('', views.start_download, name='start_download'),
    path('api/download/status/<str:task_id>/', views.check_status, name='check_status'),
    path('api/download/file/<str:task_id>/', views.download_file, name='download_file'),
    ] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
