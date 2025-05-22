# test_client.py
import unittest
from unittest.mock import patch, MagicMock, mock_open
import os
import json
import requests 
import re # ADDED

from piper_sdk.client import (
    PiperClient, PiperError, PiperConfigError, PiperLinkNeededError, PiperAuthError,
    PiperGrantNeededError, PiperForbiddenError, PiperRawSecretExchangeError, PiperSecretAcquisitionError
)

def mock_response(status_code=200, json_data=None, text_data=None, headers=None): # Same as before
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    if json_data is not None:
        mock_resp.json = MagicMock(return_value=json_data)
    mock_resp.text = text_data if text_data is not None else (json.dumps(json_data) if json_data is not None else "")
    mock_resp.headers = headers or {'Content-Type': 'application/json'}
    if status_code >= 400:
        http_error = requests.exceptions.HTTPError(f"Mock HTTP Error {status_code}")
        http_error.response = mock_resp
        mock_resp.raise_for_status = MagicMock(side_effect=http_error)
    else:
        mock_resp.raise_for_status = MagicMock()
    return mock_resp

def create_mock_psae(variable_name, piper_error_obj=None, env_error_str=None, local_config_key_and_error=None, sdk_internal_error_str=None): # Same as before
    summary = {}
    if piper_error_obj: summary["Piper"] = piper_error_obj
    if env_error_str: summary["EnvironmentVariable"] = env_error_str
    if local_config_key_and_error: summary[local_config_key_and_error[0]] = local_config_key_and_error[1]
    if sdk_internal_error_str: summary["SDKInternal"] = sdk_internal_error_str
    if hasattr(piper_error_obj, 'variable_name_requested') and not piper_error_obj.variable_name_requested: # type: ignore
        piper_error_obj.variable_name_requested = variable_name # type: ignore
    return PiperSecretAcquisitionError(f"Mock PSAE for {variable_name}", variable_name, summary)

