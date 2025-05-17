import os
import unittest
from unittest.mock import patch, MagicMock
import time
import requests_mock # For mocking HTTP requests
from piper_sdk.client import (
    PiperClient, 
    PiperLinkNeededError, 
    PiperConfigError, 
    PiperAuthError, 
    PiperRawSecretExchangeError,
    PiperGrantNeededError # If you want to test this path specifically
)
import logging

# Configure basic logging to see SDK messages
logging.basicConfig(level=logging.DEBUG) # Use DEBUG to see more SDK internal logs
logger = logging.getLogger("QuickSDKTest_v040")

# --- Configuration ---
TEST_AGENT_CLIENT_ID = os.environ.get("PIPER_TEST_AGENT_CLIENT_ID", "test_agent_id_123")
TEST_AGENT_CLIENT_SECRET = os.environ.get("PIPER_TEST_AGENT_CLIENT_SECRET", "test_agent_secret_abc")

# Mock URLs (these won't actually be called if we mock at the right level)
MOCK_TOKEN_URL = "https://mock.piper.com/token"
MOCK_RESOLVE_URL = "https://mock.piper.com/resolve"
MOCK_GET_SCOPED_URL = "https://mock.piper.com/getscoped"
MOCK_EXCHANGE_SECRET_URL = "https://mock.piper.com/exchangesecret" # Our new GCF URL

KNOWN_INSTANCE_ID = "test-instance-id-789"
KNOWN_CREDENTIAL_ID = "cred-id-abc-123"
KNOWN_VARIABLE_NAME = "MyTestApiKey"
MOCK_STS_TOKEN = "mock_sts_token_value_qwerty"
MOCK_RAW_SECRET = "actual_secret_value_for_my_test_api_key"

