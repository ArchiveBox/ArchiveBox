import pytest

# =============================================================================
# End-to-end integration tests
# =============================================================================


@pytest.mark.django_db
def test_login_page_returns_200(client):
    response = client.get("/accounts/login/")
    assert response.status_code == 200
    assert b"Log in" in response.content


@pytest.mark.django_db
def test_signup_page_returns_200(client, settings, monkeypatch):
    settings.ACCOUNT_ADAPTER = "archivebox.auth.adapters.ArchiveBoxAccountAdapter"
    import archivebox.auth.adapters as m

    monkeypatch.setattr(m, "_get_registration_enabled", lambda: True)
    monkeypatch.setattr(m, "_get_registration_mode", lambda: "open")
    response = client.get("/accounts/signup/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_admin_login_redirects_to_allauth(client, django_user_model):
    django_user_model.objects.create_superuser(username="admin", email="admin@example.com", password="testpassword123")
    response = client.get("/admin/login/")
    assert response.status_code == 200
    content = response.content.decode()
    assert "/accounts/login/" in content


@pytest.mark.django_db
def test_admin_login_preserves_first_admin_setup(client):
    response = client.get("/admin/login/")
    assert response.status_code == 200
    content = response.content.decode()
    assert 'id="first-admin-form"' in content
    assert "Create admin and continue" in content


@pytest.mark.django_db
def test_email_password_login_works(client, django_user_model, monkeypatch):
    # Disable subdomain routing so AdminCookieIsolationMiddleware does not
    # strip the session cookie from responses issued to the test client's
    # default "testserver" host.
    from archivebox.config.common import get_config

    config = get_config()
    monkeypatch.setattr(type(config), "USES_SUBDOMAIN_ROUTING", property(lambda self: False))

    user = django_user_model.objects.create_user(
        username="logintest",
        email="logintest@example.com",
        password="testpassword123",
    )
    from allauth.account.models import EmailAddress

    EmailAddress.objects.create(
        user=user,
        email="logintest@example.com",
        primary=True,
        verified=True,
    )
    response = client.post(
        "/accounts/login/",
        {
            "login": "logintest@example.com",
            "password": "testpassword123",
        },
        follow=True,
    )
    assert response.status_code == 200
    assert response.wsgi_request.user.is_authenticated


@pytest.mark.django_db
def test_registration_mode_approval_creates_inactive_user(client, settings, monkeypatch):
    settings.ACCOUNT_ADAPTER = "archivebox.auth.adapters.ArchiveBoxAccountAdapter"
    import archivebox.auth.adapters as m

    monkeypatch.setattr(m, "_get_registration_enabled", lambda: True)
    monkeypatch.setattr(m, "_get_registration_mode", lambda: "approval")
    client.post(
        "/accounts/signup/",
        {
            "email": "newuser@example.com",
            "password1": "ComplexPass999!",
            "password2": "ComplexPass999!",
        },
    )
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.filter(email="newuser@example.com").first()
    assert user is not None
    assert user.is_active is False


# =============================================================================
# Adapter unit tests
# =============================================================================


@pytest.mark.django_db
def test_account_adapter_closed_when_registration_disabled(monkeypatch):
    import archivebox.auth.adapters as m

    monkeypatch.setattr(m, "_get_registration_enabled", lambda: False)
    from django.test import RequestFactory

    from archivebox.auth.adapters import ArchiveBoxAccountAdapter

    adapter = ArchiveBoxAccountAdapter()
    request = RequestFactory().get("/accounts/signup/")
    assert adapter.is_open_for_signup(request) is False


@pytest.mark.django_db
def test_account_adapter_open_by_default(monkeypatch):
    import archivebox.auth.adapters as m

    monkeypatch.setattr(m, "_get_registration_enabled", lambda: True)
    monkeypatch.setattr(m, "_get_registration_mode", lambda: "open")
    from django.test import RequestFactory

    from archivebox.auth.adapters import ArchiveBoxAccountAdapter

    adapter = ArchiveBoxAccountAdapter()
    request = RequestFactory().get("/accounts/signup/")
    assert adapter.is_open_for_signup(request) is True


@pytest.mark.django_db
def test_signal_assigns_admin_permissions(monkeypatch):
    from django.contrib.auth import get_user_model

    import archivebox.auth.signals as s
    from archivebox.auth.signals import _apply_default_permissions

    User = get_user_model()
    user = User.objects.create_user(username="testuser100", password="pass")
    monkeypatch.setattr(s, "_get_default_permissions", lambda: "admin")
    _apply_default_permissions(user)
    user.refresh_from_db()
    assert user.is_superuser is True
    assert user.is_staff is True


@pytest.mark.django_db
def test_signal_none_permissions_adds_no_group(monkeypatch):
    from django.contrib.auth import get_user_model

    import archivebox.auth.signals as s
    from archivebox.auth.signals import _apply_default_permissions

    User = get_user_model()
    user = User.objects.create_user(username="testuser101", password="pass")
    monkeypatch.setattr(s, "_get_default_permissions", lambda: "none")
    _apply_default_permissions(user)
    assert user.groups.count() == 0
    user.refresh_from_db()
    assert user.is_superuser is False