class TestPiperClientRegression(unittest.TestCase): # Mostly same, one fix
    def setUp(self):
        self.client_id = "test_agent_client_id_123"
        self.variable_name = "TEST_API_KEY"
        self.normalized_variable_name = "test_api_key" 
        self.credential_id = "cred_12345"
        self.instance_id = "instance_abc987"
        self.sts_token = "mock_sts_token_xyz"
        self.raw_secret = "mock_raw_secret_value"
        self.resolve_url = PiperClient.DEFAULT_PIPER_RESOLVE_MAPPING_URL
        self.scoped_url = PiperClient.DEFAULT_PIPER_GET_SCOPED_URL
        self.exchange_url = PiperClient.DEFAULT_PIPER_EXCHANGE_SECRET_URL
        self.grant_ui_url = PiperClient.DEFAULT_PIPER_UI_BASE_URL
        self.client = PiperClient(client_id=self.client_id, piper_ui_grant_page_url=self.grant_ui_url)

    @patch('requests.Session.post')
    @patch('piper_sdk.client.PiperClient.discover_local_instance_id')
    def test_get_secret_piper_success_sts(self, mock_discover_id, mock_post): # No change
        mock_discover_id.return_value = self.instance_id
        mock_resolve_resp = mock_response(200, {"credentialId": self.credential_id})
        mock_scoped_resp = mock_response(200, {"access_token": self.sts_token, "granted_credential_ids": [self.credential_id], "expires_in": 3600})
        mock_post.side_effect = [mock_resolve_resp, mock_scoped_resp]
        secret_info = self.client.get_secret(self.variable_name, fetch_raw_secret=False) 
        self.assertEqual(secret_info["value"], self.sts_token)
        self.assertEqual(secret_info["source"], "piper_sts")

    @patch('requests.Session.post')
    @patch('piper_sdk.client.PiperClient.discover_local_instance_id')
    def test_get_secret_piper_success_raw(self, mock_discover_id, mock_post): # No change
        mock_discover_id.return_value = self.instance_id
        mock_resolve_resp = mock_response(200, {"credentialId": self.credential_id})
        mock_scoped_resp = mock_response(200, {"access_token": self.sts_token, "granted_credential_ids": [self.credential_id]})
        mock_exchange_resp = mock_response(200, {"secret_value": self.raw_secret})
        mock_post.side_effect = [mock_resolve_resp, mock_scoped_resp, mock_exchange_resp]
        secret_info = self.client.get_secret(self.variable_name, fetch_raw_secret=True)
        self.assertEqual(secret_info["value"], self.raw_secret)
        self.assertEqual(secret_info["source"], "piper_raw_secret")

    @patch('requests.Session.post')
    @patch('piper_sdk.client.PiperClient.discover_local_instance_id')
    @patch('os.environ.get', return_value=None) 
    @patch('os.path.exists', return_value=False) 
    def test_get_secret_piper_grant_needed_raises_psae(self, mock_exists, mock_env_get, mock_discover_id, mock_post):
        # FIX: Enable local config for this test
        self.client = PiperClient(
            client_id=self.client_id,
            piper_ui_grant_page_url=self.grant_ui_url,
            fallback_to_local_config=True, 
            local_config_file_path="/mock/dummy_path.json" 
        )
        mock_discover_id.return_value = self.instance_id
        mock_resolve_fail_resp = mock_response(404, {"error": "mapping_not_found", "message": "Grant mapping does not exist"})
        mock_post.return_value = mock_resolve_fail_resp
        with self.assertRaises(PiperSecretAcquisitionError) as cm:
            self.client.get_secret(self.variable_name)
        psae = cm.exception
        self.assertIsInstance(psae.attempted_sources_summary["Piper"], PiperGrantNeededError)
        self.assertIn(f"LocalConfigFile (/mock/dummy_path.json)", psae.attempted_sources_summary)

    @patch('piper_sdk.client.PiperClient.discover_local_instance_id')
    @patch('os.environ.get', return_value=None) 
    @patch('os.path.exists', return_value=False) 
    def test_get_secret_piper_link_needed_raises_psae(self, mock_exists, mock_env_get, mock_discover_id): # No change
        mock_discover_id.return_value = None 
        self.client._configured_instance_id = None 
        with self.assertRaises(PiperSecretAcquisitionError) as cm:
            self.client.get_secret(self.variable_name)
        psae = cm.exception
        self.assertIsInstance(psae.attempted_sources_summary["Piper"], PiperLinkNeededError)

    @patch('piper_sdk.client.PiperClient.discover_local_instance_id', return_value=None) 
    @patch('os.environ.get')
    def test_get_secret_env_var_success_after_piper_fail(self, mock_env_get, mock_discover_id): # No change (re import was the fix)
        self.client._configured_instance_id = None
        expected_env_value = "secret_from_env_yay"
        sdk_generated_env_var_name = self.variable_name.upper().replace('-', '_').replace(' ', '_')
        sdk_generated_env_var_name = re.sub(r'[^A-Z0-9_]', '_', sdk_generated_env_var_name)
        sdk_generated_env_var_name = re.sub(r'_+', '_', sdk_generated_env_var_name)
        if self.client.env_variable_prefix:
            sdk_generated_env_var_name = f"{self.client.env_variable_prefix}{sdk_generated_env_var_name}"
        mock_env_get.side_effect = lambda k: expected_env_value if k == sdk_generated_env_var_name else None
        secret_info = self.client.get_secret(self.variable_name)
        self.assertEqual(secret_info["value"], expected_env_value)
        self.assertEqual(secret_info["env_var_name_used"], sdk_generated_env_var_name)

    @patch('piper_sdk.client.PiperClient.discover_local_instance_id', return_value=None) 
    @patch('os.environ.get', return_value=None) 
    @patch('os.path.exists', return_value=True)
    @patch('os.access', return_value=True)
    def test_get_secret_local_config_success_after_piper_env_fail(self, mock_access, mock_exists, mock_env_get, mock_discover_id): # No change
        self.client._configured_instance_id = None
        config_file_path = "/fake/path/to/secrets.json"
        self.client = PiperClient(client_id=self.client_id, fallback_to_local_config=True, local_config_file_path=config_file_path)
        expected_config_value = "secret_from_local_file_woohoo"
        mock_file_content = json.dumps({self.variable_name: expected_config_value})
        with patch('builtins.open', mock_open(read_data=mock_file_content)):
            secret_info = self.client.get_secret(self.variable_name)
        self.assertEqual(secret_info["value"], expected_config_value)
        self.assertEqual(secret_info["source"], "local_config_file")

    @patch('piper_sdk.client.PiperClient.discover_local_instance_id', return_value=None) 
    @patch('os.environ.get', return_value=None) 
    @patch('os.path.exists') 
    def test_get_secret_all_tiers_fail_psae(self, mock_exists, mock_env_get, mock_discover_id): # No change
        self.client._configured_instance_id = None
        config_file_path = "/fake/path/nonexistent.json"
        self.client = PiperClient(client_id=self.client_id, fallback_to_local_config=True, local_config_file_path=config_file_path)
        mock_exists.return_value = False 
        with self.assertRaises(PiperSecretAcquisitionError) as cm:
            self.client.get_secret(self.variable_name)
        psae = cm.exception
        self.assertIsInstance(psae.attempted_sources_summary.get("Piper"), PiperLinkNeededError)
        self.assertIsInstance(psae.attempted_sources_summary.get(f"LocalConfigFile ({config_file_path})"), FileNotFoundError)

    def test_get_secret_invalid_variable_name_raises_config_error(self): # Updated regexes
        with self.assertRaisesRegex(PiperConfigError, "variable_name must be a string, not None or other type"):
            self.client.get_secret(None, raise_on_failure=True) # type: ignore
        with self.assertRaisesRegex(PiperConfigError, "variable_name cannot be empty or all whitespace after stripping"):
            self.client.get_secret("   ", raise_on_failure=True)

    def test_get_secret_on_client_with_init_failure_client_id(self): # No change
        bad_client = PiperClient(client_id=None) # type: ignore
        with self.assertRaisesRegex(PiperConfigError, "client_id is required"):
            bad_client.get_secret(self.variable_name, raise_on_failure=True)

    def test_get_secret_on_client_with_init_failure_bad_url(self): # No change
        bad_client = PiperClient(client_id=self.client_id, resolve_mapping_url="http://badurl.com")
        with self.assertRaisesRegex(PiperConfigError, "must be a valid HTTPS URL"):
            bad_client.get_secret(self.variable_name, raise_on_failure=True)

