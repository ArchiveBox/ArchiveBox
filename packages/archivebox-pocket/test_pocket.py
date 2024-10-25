import unittest
import pocket
from mock import patch


class PocketTest(unittest.TestCase):

    def setUp(self):
        self.consumer_key = 'consumer_key'
        self.access_token = 'access_token'

    def tearDown(self):
        pass

    def test_pocket_init(self):
        pocket_instance = pocket.Pocket(
            self.consumer_key,
            self.access_token,
        )

        self.assertEqual(self.consumer_key, pocket_instance.consumer_key)
        self.assertEqual(self.access_token, pocket_instance.access_token)

    def test_pocket_init_payload(self):
        pocket_instance = pocket.Pocket(
            self.consumer_key,
            self.access_token,
        )
        expected_payload = {
            'consumer_key': self.consumer_key,
            'access_token': self.access_token,
        }

        self.assertEqual(expected_payload, pocket_instance._payload)

    def test_post_request(self):
        mock_payload = {
            'consumer_key': self.consumer_key,
            'access_token': self.access_token,
        }
        mock_url = 'https://getpocket.com/v3/'
        mock_headers = {
            'content-type': 'application/json',
        }

        with patch('pocket.requests') as mock_requests:
            pocket.Pocket._post_request(mock_url, mock_payload, mock_headers)
            mock_requests.post.assert_called_once_with(
                mock_url,
                data=mock_payload,
                headers=mock_headers,
            )
