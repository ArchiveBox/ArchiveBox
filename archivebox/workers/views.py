
from django.views.generic import TemplateView
from django.contrib.auth.mixins import UserPassesTestMixin
from django.utils import timezone
from api.auth import get_or_create_api_token


class JobsDashboardView(UserPassesTestMixin, TemplateView):
    template_name = "jobs_dashboard.html"


    def test_func(self):
        return self.request.user and self.request.user.is_superuser

    def get_context_data(self, **kwargs):
        api_token = get_or_create_api_token(self.request.user)
        context = super().get_context_data(**kwargs)
        context['api_token'] = api_token.token if api_token else 'UNABLE TO GENERATE API TOKEN'
        context['now'] = timezone.now().strftime("%H:%M:%S")
        return context