class TestPiperClientGracefulFeatures(unittest.TestCase): # Some tests updated
    def setUp(self):
        self.client_id = "graceful_agent_id_456"
        self.variable_name = "GRACEFUL_VAR"
        self.normalized_variable_name = "graceful_var"
        self.credential_id = "cred_graceful_678"
        self.instance_id = "instance_graceful_def"
        self.sts_token = "graceful_sts_token"
        self.raw_secret = "graceful_raw_secret"
        self.grant_ui_url = "https://piper.example.com/secrets"
        self.client = PiperClient(client_id=self.client_id, piper_ui_grant_page_url=self.grant_ui_url)

    def test_init_client_id_missing_stores_error(self): # No change
        client = PiperClient(client_id=None) # type: ignore
        self.assertFalse(client.client_initialization_ok)
        self.assertIsInstance(client._initialization_error, PiperConfigError)

    def test_init_bad_resolve_url_stores_error(self): # No change
        client = PiperClient(client_id=self.client_id, resolve_mapping_url="http://badurl.com")
        self.assertFalse(client.client_initialization_ok)
        self.assertIsInstance(client._initialization_error, PiperConfigError)

    def test_init_local_config_path_missing_stores_error(self): # No change
        client = PiperClient(client_id=self.client_id, fallback_to_local_config=True, local_config_file_path=None)
        self.assertFalse(client.client_initialization_ok)
        self.assertIsInstance(client._initialization_error, PiperConfigError)
        
    def test_init_multiple_config_errors_stores_first(self): # No change
        client = PiperClient(client_id=None, resolve_mapping_url="http://bad.url") # type: ignore
        self.assertFalse(client.client_initialization_ok)
        self.assertIsInstance(client._initialization_error, PiperConfigError)
        self.assertIn("client_id is required", str(client._initialization_error))

    def test_get_secret_non_raising_invalid_variable_name(self): # Updated assertions for keys
        result_none = self.client.get_secret(None, raise_on_failure=False) # type: ignore
        self.assertEqual(result_none.get("source"), "config_error_input_type") # type: ignore
        self.assertEqual(result_none.get("variable_name"), "INPUT_VALIDATION_NON_STRING_VAR_NAME") # type: ignore
        self.assertIsInstance(self.client._last_get_secret_errors.get("INPUT_VALIDATION_NON_STRING_VAR_NAME"), PiperConfigError)

        result_empty = self.client.get_secret("", raise_on_failure=False)
        self.assertEqual(result_empty.get("source"), "config_error_input_empty") # type: ignore
        self.assertEqual(result_empty.get("variable_name"), "") # type: ignore
        self.assertIsInstance(self.client._last_get_secret_errors.get(""), PiperConfigError)

    def test_get_secret_non_raising_client_init_failure(self): # No change
        bad_client = PiperClient(client_id=None) # type: ignore
        result = bad_client.get_secret(self.variable_name, raise_on_failure=False)
        self.assertEqual(result.get("source"), "client_initialization_failure") # type: ignore
        self.assertIs(result.get("error_object"), bad_client._initialization_error) # type: ignore

    @patch('requests.Session.post')
    @patch('piper_sdk.client.PiperClient.discover_local_instance_id')
    @patch('os.environ.get', return_value=None)
    @patch('os.path.exists', return_value=False)
    def test_get_secret_non_raising_all_tiers_fail_stores_psae(self, mock_exists, mock_env_get, mock_discover_id, mock_post): # Updated assertion for source
        mock_discover_id.return_value = self.instance_id 
        mock_resolve_fail_resp = mock_response(404, {"error": "mapping_not_found"})
        mock_post.return_value = mock_resolve_fail_resp
        result = self.client.get_secret(self.variable_name, raise_on_failure=False)
        self.assertEqual(result.get("source"), "piper_grant_needed") 
        self.assertIsInstance(result.get("error_object"), PiperSecretAcquisitionError) # type: ignore

    @patch('requests.Session.post')
    @patch('piper_sdk.client.PiperClient.discover_local_instance_id')
    def test_get_secret_non_raising_success_clears_previous_error(self, mock_discover_id, mock_post): # No change
        mock_discover_id.return_value = self.instance_id
        mock_resolve_fail_resp = mock_response(404, {"error": "mapping_not_found"})
        mock_post.return_value = mock_resolve_fail_resp
        with patch('os.environ.get', return_value=None), patch('os.path.exists', return_value=False):
            self.client.get_secret(self.variable_name, raise_on_failure=False)
        mock_resolve_resp = mock_response(200, {"credentialId": self.credential_id})
        mock_scoped_resp = mock_response(200, {"access_token": self.sts_token, "granted_credential_ids": [self.credential_id]})
        mock_post.side_effect = [mock_resolve_resp, mock_scoped_resp]
        success_result = self.client.get_secret(self.variable_name, fetch_raw_secret=False, raise_on_failure=False)
        self.assertEqual(success_result.get("source"), "piper_sts") # type: ignore
        self.assertIsNone(self.client._last_get_secret_errors.get(self.variable_name))

    def test_get_last_error_for_variable_no_error(self): # No change
        self.assertIsNone(self.client.get_last_error_for_variable(self.variable_name))

    @patch('piper_sdk.client.PiperClient._perform_get_secret')
    def test_get_last_error_for_variable_returns_stored_error(self, mock_perform_get): # No change
        mock_error = PiperLinkNeededError("Test link needed")
        mock_perform_get.side_effect = mock_error
        self.client.get_secret(self.variable_name, raise_on_failure=False)
        self.assertIs(self.client.get_last_error_for_variable(self.variable_name), mock_error)

    def test_get_last_error_for_variable_bad_input(self): # Updated for new key
        self.assertIsNone(self.client.get_last_error_for_variable(None)) # type: ignore
        # Test for the specific key used for non-string input
        self.client.get_secret(None, raise_on_failure=False) # type: ignore
        self.assertIsInstance(self.client.get_last_error_for_variable("INPUT_VALIDATION_NON_STRING_VAR_NAME"), PiperConfigError)


    def test_get_resolution_advice_no_error_returns_none(self): # No change
        self.assertIsNone(self.client.get_resolution_advice("ANY_VAR"))

    def test_get_resolution_advice_for_init_error_client_id_missing(self): # No change
        bad_client = PiperClient(client_id=None) # type: ignore
        advice = bad_client.get_resolution_advice("")
        self.assertIn("Piper SDK Client Initial Setup Problem:", advice) # type: ignore
        self.assertIn("Detail: PiperClient critical configuration error: client_id is required.", advice) # type: ignore

    def test_get_resolution_advice_psae_grant_needed(self): # FIX: Use keyword args for error
        var_name = "NEEDS_GRANT_KEY"
        grant_error = PiperGrantNeededError(
            message=f"No grant for '{var_name}'", # Corrected message from before
            agent_id_for_grant=self.client_id,
            variable_name_requested=var_name,
            piper_ui_grant_url_template=self.grant_ui_url
        )
        psae = create_mock_psae(var_name, piper_error_obj=grant_error)
        advice = self.client.get_resolution_advice(var_name, error_object=psae)
        self.assertIn(f"permission for '{var_name}'", advice) # type: ignore
        # Check for new URL structure with response_type=code and client=...
        expected_grant_url = f"{self.grant_ui_url}?response_type=code&scope=manage_grants&client={self.client_id}&variable={var_name}"
        self.assertIn(expected_grant_url, advice) # type: ignore

    def test_get_resolution_advice_psae_link_needed(self): # No change
        var_name = "NEEDS_LINK_KEY"; link_error = PiperLinkNeededError("Not connected.")
        psae = create_mock_psae(var_name, piper_error_obj=link_error)
        client_with_discovery = PiperClient(client_id=self.client_id, attempt_local_discovery=True)
        advice = client_with_discovery.get_resolution_advice(var_name, error_object=psae)
        self.assertIn("Piper Link application needs to be connected", advice) # type: ignore
        self.assertIn(PiperClient.DEFAULT_PIPER_LINK_SERVICE_URL, advice) # type: ignore

    def test_get_resolution_advice_psae_env_var_not_set(self): # No change
        var_name = "ENV_VAR_KEY"; env_error_msg = "Environment variable 'MY_APP_ENV_VAR_KEY' not set."
        psae = create_mock_psae(var_name, env_error_str=env_error_msg)
        advice = self.client.get_resolution_advice(var_name, error_object=psae)
        self.assertIn(f"Environment Variable Check: {env_error_msg}", advice) # type: ignore

    def test_get_resolution_advice_psae_local_config_file_not_found(self): # No change
        var_name = "LOCAL_CONF_KEY"; file_path = "/fake/secrets.json"
        local_error_info = (f"LocalConfigFile ({file_path})", FileNotFoundError(f"File not found: {file_path}"))
        psae = create_mock_psae(var_name, local_config_key_and_error=local_error_info)
        advice = self.client.get_resolution_advice(var_name, error_object=psae)
        self.assertIn(f"Local Config File Check ({file_path}): File was not found.", advice) # type: ignore

    def test_get_resolution_advice_no_specifics_gets_check_logs_message(self): # Fixed based on new logic
        class OddError(PiperError): pass
        odd_error = OddError("Something odd happened.")
        advice = self.client.get_resolution_advice("ODD_VAR", error_object=odd_error)
        self.assertIn("Please check the application logs", advice) # type: ignore
        self.assertNotIn("Once this is resolved", advice) # type: ignore
        
    def test_get_resolution_advice_prefers_explicit_error_object(self): # No change
        client_with_init_error = PiperClient(client_id=None) #type: ignore
        specific_error = PiperLinkNeededError("Explicit link needed error for test")
        advice = client_with_init_error.get_resolution_advice("ANY_VAR", error_object=specific_error)
        self.assertIn("The Piper Link application needs to be connected.", advice) # type: ignore
        self.assertNotIn("client_id is required", advice) # type: ignore

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)