from django.shortcuts import render

from django.views import View

from legacy.config import OUTPUT_DIR
from legacy.index import load_main_index, load_main_index_meta


class MainIndex(View):
    template = 'main_index.html'

    def get(self, request):
        all_links = load_main_index(out_dir=OUTPUT_DIR)
        meta_info = load_main_index_meta(out_dir=OUTPUT_DIR)

        context = {
            'updated': meta_info['updated'],
            'num_links': meta_info['num_links'],
            'links': all_links,
        }

        return render(template_name=self.template, request=request, context=context)


class AddLinks(View):
    template = 'add_links.html'

    def get(self, request):
        context = {}

        return render(template_name=self.template, request=request, context=context)


    def post(self, request):
        import_path = request.POST['url']
        
        # TODO: add the links to the index here using archivebox.legacy.main.update_archive_data
        print(f'Adding URL: {import_path}')

        return render(template_name=self.template, request=request, context={})


class LinkDetails(View):
    template = 'link_details.html'

    def get(self, request):
        return render(template_name=self.template, request=request, context={})