class TestPiperSDKRawSecretFetch(unittest.TestCase):

    def setUp(self):
        # Reset any shared state if necessary, though PiperClient is usually instantiated per test
        pass

    def _get_mock_piper_client(self, exchange_url=None, instance_id_at_init=None, auto_discover=False):
        # Disable actual discovery for most tests by default, unless testing discovery itself
        return PiperClient(
            client_id=TEST_AGENT_CLIENT_ID,
            client_secret=TEST_AGENT_CLIENT_SECRET,
            token_url=MOCK_TOKEN_URL,
            resolve_mapping_url=MOCK_RESOLVE_URL,
            get_scoped_url=MOCK_GET_SCOPED_URL,
            piper_link_service_url="http://localhost:0", # Non-existent to ensure discovery fails if attempted
            piper_link_instance_id=instance_id_at_init,
            auto_discover_instance_id=auto_discover, # Control discovery for specific tests
            exchange_secret_url=exchange_url
        )

    @requests_mock.Mocker() # Decorator for requests_mock
    def test_01_fetch_raw_secret_success(self, m):
        logger.info("--- Test 01: Fetch Raw Secret - SUCCESS ---")
        client = self._get_mock_piper_client(exchange_url=MOCK_EXCHANGE_SECRET_URL, instance_id_at_init=KNOWN_INSTANCE_ID)

        # 1. Mock response for _fetch_agent_token (for resolve_mapping_url)
        m.post(MOCK_TOKEN_URL, json={'access_token': 'jwt_for_resolve', 'expires_in': 3600}, status_code=200)
        # 2. Mock response for _resolve_piper_variable
        m.post(MOCK_RESOLVE_URL, json={'credentialId': KNOWN_CREDENTIAL_ID}, status_code=200)
        # 3. Mock response for _fetch_agent_token (for get_scoped_url)
        # requests_mock needs distinct matchers if URL is same but payload/purpose differs, or use different URLs
        # For simplicity, assume token URL is called again and gets a new token (or same if audience is same)
        # The SDK's _get_valid_agent_token handles caching if audience is same.
        # We are mocking the HTTP call that _fetch_agent_token makes.
        # Let's assume _get_valid_agent_token will be called twice for different audiences
        # The first call to MOCK_TOKEN_URL is for resolve, second for get_scoped, third for exchange
        m.post(MOCK_TOKEN_URL, json={'access_token': 'jwt_for_get_scoped', 'expires_in': 3600}, status_code=200) # For get_scoped
        # 4. Mock response for _fetch_piper_sts_token
        m.post(MOCK_GET_SCOPED_URL, json={
            'access_token': MOCK_STS_TOKEN, 
            'expires_in': 900, 
            'granted_credential_ids': [KNOWN_CREDENTIAL_ID]
        }, status_code=200)
        
        # 5. Mock response for _fetch_agent_token (for exchange_secret_url)
        m.post(MOCK_TOKEN_URL, json={'access_token': 'jwt_for_exchange', 'expires_in': 3600}, status_code=200) # For exchange
        # 6. Mock response for the exchange_secret_url call
        m.post(MOCK_EXCHANGE_SECRET_URL, json={
            'piper_credential_id': KNOWN_CREDENTIAL_ID,
            'secret_value': MOCK_RAW_SECRET
        }, status_code=200)

        secret_info = client.get_secret(KNOWN_VARIABLE_NAME, fetch_raw_secret=True)
        
        self.assertIsNotNone(secret_info)
        self.assertEqual(secret_info.get('source'), 'piper_raw_secret')
        self.assertEqual(secret_info.get('value'), MOCK_RAW_SECRET)
        self.assertEqual(secret_info.get('piper_credential_id'), KNOWN_CREDENTIAL_ID)
        self.assertEqual(secret_info.get('piper_instance_id'), KNOWN_INSTANCE_ID)
        logger.info(f"SUCCESS: Raw secret correctly fetched: {secret_info.get('value')}")

    @requests_mock.Mocker()
    def test_02_fetch_raw_secret_exchange_url_not_configured(self, m):
        logger.info("--- Test 02: Fetch Raw Secret - Exchange URL Not Configured ---")
        client = self._get_mock_piper_client(exchange_url=None, instance_id_at_init=KNOWN_INSTANCE_ID) # NO exchange_url

        # Mock up to STS token retrieval
        m.post(MOCK_TOKEN_URL, json={'access_token': 'jwt_for_resolve', 'expires_in': 3600})
        m.post(MOCK_RESOLVE_URL, json={'credentialId': KNOWN_CREDENTIAL_ID})
        m.post(MOCK_TOKEN_URL, json={'access_token': 'jwt_for_get_scoped', 'expires_in': 3600}) # For get_scoped
        m.post(MOCK_GET_SCOPED_URL, json={
            'access_token': MOCK_STS_TOKEN, 'expires_in': 900, 
            'granted_credential_ids': [KNOWN_CREDENTIAL_ID]
        })

        with self.assertRaisesRegex(PiperConfigError, "exchange_secret_url' is not configured"):
            client.get_secret(KNOWN_VARIABLE_NAME, fetch_raw_secret=True)
        logger.info("SUCCESS: Correctly raised PiperConfigError when exchange_url not set.")

    @requests_mock.Mocker()
    def test_03_fetch_raw_secret_false_returns_sts(self, m):
        logger.info("--- Test 03: Fetch Raw Secret False - Returns STS ---")
        client = self._get_mock_piper_client(exchange_url=MOCK_EXCHANGE_SECRET_URL, instance_id_at_init=KNOWN_INSTANCE_ID)

        m.post(MOCK_TOKEN_URL, json={'access_token': 'jwt_for_resolve', 'expires_in': 3600})
        m.post(MOCK_RESOLVE_URL, json={'credentialId': KNOWN_CREDENTIAL_ID})
        m.post(MOCK_TOKEN_URL, json={'access_token': 'jwt_for_get_scoped', 'expires_in': 3600})
        m.post(MOCK_GET_SCOPED_URL, json={
            'access_token': MOCK_STS_TOKEN, 'expires_in': 900, 
            'granted_credential_ids': [KNOWN_CREDENTIAL_ID]
        })

        secret_info = client.get_secret(KNOWN_VARIABLE_NAME, fetch_raw_secret=False) # fetch_raw_secret is False
        
        self.assertIsNotNone(secret_info)
        self.assertEqual(secret_info.get('source'), 'piper_sts')
        self.assertEqual(secret_info.get('value'), MOCK_STS_TOKEN)
        logger.info(f"SUCCESS: STS token correctly returned when fetch_raw_secret=False: {secret_info.get('value')}")

    @requests_mock.Mocker()
    def test_04_exchange_gcf_returns_error(self, m):
        logger.info("--- Test 04: Fetch Raw Secret - Exchange GCF Returns Error ---")
        client = self._get_mock_piper_client(exchange_url=MOCK_EXCHANGE_SECRET_URL, instance_id_at_init=KNOWN_INSTANCE_ID)

        # Mock successful STS retrieval
        m.post(MOCK_TOKEN_URL, json={'access_token': 'jwt_for_resolve', 'expires_in': 3600})
        m.post(MOCK_RESOLVE_URL, json={'credentialId': KNOWN_CREDENTIAL_ID})
        m.post(MOCK_TOKEN_URL, json={'access_token': 'jwt_for_get_scoped', 'expires_in': 3600})
        m.post(MOCK_GET_SCOPED_URL, json={'access_token': MOCK_STS_TOKEN, 'expires_in': 900, 'granted_credential_ids': [KNOWN_CREDENTIAL_ID]})
        
        # Mock agent token for exchange GCF
        m.post(MOCK_TOKEN_URL, json={'access_token': 'jwt_for_exchange', 'expires_in': 3600})
        # Mock exchange GCF returning a 403 error
        m.post(MOCK_EXCHANGE_SECRET_URL, status_code=403, json={'error': 'access_denied', 'error_description': 'Grant revoked for raw secret'})

        with self.assertRaises(PiperRawSecretExchangeError) as cm:
            client.get_secret(KNOWN_VARIABLE_NAME, fetch_raw_secret=True)
        
        self.assertEqual(cm.exception.status_code, 403)
        self.assertIn("Grant revoked for raw secret", str(cm.exception))
        logger.info(f"SUCCESS: Correctly raised PiperRawSecretExchangeError: {cm.exception}")

    @requests_mock.Mocker()
    def test_05_initial_sts_fails_then_fallback(self, m):
        logger.info("--- Test 05: Initial STS Fails, Then Fallback (fetch_raw_secret=True but irrelevant) ---")
        client = self._get_mock_piper_client(exchange_url=MOCK_EXCHANGE_SECRET_URL, instance_id_at_init=KNOWN_INSTANCE_ID)
        client.enable_env_fallback = True # Ensure fallback is on
        client.env_variable_map = {KNOWN_VARIABLE_NAME: "TEST_API_KEY_ENV_VAR"}

        # Mock initial STS flow failure (e.g., mapping not found)
        m.post(MOCK_TOKEN_URL, json={'access_token': 'jwt_for_resolve', 'expires_in': 3600})
        m.post(MOCK_RESOLVE_URL, status_code=404, json={'error': 'mapping_not_found', 'message': 'Grant not found for variable'})
        
        os.environ["TEST_API_KEY_ENV_VAR"] = "env_secret_value"
        secret_info = client.get_secret(KNOWN_VARIABLE_NAME, fetch_raw_secret=True) # fetch_raw_secret doesn't matter if STS fails
        del os.environ["TEST_API_KEY_ENV_VAR"]

        self.assertEqual(secret_info.get('source'), 'environment_variable')
        self.assertEqual(secret_info.get('value'), 'env_secret_value')
        logger.info(f"SUCCESS: Fell back to environment variable: {secret_info.get('value')}")


