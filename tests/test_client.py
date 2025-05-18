# tests/test_client.py
import unittest
import os
import json
from unittest import mock

# Assuming client.py is in piper_sdk directory, and tests is a sibling
# Adjust import path as necessary based on your project structure
from piper_sdk.client import (
    PiperClient,
    PiperError,
    PiperConfigError,
    PiperLinkNeededError,
    PiperAuthError,
    PiperGrantNeededError,
    PiperForbiddenError,
    PiperRawSecretExchangeError,
    PiperSecretAcquisitionError
)

# Dummy credentials for client initialization
DUMMY_CLIENT_ID = "test_agent_client_id"
DUMMY_CLIENT_SECRET = "test_agent_client_secret"
DUMMY_INSTANCE_ID = "test_instance_123"
DUMMY_CREDENTIAL_ID = "bubble_cred_abc"
DUMMY_STS_TOKEN = "sts_token_xyz"
DUMMY_RAW_SECRET = "super_secret_value"
DUMMY_VARIABLE_NAME = "TEST_API_KEY"
DUMMY_ENV_VAR_NAME = "SDK_TEST_API_KEY_ENV"
DUMMY_ENV_VAR_VALUE = "env_secret_value"
DUMMY_LOCAL_CONFIG_PATH = "test_secrets.json" # Will create/mock this file
DUMMY_LOCAL_CONFIG_VALUE = "local_config_secret_value"

