from django.test import TestCase

# Create your tests here.


class CrawlActorTest(TestCase):

    def test_crawl_creation(self):
        seed = Seed.objects.create(uri='https://example.com')
        Event.dispatch('CRAWL_CREATE', {'seed_id': seed.id})
        
        crawl_actor = CrawlActor()
        
        output_events = list(crawl_actor.process_next_event())
        
        assert len(output_events) == 1
        assert output_events[0].get('name', 'unset') == 'FS_WRITE'
        assert output_events[0].get('path') == '/tmp/test_crawl/index.json'

        output_events = list(crawl_actor.process_next_event())
        assert len(output_events) == 1
        assert output_events[0].get('name', 'unset') == 'CRAWL_CREATED'
        
        assert Crawl.objects.filter(seed_id=seed.id).exists(), 'Crawl was not created'

