"""An HTTP response owns its payload even outside body iteration."""

import asyncio
import os

import psutil
import pytest
from django.test import AsyncRequestFactory, RequestFactory

from archivebox.misc.serve_static import RangedFileReader, serve_static_with_byterange_support


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("asgi", [False, True])
@pytest.mark.parametrize("consumed_chunks", [0, 1, 3])
def test_file_response_close_releases_payload(tmp_path, asgi, consumed_chunks):
    payload = tmp_path / "payload.bin"
    data = os.urandom(RangedFileReader.block_size * 3)
    payload.write_bytes(data)
    request = (AsyncRequestFactory() if asgi else RequestFactory()).get("/payload.bin")
    response = serve_static_with_byterange_support(request, "payload.bin", document_root=tmp_path)
    assert response.status_code == 200
    assert response.streaming
    process = psutil.Process(os.getpid())

    def assert_closed(chunks):
        assert b"".join(chunks) == data[: consumed_chunks * RangedFileReader.block_size]
        response.close()
        # Disconnects can arrive before the first byte, midway through a file,
        # or after its last chunk but before the next iteration observes EOF.
        # Keep response/iterator references alive so GC cannot hide bad cleanup.
        assert str(payload) not in {file.path for file in process.open_files()}

    if asgi:

        async def check_async():
            iterator = response.streaming_content
            try:
                chunks = [await anext(iterator) for _ in range(consumed_chunks)]
                assert_closed(chunks)
            finally:
                await iterator.aclose()
                response.close()

        asyncio.run(check_async())
    else:
        iterator = iter(response.streaming_content)
        try:
            assert_closed([next(iterator) for _ in range(consumed_chunks)])
        finally:
            response.close()
