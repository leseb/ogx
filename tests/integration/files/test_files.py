# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

import json
import os
from io import BytesIO
from unittest.mock import patch

import pytest
import requests
from openai import OpenAI

from ogx.core.datatypes import User
from ogx_api import OpenAIFilePurpose

purpose = OpenAIFilePurpose.ASSISTANTS


@pytest.fixture()
def provider_type_is_openai(ogx_client):
    providers = [provider for provider in ogx_client.providers.list() if provider.api == "files"]
    assert len(providers) == 1, "Expected exactly one files provider"
    return providers[0].provider_type == "remote::openai"


# a fixture to skip all these tests if a files provider is not available
@pytest.fixture(autouse=True)
def skip_if_no_files_provider(ogx_client):
    if not [provider for provider in ogx_client.providers.list() if provider.api == "files"]:
        pytest.skip("No files providers found")


def test_openai_client_basic_operations(openai_client, provider_type_is_openai):
    """Test basic file operations through OpenAI client."""
    from openai import NotFoundError

    client = openai_client

    test_content = b"files test content"

    uploaded_file = None

    try:
        # Upload file using OpenAI client
        with BytesIO(test_content) as file_buffer:
            file_buffer.name = "openai_test.txt"
            uploaded_file = client.files.create(file=file_buffer, purpose=purpose)

        # Verify basic response structure
        assert uploaded_file.id.startswith("file-")
        assert hasattr(uploaded_file, "filename")
        assert uploaded_file.filename == "openai_test.txt"

        # List files
        files_list = client.files.list()
        file_ids = [f.id for f in files_list.data]
        assert uploaded_file.id in file_ids

        # Retrieve file info
        retrieved_file = client.files.retrieve(uploaded_file.id)
        assert retrieved_file.id == uploaded_file.id

        # Retrieve file content
        # OpenAI provider does not allow content retrieval with many `purpose` values
        if not provider_type_is_openai:
            content_response = client.files.content(uploaded_file.id)
            assert content_response.content == test_content

        # Delete file
        delete_response = client.files.delete(uploaded_file.id)
        assert delete_response.deleted is True

        # Retrieve file should fail
        with pytest.raises(NotFoundError):
            client.files.retrieve(uploaded_file.id)

        # File should not be found in listing
        files_list = client.files.list()
        file_ids = [f.id for f in files_list.data]
        assert uploaded_file.id not in file_ids

        # Double delete should fail
        with pytest.raises(NotFoundError):
            client.files.delete(uploaded_file.id)

    finally:
        # Cleanup in case of failure
        if uploaded_file is not None:
            try:
                client.files.delete(uploaded_file.id)
            except NotFoundError:
                pass  # ignore 404


@pytest.mark.xfail(message="expires_after not available on all providers")
def test_expires_after(openai_client):
    """Test uploading a file with expires_after parameter."""
    client = openai_client

    uploaded_file = None
    try:
        with BytesIO(b"expires_after test") as file_buffer:
            file_buffer.name = "expires_after.txt"
            uploaded_file = client.files.create(
                file=file_buffer,
                purpose=purpose,
                expires_after={"anchor": "created_at", "seconds": 4545},
            )

        assert uploaded_file.expires_at is not None
        assert uploaded_file.expires_at == uploaded_file.created_at + 4545

        listed = client.files.list()
        ids = [f.id for f in listed.data]
        assert uploaded_file.id in ids

        retrieved = client.files.retrieve(uploaded_file.id)
        assert retrieved.id == uploaded_file.id

    finally:
        if uploaded_file is not None:
            try:
                client.files.delete(uploaded_file.id)
            except Exception:
                pass


