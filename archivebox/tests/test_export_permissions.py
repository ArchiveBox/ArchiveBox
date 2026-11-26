"""Export authorization through real API requests and native export processes."""

import json
from pathlib import Path

import pytest

from archivebox.api.models import APIToken
from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import ADMIN_TEST_HOST, run_python_cwd


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("authentication", ["anonymous", "session", "token"])
def test_metadata_export_preserves_identity_and_public_filters(client, admin_user, authentication):
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    snapshots = {
        permission: Snapshot.objects.create(
            url=f"https://news.ycombinator.com/{permission}",
            crawl=crawl,
            config={"PERMISSIONS": permission},
        )
        for permission in ("public", "unlisted", "private")
    }
    headers = {"HTTP_HOST": ADMIN_TEST_HOST}
    if authentication == "session":
        assert client.login(username=admin_user.username, password="testpassword")
    elif authentication == "token":
        headers["HTTP_X_ARCHIVEBOX_API_KEY"] = APIToken.objects.create(created_by=admin_user).token
    response = client.get("/api/v1/core/snapshots/export/jsonl", **headers)
    assert response.status_code == 200
    rows = [json.loads(row) for row in b"".join(response.streaming_content).splitlines()]
    expected = snapshots.values() if authentication != "anonymous" else [snapshots["public"]]
    assert {row["id"] for row in rows} == {str(snapshot.pk) for snapshot in expected}
    if authentication != "anonymous":
        assert response.wsgi_request.user.pk == admin_user.pk
    for query in (
        {"public_only": "1"},
        {"public_only": "1", "permissions": "private"},
        {"public_only": "1", "id__in": ",".join(str(snapshot.pk) for snapshot in snapshots.values())},
        {"public_only": "1", "q": "permissions:private OR permissions:unlisted"},
    ):
        response = client.get("/api/v1/core/snapshots/export/jsonl", query, **headers)
        assert response.status_code == 200, response.content if not response.streaming else response.status_code
        rows = [json.loads(row) for row in b"".join(response.streaming_content).splitlines()]
        assert {row["id"] for row in rows} <= {str(snapshots["public"].pk)}


def test_authenticated_public_export_jobs_and_session_csrf(initialized_archive):
    fixture = Path(__file__).parent / "fixtures/original-domain-replay"
    script = """
import os
from pathlib import Path
os.environ['DATA_DIR'] = str(Path.cwd())
import django
django.setup()
import gzip, io, json, zipfile
from django.contrib.auth import get_user_model
from django.conf import settings
from django.test import Client
from archivebox.api.models import APIToken
from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Process

user = get_user_model().objects.create_superuser(username='export-owner', password='export-owner')
other = get_user_model().objects.create_superuser(username='other-owner', password='other-owner')
token = APIToken.objects.create(created_by=user)
other_token = APIToken.objects.create(created_by=other)
crawl = Crawl.objects.create(urls='https://news.ycombinator.com/', created_by=user)
fixture = Path(FIXTURE_PATH)
saved = []
for index, record in enumerate(json.loads((fixture / 'captures.json').read_text())):
    body = gzip.decompress((fixture / record['file']).read_bytes())
    snapshot = Snapshot.objects.create(url=record['url'], crawl=crawl, config={'PERMISSIONS': ('public', 'unlisted', 'private')[index]})
    output = snapshot.output_dir / 'dom/output.html'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(body)
    ArchiveResult.objects.create(snapshot=snapshot, plugin='dom', status='succeeded', output_str='dom/output.html', output_files={'dom/output.html': {'size': len(body), 'mimetype': 'text/html'}})
    saved.append(snapshot)
client = Client(HTTP_HOST='api.archivebox.localhost:5797', enforce_csrf_checks=True)
headers = {'HTTP_X_ARCHIVEBOX_API_KEY': token.token}
jobs = []
for authentication in ('token', 'session'):
    if authentication == 'session':
        page = client.get('/admin/login/', HTTP_HOST='admin.archivebox.localhost:5797')
        assert page.status_code == 200, page.status_code
        assert client.login(username=user.username, password='export-owner')
        # API session POST must enforce the same CSRF check as admin exports.
        denied = client.post('/api/v1/core/snapshots/export/html_zip', '{}', content_type='application/json')
        assert denied.status_code == 403, denied.content
        headers = {'HTTP_X_CSRFTOKEN': client.cookies[settings.CSRF_COOKIE_NAME].value}
    response = client.post('/api/v1/core/snapshots/export/html_zip?public_only=1', '{}', content_type='application/json', **headers)
    assert response.status_code == 202, response.content
    job = response.json()
    process = Process.objects.get(pk=job['id'])
    assert '--public-only' in process.cmd and '--user' in process.cmd
    assert process.cmd[process.cmd.index('--user') + 1] == str(user.pk)
    assert process.wait(timeout=30) == 0, process.stderr_file.read_text()
    anonymous = Client(HTTP_HOST='api.archivebox.localhost:5797')
    for viewer in (client, anonymous):
        response = viewer.get(job['status_url'])
        assert response.status_code == 200, response.content
        response = viewer.get(job['download_url'])
        assert response.status_code == 200, (response.content if not response.streaming else response.status_code, list(Snapshot.objects.values_list('pk','permissions')), viewer.get(job['status_url']).json(), process.cmd)
        with zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content))) as bundle:
            assert [row['url'] for row in json.loads(bundle.read('pages.json'))] == [saved[0].url]
            links = bundle.read('archivebox-links.js')
            assert all(snapshot.url.encode() not in links for snapshot in saved[1:])
        response.close()
    assert anonymous.post(job['cancel_url']).status_code == 403
    jobs.append(job)
# Session creation without public_only must retain its owner and private selection.
response = client.post('/api/v1/core/snapshots/export/html_zip', '{}', content_type='application/json', **headers)
assert response.status_code == 202, response.content
private = response.json()
process = Process.objects.get(pk=private['id'])
assert '--public-only' not in process.cmd
assert process.wait(timeout=30) == 0, process.stderr_file.read_text()
assert anonymous.get(private['status_url']).status_code == 403
assert anonymous.get(private['download_url'], HTTP_X_ARCHIVEBOX_API_KEY=other_token.token).status_code == 403
assert client.get(private['status_url']).status_code == 200
user.is_active = False
user.save(update_fields=['is_active'])
assert anonymous.get(private['download_url'], HTTP_X_ARCHIVEBOX_API_KEY=token.token).status_code == 401
saved[0].config = {'PERMISSIONS': 'private'}
saved[0].save(update_fields=['config'])
for job in jobs:
    response = anonymous.get(job['download_url'])
    assert response.status_code == 409, response.content
print('export-permissions-ok')
""".replace("FIXTURE_PATH", repr(str(fixture)))
    stdout, stderr, code = run_python_cwd(script, cwd=initialized_archive, timeout=90)
    assert code == 0, stdout + stderr
    assert "export-permissions-ok" in stdout
