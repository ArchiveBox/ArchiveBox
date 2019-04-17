from django.shortcuts import render

from django.views import View


class MainIndex(View):
    template = 'main_index.html'

    def get(self, request):
        return render(self.template, {})


class LinkDetails(View):
    template = 'link_details.html'

    def get(self, request):
        return render(self.template, {})
