from django.urls import path

from .views import GalleryDLIconView, GalleryDLEmbedView, GalleryDLOutputView, GalleryDLDependencyView, GalleryDLExtractorView

urlpatterns = [
	path('/plugins/gallerydl/icon/<path:path>', GalleryDLIconView(.as_view), name='gallerydl_icon'),
	path('/plugins/gallerydl/embed/<path:path>', GalleryDLEmbedView.as_view(), name='gallerydl_embed'),
	path('/plugins/gallerydl/output/<path:path>', GalleryDLOutputView.as_view(), name='gallerydl_output'),

	path('/plugins/gallerydl/dependency/', GalleryDLDependencyView.as_view(), name='gallerydl_dependency'),
	path('/plugins/gallerydl/extractor/', GalleryDLExtractorView.as_view(), name='gallerydl_extractor'),
]