# Add this new test method to the TestPiperSDKRawSecretFetch class in quick_sdk_test.py

    @requests_mock.Mocker()
    def test_06_grant_needed_error_includes_url(self, m):
        logger.info("--- Test 06: PiperGrantNeededError Includes Constructed URL ---")
        # Use the actual default UI base URL from the client if not overridden
        expected_grant_page_base = PiperClient.DEFAULT_PIPER_UI_BASE_URL 
        client = self._get_mock_piper_client(
            instance_id_at_init=KNOWN_INSTANCE_ID,
            # piper_ui_grant_page_url is not passed to _get_mock_piper_client,
            # so it will use the default from PiperClient class.
            # If you want to test overriding it, add it to _get_mock_piper_client
            # and pass a custom URL here.
        )
        client.piper_ui_grant_page_url = expected_grant_page_base # Explicitly ensure it's set for test clarity

        # Mock agent token fetch for resolve_variable_mapping
        m.post(MOCK_TOKEN_URL, json={'access_token': 'jwt_for_resolve', 'expires_in': 3600})
        # Mock resolve_variable_mapping to return 404 mapping_not_found
        m.post(MOCK_RESOLVE_URL, 
               status_code=404, 
               json={'error': 'mapping_not_found', 
                     'error_description': 'Test explicit grant missing for variable.'})

        variable_to_request = "VerySpecificVar"
        expected_url_params = urlencode({
            'scope': 'manage_grants',
            'client': TEST_AGENT_CLIENT_ID, # From your test config
            'variable': variable_to_request
        }, quote_via=_quote_plus)
        expected_full_grant_url = f"{expected_grant_page_base}?{expected_url_params}"

        with self.assertRaises(PiperGrantNeededError) as cm:
            client.get_secret(variable_to_request)
        
        error_message = str(cm.exception)
        self.assertIn("No active grant mapping found", error_message)
        self.assertIn(expected_full_grant_url, error_message)
        logger.info(f"SUCCESS: PiperGrantNeededError correctly raised with helpful URL.")
        logger.debug(f"Full error: {error_message}")

if __name__ == '__main__':
    # Temporarily set env vars if not present, for the dummy client_id/secret
    if "PIPER_TEST_AGENT_CLIENT_ID" not in os.environ:
        os.environ["PIPER_TEST_AGENT_CLIENT_ID"] = "dummy_test_id_for_sdk_tests"
    if "PIPER_TEST_AGENT_CLIENT_SECRET" not in os.environ:
        os.environ["PIPER_TEST_AGENT_CLIENT_SECRET"] = "dummy_test_secret_for_sdk_tests"
    
    # Replace YOUR_FUNCTIONAL_AGENT_... in the script above with actual values if you want to test against live backend
    # For this quick test, we are mocking all HTTP calls so live backend isn't hit.

    unittest.main()