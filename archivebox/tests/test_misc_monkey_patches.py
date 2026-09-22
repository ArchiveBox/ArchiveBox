import datetime
import io


def test_daphne_access_log_redacts_sensitive_query_params():
    from archivebox.misc.monkey_patches import ModifiedAccessLogGenerator

    stream = io.StringIO()
    logger = ModifiedAccessLogGenerator(stream)

    logger.write_entry(
        host="127.0.0.1:54321",
        date=datetime.datetime(2026, 5, 29, 12, 0, 0),
        request="GET /api/v1/crawls/crawl/a1000000-0000-0000-0000-00000003cea2?api_key=d837c273f6e8f4950e706ebd67d95889&limit=1",
        status=200,
    )

    output = stream.getvalue()
    assert "api_key=[REDACTED]" in output
    assert "d837c273f6e8f4950e706ebd67d95889" not in output
    assert "limit=1" in output
