from django.urls import path

from .views import ReplayWebPageViewer

urlpatterns = [
	path('<path:path>', ReplayWebPageViewer.as_view(), name='plugin_replaywebpage__viewer'),
]