class TestPiperClientGetSecret(unittest.TestCase):

    def setUp(self):
        # Basic client, fallbacks can be enabled/disabled per test
        self.client = PiperClient(
            client_id=DUMMY_CLIENT_ID,
            client_secret=DUMMY_CLIENT_SECRET,
            use_piper=True,
            attempt_local_discovery=True, # Default, can be overridden in specific client instances
            fallback_to_env=True,         # Default, can be overridden
            fallback_to_local_config=True, # Default, can be overridden
            local_config_file_path=DUMMY_LOCAL_CONFIG_PATH # Required if fallback_to_local_config is True
        )
        # Clean up dummy local config file if it exists from a previous failed test
        if os.path.exists(DUMMY_LOCAL_CONFIG_PATH):
            os.remove(DUMMY_LOCAL_CONFIG_PATH)

    def tearDown(self):
        # Clean up dummy local config file
        if os.path.exists(DUMMY_LOCAL_CONFIG_PATH):
            os.remove(DUMMY_LOCAL_CONFIG_PATH)

    # --- Test Scenarios ---

    # Scenario 1: Piper Success (STS)
    @mock.patch.object(PiperClient, '_get_instance_id_for_api_call', return_value=DUMMY_INSTANCE_ID)
    @mock.patch.object(PiperClient, '_resolve_piper_variable', return_value=DUMMY_CREDENTIAL_ID)
    @mock.patch.object(PiperClient, '_fetch_piper_sts_token')
    def test_get_secret_piper_sts_success(self, mock_fetch_sts, mock_resolve, mock_get_id):
        mock_fetch_sts.return_value = {
            "access_token": DUMMY_STS_TOKEN,
            "expires_in": 3600,
            "granted_credential_ids": [DUMMY_CREDENTIAL_ID]
        }
        
        secret_info = self.client.get_secret(DUMMY_VARIABLE_NAME, fetch_raw_secret=False)
        
        self.assertEqual(secret_info['value'], DUMMY_STS_TOKEN)
        self.assertEqual(secret_info['source'], 'piper_sts')
        self.assertEqual(secret_info['piper_credential_id'], DUMMY_CREDENTIAL_ID)
        self.assertEqual(secret_info['piper_instance_id'], DUMMY_INSTANCE_ID)
        mock_get_id.assert_called_once_with(None) # piper_link_instance_id_for_call is None
        mock_resolve.assert_called_once_with(DUMMY_VARIABLE_NAME, DUMMY_INSTANCE_ID)
        mock_fetch_sts.assert_called_once_with([DUMMY_CREDENTIAL_ID], DUMMY_INSTANCE_ID)

    # Scenario 2: Piper Success (Raw Secret)
    @mock.patch.object(PiperClient, '_get_instance_id_for_api_call', return_value=DUMMY_INSTANCE_ID)
    @mock.patch.object(PiperClient, '_resolve_piper_variable', return_value=DUMMY_CREDENTIAL_ID)
    @mock.patch.object(PiperClient, '_fetch_piper_sts_token') # For the initial STS part
    @mock.patch.object(PiperClient, '_get_valid_agent_token') # For the exchange JWT
    @mock.patch('piper_sdk.client.requests.Session.post') # To mock the actual HTTP POST for exchange
    def test_get_secret_piper_raw_success(self, mock_requests_post, mock_get_exchange_jwt, mock_fetch_sts, mock_resolve, mock_get_id):
        # Mock STS fetch (still happens first)
        mock_fetch_sts.return_value = {
            "access_token": "intermediate_sts_token", # Not the final value
            "expires_in": 3600,
            "granted_credential_ids": [DUMMY_CREDENTIAL_ID]
        }
        # Mock JWT for exchange
        mock_get_exchange_jwt.return_value = "jwt_for_exchange"
        
        # Mock response from exchange GCF
        mock_exchange_response = mock.Mock()
        mock_exchange_response.status_code = 200
        mock_exchange_response.json.return_value = {"secret_value": DUMMY_RAW_SECRET}
        mock_requests_post.return_value = mock_exchange_response
        
        secret_info = self.client.get_secret(DUMMY_VARIABLE_NAME, fetch_raw_secret=True)
        
        self.assertEqual(secret_info['value'], DUMMY_RAW_SECRET)
        self.assertEqual(secret_info['source'], 'piper_raw_secret')
        self.assertEqual(secret_info['piper_credential_id'], DUMMY_CREDENTIAL_ID)
        self.assertEqual(secret_info['piper_instance_id'], DUMMY_INSTANCE_ID)
        
        mock_get_id.assert_called_once_with(None)
        mock_resolve.assert_called_once_with(DUMMY_VARIABLE_NAME, DUMMY_INSTANCE_ID)
        mock_fetch_sts.assert_called_once_with([DUMMY_CREDENTIAL_ID], DUMMY_INSTANCE_ID)
        mock_get_exchange_jwt.assert_called_once_with(audience=self.client.exchange_secret_url, instance_id=DUMMY_INSTANCE_ID)
        mock_requests_post.assert_called_once_with(
            self.client.exchange_secret_url,
            headers=mock.ANY, # or more specific: {"Authorization": "Bearer jwt_for_exchange", ...}
            json={"piper_credential_id": DUMMY_CREDENTIAL_ID},
            timeout=10
        )

    # Scenario 3: Piper Fails (GrantNeededError), Env Var Success
    @mock.patch.object(PiperClient, '_get_instance_id_for_api_call', return_value=DUMMY_INSTANCE_ID)
    @mock.patch.object(PiperClient, '_resolve_piper_variable')
    @mock.patch.dict(os.environ, {DUMMY_ENV_VAR_NAME: DUMMY_ENV_VAR_VALUE}, clear=True)
    def test_get_secret_piper_grant_needed_env_success(self, mock_resolve, mock_get_id):
        # Configure client for this test to map variable name to specific env var
        self.client.env_variable_map = {DUMMY_VARIABLE_NAME: DUMMY_ENV_VAR_NAME}
        self.client.env_variable_prefix = "" # Ensure prefix doesn't interfere

        mock_resolve.side_effect = PiperGrantNeededError(
            message="Grant needed for test",
            agent_id_for_grant=DUMMY_CLIENT_ID,
            variable_name_requested=DUMMY_VARIABLE_NAME,
            piper_ui_grant_url_template=self.client.piper_ui_grant_page_url
        )
        
        secret_info = self.client.get_secret(DUMMY_VARIABLE_NAME)
        
        self.assertEqual(secret_info['value'], DUMMY_ENV_VAR_VALUE)
        self.assertEqual(secret_info['source'], 'environment_variable')
        self.assertEqual(secret_info['env_var_name_used'], DUMMY_ENV_VAR_NAME)
        mock_get_id.assert_called_once_with(None)
        mock_resolve.assert_called_once_with(DUMMY_VARIABLE_NAME, DUMMY_INSTANCE_ID)

    # Scenario 4: Piper Fails (LinkNeededError), Env Fails, Local Config Success
    @mock.patch.object(PiperClient, '_get_instance_id_for_api_call', return_value=None) # Simulate discovery failure
    @mock.patch.dict(os.environ, {}, clear=True) # Ensure ENV is empty for this var
    def test_get_secret_piper_link_needed_env_fail_local_config_success(self, mock_get_id):
        # Create dummy local config file
        with open(DUMMY_LOCAL_CONFIG_PATH, 'w') as f:
            json.dump({DUMMY_VARIABLE_NAME: DUMMY_LOCAL_CONFIG_VALUE}, f)
            
        # Ensure env_variable_map doesn't find it, forcing prefix logic that won't match
        self.client.env_variable_map = {} 
        self.client.env_variable_prefix = "PREFIX_THAT_WONT_MATCH_"

        secret_info = self.client.get_secret(DUMMY_VARIABLE_NAME)
        
        self.assertEqual(secret_info['value'], DUMMY_LOCAL_CONFIG_VALUE)
        self.assertEqual(secret_info['source'], 'local_config_file')
        self.assertEqual(secret_info['config_file_path'], os.path.expanduser(DUMMY_LOCAL_CONFIG_PATH))
        mock_get_id.assert_called_once_with(None)

    # Scenario 5: All Tiers Fail - Expect PiperSecretAcquisitionError
    @mock.patch.object(PiperClient, '_get_instance_id_for_api_call', return_value=DUMMY_INSTANCE_ID)
    @mock.patch.object(PiperClient, '_resolve_piper_variable')
    @mock.patch.dict(os.environ, {}, clear=True) # ENV empty
    def test_get_secret_all_tiers_fail(self, mock_resolve, mock_get_id):
        # Piper fails with GrantNeeded
        grant_error_instance = PiperGrantNeededError(
            message="Grant truly needed",
            agent_id_for_grant=DUMMY_CLIENT_ID,
            variable_name_requested=DUMMY_VARIABLE_NAME,
            piper_ui_grant_url_template=self.client.piper_ui_grant_page_url
        )
        mock_resolve.side_effect = grant_error_instance
        
        # Local config file does not exist (setUp/tearDown ensures this unless created)
        # Or ensure it's enabled but file path won't be found
        # self.client.fallback_to_local_config = True
        # self.client.local_config_file_path = "non_existent_file.json"

        with self.assertRaises(PiperSecretAcquisitionError) as cm:
            self.client.get_secret(DUMMY_VARIABLE_NAME)
        
        err = cm.exception
        self.assertEqual(err.variable_name, DUMMY_VARIABLE_NAME)
        self.assertIn("Piper", err.attempted_sources_summary)
        self.assertIsInstance(err.attempted_sources_summary["Piper"], PiperGrantNeededError)
        self.assertEqual(err.attempted_sources_summary["Piper"], grant_error_instance)
        
        self.assertIn("EnvironmentVariable", err.attempted_sources_summary)
        self.assertTrue("not set" in err.attempted_sources_summary["EnvironmentVariable"])
        
        expected_local_config_key = f"LocalConfigFile ({os.path.expanduser(DUMMY_LOCAL_CONFIG_PATH)})"
        self.assertIn(expected_local_config_key, err.attempted_sources_summary)
        self.assertIsInstance(err.attempted_sources_summary[expected_local_config_key], FileNotFoundError)

        # Check the __str__ output for key phrases
        err_str = str(err)
        self.assertIn(f"Failed to retrieve secret for '{DUMMY_VARIABLE_NAME}'", err_str)
        self.assertIn("Primary Issue (Piper): Grant truly needed", err_str) # Check PiperGrantNeededError part
        self.assertIn(self.client.piper_ui_grant_page_url, err_str) # Grant URL should be there
        self.assertIn("EnvironmentVariable: Environment variable", err_str)
        self.assertIn("not set", err_str)
        self.assertIn(f"LocalConfigFile ({os.path.expanduser(DUMMY_LOCAL_CONFIG_PATH)}): File not found", err_str)

    # Scenario 6: Piper disabled, Env success
    @mock.patch.dict(os.environ, {DUMMY_ENV_VAR_NAME: DUMMY_ENV_VAR_VALUE}, clear=True)
    def test_get_secret_piper_disabled_env_success(self):
        client_no_piper = PiperClient(
            client_id=DUMMY_CLIENT_ID, client_secret=DUMMY_CLIENT_SECRET,
            use_piper=False, # Piper disabled
            fallback_to_env=True,
            env_variable_map={DUMMY_VARIABLE_NAME: DUMMY_ENV_VAR_NAME},
            fallback_to_local_config=False # Disable local for this test
        )
        secret_info = client_no_piper.get_secret(DUMMY_VARIABLE_NAME)
        self.assertEqual(secret_info['value'], DUMMY_ENV_VAR_VALUE)
        self.assertEqual(secret_info['source'], 'environment_variable')

    # Scenario 7: Local config file permission error
    @mock.patch.object(PiperClient, '_get_instance_id_for_api_call', return_value=None) # Piper fails (e.g. link needed)
    @mock.patch.dict(os.environ, {}, clear=True) # Env fails
    @mock.patch('os.access', return_value=False) # Mock os.access to simulate permission error
    def test_get_secret_local_config_permission_error(self, mock_os_access, mock_get_id):
        # Create the file so FileNotFoundError isn't raised first
        with open(DUMMY_LOCAL_CONFIG_PATH, 'w') as f:
            json.dump({DUMMY_VARIABLE_NAME: DUMMY_LOCAL_CONFIG_VALUE}, f)

        with self.assertRaises(PiperSecretAcquisitionError) as cm:
            self.client.get_secret(DUMMY_VARIABLE_NAME)
        
        err = cm.exception
        expected_local_config_key = f"LocalConfigFile ({os.path.expanduser(DUMMY_LOCAL_CONFIG_PATH)})"
        self.assertIn(expected_local_config_key, err.attempted_sources_summary)
        self.assertIsInstance(err.attempted_sources_summary[expected_local_config_key], PermissionError)
        mock_os_access.assert_called_with(os.path.expanduser(DUMMY_LOCAL_CONFIG_PATH), os.R_OK)


    # Scenario 8: Local config file JSON decode error
    @mock.patch.object(PiperClient, '_get_instance_id_for_api_call', return_value=None) # Piper fails
    @mock.patch.dict(os.environ, {}, clear=True) # Env fails
    def test_get_secret_local_config_json_decode_error(self, mock_get_id):
        # Create a malformed JSON file
        with open(DUMMY_LOCAL_CONFIG_PATH, 'w') as f:
            f.write("{not_json: ") # Malformed JSON
            
        with self.assertRaises(PiperSecretAcquisitionError) as cm:
            self.client.get_secret(DUMMY_VARIABLE_NAME)
            
        err = cm.exception
        expected_local_config_key = f"LocalConfigFile ({os.path.expanduser(DUMMY_LOCAL_CONFIG_PATH)})"
        self.assertIn(expected_local_config_key, err.attempted_sources_summary)
        self.assertIsInstance(err.attempted_sources_summary[expected_local_config_key], PiperError) # Wrapped as PiperError
        self.assertIn("Error decoding JSON", str(err.attempted_sources_summary[expected_local_config_key]))


    # Scenario 9: Piper Link discovery explicitly disabled, no configured instance ID
    def test_get_secret_piper_discovery_disabled_no_explicit_id(self):
        client_no_discovery = PiperClient(
            client_id=DUMMY_CLIENT_ID, client_secret=DUMMY_CLIENT_SECRET,
            use_piper=True,
            attempt_local_discovery=False, # Discovery disabled
            piper_link_instance_id=None,   # No explicit ID
            fallback_to_env=False,         # Disable fallbacks for focused test
            fallback_to_local_config=False
        )
        with self.assertRaises(PiperSecretAcquisitionError) as cm:
            client_no_discovery.get_secret(DUMMY_VARIABLE_NAME)
        
        err = cm.exception
        self.assertIn("Piper", err.attempted_sources_summary)
        self.assertIsInstance(err.attempted_sources_summary["Piper"], PiperLinkNeededError)
        self.assertIn("local discovery is disabled", str(err.attempted_sources_summary["Piper"]))

    # Add more tests:
    # - Piper explicit instance_id passed to get_secret()
    # - Piper explicit instance_id passed to client constructor
    # - Env var prefix logic
    # - Raw secret exchange GCF returning an error (e.g., 403, 500)
    # - _resolve_piper_variable returning other PiperAuthError types
    # - _fetch_piper_sts_token returning PiperForbiddenError or other PiperAuthError types
    # - etc.
    
    # Add this test method to the TestPiperClientGetSecret class in tests/test_client.py

    # Scenario 10: Piper Raw Secret Exchange Fails (e.g., GCF 403), fallbacks also fail
    @mock.patch.object(PiperClient, '_get_instance_id_for_api_call', return_value=DUMMY_INSTANCE_ID)
    @mock.patch.object(PiperClient, '_resolve_piper_variable', return_value=DUMMY_CREDENTIAL_ID)
    @mock.patch.object(PiperClient, '_fetch_piper_sts_token') # For the initial STS part
    @mock.patch.object(PiperClient, '_get_valid_agent_token') # For the exchange JWT
    @mock.patch('piper_sdk.client.requests.Session.post') # To mock the actual HTTP POST for exchange
    @mock.patch.dict(os.environ, {}, clear=True) # Env fails
    def test_get_secret_piper_raw_exchange_fails_all_fallback_fail(
        self, mock_requests_post, mock_get_exchange_jwt, mock_fetch_sts, mock_resolve, mock_get_id
    ):
        # Local config file does not exist (setUp/tearDown ensures this)
        # self.client.fallback_to_local_config is True by default in setUp

        # Mock STS fetch (succeeds)
        mock_fetch_sts.return_value = {
            "access_token": "intermediate_sts_token",
            "expires_in": 3600,
            "granted_credential_ids": [DUMMY_CREDENTIAL_ID]
        }
        # Mock JWT for exchange (succeeds)
        mock_get_exchange_jwt.return_value = "jwt_for_exchange"
        
        # Mock response from exchange GCF - THIS TIME IT FAILS (e.g., 403 Forbidden)
        mock_exchange_failure_response = mock.Mock()
        mock_exchange_failure_response.status_code = 403
        mock_exchange_failure_response.json.return_value = {
            "error": "permission_denied_on_exchange", 
            "error_description": "User not allowed to exchange this secret."
        }
        mock_requests_post.return_value = mock_exchange_failure_response # This mock is for the exchange call

        with self.assertRaises(PiperSecretAcquisitionError) as cm:
            self.client.get_secret(DUMMY_VARIABLE_NAME, fetch_raw_secret=True)
        
        err = cm.exception
        self.assertEqual(err.variable_name, DUMMY_VARIABLE_NAME)
        
        # Check Piper tier failure details
        self.assertIn("Piper", err.attempted_sources_summary)
        piper_failure = err.attempted_sources_summary["Piper"]
        self.assertIsInstance(piper_failure, PiperRawSecretExchangeError)
        self.assertEqual(piper_failure.status_code, 403)
        self.assertEqual(piper_failure.error_code, "permission_denied_on_exchange")
        self.assertIn("User not allowed to exchange this secret", str(piper_failure))
        
        # Check other fallbacks
        self.assertIn("EnvironmentVariable", err.attempted_sources_summary)
        self.assertTrue("not set" in err.attempted_sources_summary["EnvironmentVariable"])
        
        expected_local_config_key = f"LocalConfigFile ({os.path.expanduser(DUMMY_LOCAL_CONFIG_PATH)})"
        self.assertIn(expected_local_config_key, err.attempted_sources_summary)
        self.assertIsInstance(err.attempted_sources_summary[expected_local_config_key], FileNotFoundError)

        # Verify calls up to the point of failure
        mock_get_id.assert_called_once_with(None)
        mock_resolve.assert_called_once_with(DUMMY_VARIABLE_NAME, DUMMY_INSTANCE_ID)
        mock_fetch_sts.assert_called_once_with([DUMMY_CREDENTIAL_ID], DUMMY_INSTANCE_ID)
        mock_get_exchange_jwt.assert_called_once_with(audience=self.client.exchange_secret_url, instance_id=DUMMY_INSTANCE_ID)
        mock_requests_post.assert_called_once_with(
            self.client.exchange_secret_url,
            headers=mock.ANY,
            json={"piper_credential_id": DUMMY_CREDENTIAL_ID},
            timeout=10
        )