@pytest.mark.xfail(message="expires_after not available on all providers")
def test_expires_after_requests(openai_client):
    """Upload a file using requests multipart/form-data and bracketed expires_after fields.

    This ensures clients that send form fields like `expires_after[anchor]` and
    `expires_after[seconds]` are handled by the server.
    """
    base_url = f"{openai_client.base_url}files"

    uploaded_id = None
    try:
        files = {"file": ("expires_after_with_requests.txt", BytesIO(b"expires_after via requests"))}
        data = {
            "purpose": str(purpose),
            "expires_after[anchor]": "created_at",
            "expires_after[seconds]": "4545",
        }

        session = requests.Session()
        request = requests.Request("POST", base_url, files=files, data=data)
        prepared = session.prepare_request(request)
        resp = session.send(prepared, timeout=30)
        resp.raise_for_status()
        result = resp.json()

        assert result.get("id", "").startswith("file-")
        uploaded_id = result["id"]
        assert result.get("created_at") is not None
        assert result.get("expires_at") == result["created_at"] + 4545

        list_resp = requests.get(base_url, timeout=30)
        list_resp.raise_for_status()
        listed = list_resp.json()
        ids = [f["id"] for f in listed.get("data", [])]
        assert uploaded_id in ids

        retrieve_resp = requests.get(f"{base_url}/{uploaded_id}", timeout=30)
        retrieve_resp.raise_for_status()
        retrieved = retrieve_resp.json()
        assert retrieved["id"] == uploaded_id

    finally:
        if uploaded_id:
            try:
                requests.delete(f"{base_url}/{uploaded_id}", timeout=30)
            except Exception:
                pass


def _files_auth_enabled() -> bool:
    return bool(os.environ.get("ALICE_TOKEN") or os.environ.get("BOB_TOKEN"))


@pytest.mark.integration
@pytest.mark.skipif(not _files_auth_enabled(), reason="Auth tokens not configured (set ALICE_TOKEN and BOB_TOKEN)")
class TestFilesAuthenticationIsolation:
    """Test user isolation for the files API using real HTTP auth tokens.

    Requires ALICE_TOKEN and BOB_TOKEN environment variables with valid
    auth tokens for two users with non-overlapping attributes.
    """

    @pytest.fixture
    def alice_client(self, openai_client, request):
        token = os.environ.get("ALICE_TOKEN", "token-alice")
        default_headers = {
            "X-OGX-Provider-Data": json.dumps({"__test_id": request.node.nodeid}),
        }
        return OpenAI(
            base_url=str(openai_client.base_url),
            api_key=token,
            default_headers=default_headers,
            max_retries=0,
            timeout=60.0,
        )

    @pytest.fixture
    def bob_client(self, openai_client, request):
        token = os.environ.get("BOB_TOKEN", "token-bob")
        default_headers = {
            "X-OGX-Provider-Data": json.dumps({"__test_id": request.node.nodeid}),
        }
        return OpenAI(
            base_url=str(openai_client.base_url),
            api_key=token,
            default_headers=default_headers,
            max_retries=0,
            timeout=60.0,
        )

    def test_user_cannot_list_other_users_files(self, alice_client, bob_client):
        """Alice's files should not appear in Bob's file listing."""
        test_content = b"Alice's private file content"

        with BytesIO(test_content) as file_buffer:
            file_buffer.name = "alice_file.txt"
            alice_file = alice_client.files.create(file=file_buffer, purpose=purpose)

        try:
            alice_files = alice_client.files.list()
            alice_file_ids = [f.id for f in alice_files.data]
            assert alice_file.id in alice_file_ids

            bob_files = bob_client.files.list()
            bob_file_ids = [f.id for f in bob_files.data]
            assert alice_file.id not in bob_file_ids
        finally:
            try:
                alice_client.files.delete(alice_file.id)
            except Exception:
                pass

    def test_user_cannot_retrieve_other_users_file(self, alice_client, bob_client):
        """Bob should get an error when retrieving Alice's file."""
        test_content = b"Alice's private file content"

        with BytesIO(test_content) as file_buffer:
            file_buffer.name = "alice_file.txt"
            alice_file = alice_client.files.create(file=file_buffer, purpose=purpose)

        try:
            retrieved = alice_client.files.retrieve(alice_file.id)
            assert retrieved.id == alice_file.id

            with pytest.raises(Exception) as exc_info:
                bob_client.files.retrieve(alice_file.id)
            assert exc_info.value.status_code in (400, 403, 404)
        finally:
            try:
                alice_client.files.delete(alice_file.id)
            except Exception:
                pass

    def test_user_cannot_delete_other_users_file(self, alice_client, bob_client):
        """Bob should not be able to delete Alice's file."""
        test_content = b"Alice's private file content"

        with BytesIO(test_content) as file_buffer:
            file_buffer.name = "alice_file.txt"
            alice_file = alice_client.files.create(file=file_buffer, purpose=purpose)

        try:
            with pytest.raises(Exception) as exc_info:
                bob_client.files.delete(alice_file.id)
            assert exc_info.value.status_code in (400, 403, 404)

            retrieved = alice_client.files.retrieve(alice_file.id)
            assert retrieved.id == alice_file.id
        finally:
            try:
                alice_client.files.delete(alice_file.id)
            except Exception:
                pass


