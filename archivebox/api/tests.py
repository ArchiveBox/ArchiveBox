__package__ = 'archivebox.api'

# from django.test import TestCase
# from ninja.testing import TestClient

# from .routes_cli import router

# class ArchiveBoxCLIAPITestCase(TestCase):
#     def setUp(self):
#         self.client = TestClient(router)

#     def test_add_endpoint(self):
#         response = self.client.post("/add", json={"urls": ["http://example.com"], "tag": "testTag1,testTag2"})
#         self.assertEqual(response.status_code, 200)
#         self.assertTrue(response.json()["success"])

#     def test_remove_endpoint(self):
#         response = self.client.post("/remove", json={"filter_patterns": ["http://example.com"]})
#         self.assertEqual(response.status_code, 200)
#         self.assertTrue(response.json()["success"])

#     def test_update_endpoint(self):
#         response = self.client.post("/update", json={})
#         self.assertEqual(response.status_code, 200)
#         self.assertTrue(response.json()["success"])

#     def test_list_all_endpoint(self):
#         response = self.client.post("/list_all", json={})
#         self.assertEqual(response.status_code, 200)
#         self.assertTrue(response.json()["success"])
