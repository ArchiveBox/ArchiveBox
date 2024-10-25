Pocket
======
[![CircleCI](https://img.shields.io/circleci/build/github/tapanpandita/pocket/master?logo=CircleCI)](https://circleci.com/gh/tapanpandita/pocket)
[![Pypi](https://img.shields.io/pypi/v/pocket.svg)](https://pypi.python.org/pypi/pocket)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/pocket.svg)](https://pypi.python.org/pypi/pocket)
![GitHub](https://img.shields.io/github/license/tapanpandita/pocket.svg)


A python wrapper for the [pocket api](http://getpocket.com/api/docs).

Installation
------------
```
pip install pocket
```

Usage
------

You'll need your pocket consumer key. You can find this from your account page.
You will also need the access token for the account you want to modify.
Then, you need to create an instance of the pocket object

```python
import pocket

pocket_instance = pocket.Pocket(consumer_key, access_token)
```

### Chaining Modify Methods

All the modify methods can be chained together for creating one bulk query. If you don't wish to chain the methods, just pass `wait=False`.

```python
import pocket

pocket_instance = pocket.Pocket(consumer_key, access_token)

# perfoms all these actions in one request
# NOTE: Each individual method returns the instance itself. The response
# dictionary is not returned till commit is called on the instance.
response, headers = pocket_instance.archive(item_id1).archive(item_id2).favorite(item_id3).delete(item_id4).commit()

# performs action immediately and returns a dictionary
pocket_instance.archive(item_id1, wait=False)
```

### OAUTH

To get request token, use the get_request_token class method. To get the access token use the get_access_token method.

```python
from pocket import Pocket

request_token = Pocket.get_request_token(consumer_key=consumer_key, redirect_uri=redirect_uri)

# URL to redirect user to, to authorize your app
auth_url = Pocket.get_auth_url(code=request_token, redirect_uri=redirect_uri)
# e.g. import subprocess; subprocess.run(['xdg-open', auth_url])

user_credentials = Pocket.get_credentials(consumer_key=consumer_key, code=request_token)

access_token = user_credentials['access_token']
```

For detailed documentation of the methods available, please visit the official [pocket api documentation](http://getpocket.com/api/docs).