@patch("ogx.core.storage.sqlstore.authorized_sqlstore.get_authenticated_user")
def test_files_authentication_shared_attributes(mock_get_authenticated_user, ogx_client, provider_type_is_openai):
    """Test access control with users having identical attributes."""
    client = ogx_client

    # Create users with identical attributes (required for default policy)
    user_a = User("user-a", {"roles": ["user"], "teams": ["shared-team"]})
    user_b = User("user-b", {"roles": ["user"], "teams": ["shared-team"]})

    # User A uploads a file
    mock_get_authenticated_user.return_value = user_a
    test_content = b"Shared attributes file content"

    with BytesIO(test_content) as file_buffer:
        file_buffer.name = "shared_attributes_file.txt"
        shared_file = client.files.create(file=file_buffer, purpose=purpose)

    try:
        # User B with identical attributes can access the file
        mock_get_authenticated_user.return_value = user_b
        files_list = client.files.list()
        file_ids = [f.id for f in files_list.data]

        # User B should be able to see the file due to identical attributes
        assert shared_file.id in file_ids

        # User B can retrieve file info
        retrieved_file = client.files.retrieve(shared_file.id)
        assert retrieved_file.id == shared_file.id

        # User B can access file content
        if not provider_type_is_openai:
            content_response = client.files.content(shared_file.id)
            if isinstance(content_response, str):
                content = bytes(content_response, "utf-8")
            else:
                content = content_response.content
            assert content == test_content

        # Cleanup
        mock_get_authenticated_user.return_value = user_a
        client.files.delete(shared_file.id)

    except Exception as e:
        # Cleanup in case of failure
        try:
            mock_get_authenticated_user.return_value = user_a
            client.files.delete(shared_file.id)
        except Exception:
            pass
        try:
            mock_get_authenticated_user.return_value = user_b
            client.files.delete(shared_file.id)
        except Exception:
            pass
        raise e


@patch("ogx.core.storage.sqlstore.authorized_sqlstore.get_authenticated_user")
def test_files_authentication_anonymous_access(mock_get_authenticated_user, ogx_client, provider_type_is_openai):
    client = ogx_client

    # Simulate anonymous user (no authentication)
    mock_get_authenticated_user.return_value = None

    test_content = b"Anonymous file content"

    with BytesIO(test_content) as file_buffer:
        file_buffer.name = "anonymous_file.txt"
        anonymous_file = client.files.create(file=file_buffer, purpose=purpose)

    try:
        # Anonymous user should be able to access their own uploaded file
        files_list = client.files.list()
        file_ids = [f.id for f in files_list.data]
        assert anonymous_file.id in file_ids

        # Can retrieve file info
        retrieved_file = client.files.retrieve(anonymous_file.id)
        assert retrieved_file.id == anonymous_file.id

        # Can access file content
        if not provider_type_is_openai:
            content_response = client.files.content(anonymous_file.id)
            if isinstance(content_response, str):
                content = bytes(content_response, "utf-8")
            else:
                content = content_response.content
            assert content == test_content

        # Can delete the file
        delete_response = client.files.delete(anonymous_file.id)
        assert delete_response.deleted is True

    except Exception as e:
        # Cleanup in case of failure
        try:
            client.files.delete(anonymous_file.id)
        except Exception:
            pass
        raise e
