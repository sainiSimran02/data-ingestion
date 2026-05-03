from django.urls import path
from ingestion.views import StoreUploadView, UserUploadView, PJPUploadView, StatusView

urlpatterns = [
    path('upload/stores/', StoreUploadView.as_view(), name='upload-stores'),
    path('upload/users/',  UserUploadView.as_view(),  name='upload-users'),
    path('upload/pjp/',    PJPUploadView.as_view(),   name='upload-pjp'),
    path('status/',        StatusView.as_view(),       name='status'),
]