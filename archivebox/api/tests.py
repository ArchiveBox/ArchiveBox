from django.test import TestCase
from ninja.testing import TestClient
from archivebox.api.archive import router as archive_router

class ArchiveBoxAPITestCase(TestCase):
    def setUp(self):
        self.client = TestClient(archive_router)

    def test_add_endpoint(self):
        response = self.client.post("/add", json={"urls": ["http://example.com"], "tag": "test"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")

    def test_remove_endpoint(self):
        response = self.client.post("/remove", json={"filter_patterns": ["http://example.com"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")

    def test_update_endpoint(self):
        response = self.client.post("/update", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")

    def test_list_all_endpoint(self):
        response = self.client.post("/list_all", json={})
        self.assertEqual(response.status_code, 200)
        self.assertTrue("success" in response.json()["status"])