# Add this test method to the TestPiperClientGetSecret class in tests/test_client.py

    # Scenario 11: Piper Success (STS) with instance_id explicitly passed to client constructor
    @mock.patch.object(PiperClient, '_resolve_piper_variable', return_value=DUMMY_CREDENTIAL_ID)
    @mock.patch.object(PiperClient, '_fetch_piper_sts_token')
    @mock.patch.object(PiperClient, 'discover_local_instance_id') # To ensure it's NOT called
    def test_get_secret_piper_sts_success_explicit_constructor_instance_id(
        self, mock_discover_local, mock_fetch_sts, mock_resolve
    ):
        explicit_instance_id = "constructor_instance_id_456"
        client_with_explicit_id = PiperClient(
            client_id=DUMMY_CLIENT_ID,
            client_secret=DUMMY_CLIENT_SECRET,
            piper_link_instance_id=explicit_instance_id, # Explicit ID here
            attempt_local_discovery=True, # Even if true, explicit ID should take precedence
            use_piper=True,
            fallback_to_env=False, # Disable fallbacks for focused test
            fallback_to_local_config=False
        )

        mock_fetch_sts.return_value = {
            "access_token": DUMMY_STS_TOKEN,
            "expires_in": 3600,
            "granted_credential_ids": [DUMMY_CREDENTIAL_ID]
        }
        
        secret_info = client_with_explicit_id.get_secret(DUMMY_VARIABLE_NAME, fetch_raw_secret=False)
        
        self.assertEqual(secret_info['value'], DUMMY_STS_TOKEN)
        self.assertEqual(secret_info['source'], 'piper_sts')
        self.assertEqual(secret_info['piper_instance_id'], explicit_instance_id)
        
        mock_discover_local.assert_not_called() # Crucial: discovery should be skipped
        mock_resolve.assert_called_once_with(DUMMY_VARIABLE_NAME, explicit_instance_id)
        mock_fetch_sts.assert_called_once_with([DUMMY_CREDENTIAL_ID], explicit_instance_id)

        # Add this test method to the TestPiperClientGetSecret class in tests/test_client.py

    # Scenario 12: Piper Success (STS) with instance_id explicitly passed to get_secret call
    @mock.patch.object(PiperClient, '_resolve_piper_variable', return_value=DUMMY_CREDENTIAL_ID)
    @mock.patch.object(PiperClient, '_fetch_piper_sts_token')
    @mock.patch.object(PiperClient, 'discover_local_instance_id') # To ensure it's NOT called if overridden
    def test_get_secret_piper_sts_success_explicit_call_instance_id(
        self, mock_discover_local, mock_fetch_sts, mock_resolve
    ):
        call_specific_instance_id = "call_instance_id_789"
        # Client initialized without explicit ID, discovery enabled by default in setUp's self.client
        
        mock_fetch_sts.return_value = {
            "access_token": DUMMY_STS_TOKEN,
            "expires_in": 3600,
            "granted_credential_ids": [DUMMY_CREDENTIAL_ID]
        }
        
        secret_info = self.client.get_secret(
            DUMMY_VARIABLE_NAME, 
            piper_link_instance_id_for_call=call_specific_instance_id, # Explicit ID for this call
            fetch_raw_secret=False
        )
        
        self.assertEqual(secret_info['value'], DUMMY_STS_TOKEN)
        self.assertEqual(secret_info['source'], 'piper_sts')
        self.assertEqual(secret_info['piper_instance_id'], call_specific_instance_id)
        
        mock_discover_local.assert_not_called() # Discovery should be skipped due to call-specific ID
        mock_resolve.assert_called_once_with(DUMMY_VARIABLE_NAME, call_specific_instance_id)
        mock_fetch_sts.assert_called_once_with([DUMMY_CREDENTIAL_ID], call_specific_instance_id)