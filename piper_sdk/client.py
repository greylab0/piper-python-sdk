# piper_sdk/client.py

import os
import re # For variable name normalization
import requests
import time
from urllib.parse import urlencode
import logging
from typing import List, Dict, Any, Optional, Tuple
import uuid # For potential future use by SDK if it were to manage instanceId itself

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - PiperSDK - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Error classes
class PiperError(Exception):
    pass

class PiperAuthError(PiperError):
    def __init__(self, message: str, status_code: Optional[int] = None, error_code: Optional[str] = None, error_details: Optional[Any] = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.error_details = error_details
    def __str__(self):
        details_str = f", Details: {self.error_details}" if self.error_details is not None else ""
        status_str = f" (Status: {self.status_code})" if self.status_code is not None else ""
        code_str = f" (Code: {self.error_code})" if self.error_code else ""
        return f"{super().__str__()}{status_str}{code_str}{details_str}"

class PiperConfigError(PiperError):
    pass

class PiperLinkNeededError(PiperConfigError):
    def __init__(self, message="Piper Link instanceId not provided and could not be discovered. Is Piper Link app running?"):
        super().__init__(message)

class PiperClient:
    DEFAULT_TOKEN_EXPIRY_BUFFER_SECONDS: int = 60
    DEFAULT_PROJECT_ID: str = "444535882337" # This is for constructing default FULL URLs
    DEFAULT_REGION: str = "us-central1"     # This is for constructing default FULL URLs

    # --- Default FULL URLs for Piper Production API Endpoints ---
    # These will be constructed using DEFAULT_PROJECT_ID and DEFAULT_REGION if not overridden
    DEFAULT_PIPER_TOKEN_URL = f"https://piper-token-endpoint-{DEFAULT_PROJECT_ID}.{DEFAULT_REGION}.run.app"
    DEFAULT_PIPER_GET_SCOPED_URL = f"https://getscopedgcpcredentials-{DEFAULT_PROJECT_ID}.{DEFAULT_REGION}.run.app"
    DEFAULT_PIPER_RESOLVE_MAPPING_URL = f"https://piper-resolve-variable-mapping-{DEFAULT_PROJECT_ID}.{DEFAULT_REGION}.run.app"
    
    DEFAULT_PIPER_LINK_SERVICE_URL = "http://localhost:31477/piper-link-context"

    # --- Instance variable for discovered instanceId ---
    # self._discovered_instance_id: Optional[str] = None # Initialized in __init__

    def __init__(self,
                 client_id: str,
                 client_secret: str,
                 # project_id and region are no longer primary config for SDK users.
                 # They are used here only if you want to allow overriding the default *construction* of the full URLs
                 # for a Piper system deployment different from the hardcoded defaults above.
                 # For most users, these would not be passed.
                 _piper_system_project_id: Optional[str] = None, # Underscore to indicate advanced/internal use
                 _piper_system_region: Optional[str] = None,     # Underscore to indicate advanced/internal use
                 token_url: Optional[str] = None,
                 get_scoped_url: Optional[str] = None,
                 resolve_mapping_url: Optional[str] = None,
                 piper_link_service_url: Optional[str] = None,
                 requests_session: Optional[requests.Session] = None,
                 auto_discover_instance_id: bool = True,
                 enable_env_fallback: bool = True,
                 env_variable_prefix: str = "",
                 env_variable_map: Optional[Dict[str, str]] = None):

        if not client_id or not client_secret:
            raise ValueError("client_id and client_secret are required.")
        self.client_id: str = client_id
        self._client_secret: str = client_secret
        
        # Determine effective project_id and region for URL construction if defaults are used
        # This allows advanced override of defaults if needed, but primary way is direct URL override
        effective_project_id = _piper_system_project_id or self.DEFAULT_PROJECT_ID
        effective_region = _piper_system_region or self.DEFAULT_REGION

        self.token_url: str = token_url or f"https://piper-token-endpoint-{effective_project_id}.{effective_region}.run.app"
        self.get_scoped_url: str = get_scoped_url or f"https://getscopedgcpcredentials-{effective_project_id}.{effective_region}.run.app"
        self.resolve_mapping_url: str = resolve_mapping_url or f"https://piper-resolve-variable-mapping-{effective_project_id}.{effective_region}.run.app"
        self.piper_link_service_url: str = piper_link_service_url or self.DEFAULT_PIPER_LINK_SERVICE_URL
        
        # Basic URL validation
        for url_attr_name, url_value_str in [
            ("Piper Token URL", self.token_url),
            ("Piper GetScoped URL", self.get_scoped_url),
            ("Piper Resolve Mapping URL", self.resolve_mapping_url)
        ]:
            if not url_value_str or not url_value_str.startswith('https://'):
                raise PiperConfigError(f"{url_attr_name} ('{url_value_str}') must be a valid HTTPS URL.")
        if not self.piper_link_service_url or not self.piper_link_service_url.startswith('http://localhost'):
             logger.warning(f"Piper Link Service URL ('{self.piper_link_service_url}') does not look like a standard localhost URL. Ensure it's correct.")


        self._session = requests_session if requests_session else requests.Session()
        sdk_version = "0.3.0" # Reflects new features
        self._session.headers.update({'User-Agent': f'Pyper-SDK/{sdk_version}'})
        
        self._access_tokens: Dict[Tuple[str, Optional[str]], str] = {}
        self._token_expiries: Dict[Tuple[str, Optional[str]], float] = {}
        self._discovered_instance_id: Optional[str] = None # Initialize as instance variable

        self.enable_env_fallback = enable_env_fallback
        self.env_variable_prefix = env_variable_prefix
        self.env_variable_map = env_variable_map if env_variable_map is not None else {}

        logger.info(f"PiperClient initialized for agent client_id '{self.client_id[:8]}...'. Env fallback: {self.enable_env_fallback}")
        if auto_discover_instance_id:
             self.discover_local_instance_id()

    def discover_local_instance_id(self, force_refresh: bool = False) -> Optional[str]:
        if self._discovered_instance_id and not force_refresh:
            logger.debug(f"Using cached instanceId: {self._discovered_instance_id}")
            return self._discovered_instance_id
        
        logger.info(f"Attempting to discover Piper Link instanceId from: {self.piper_link_service_url}")
        try:
            response = self._session.get(self.piper_link_service_url, timeout=1.0)
            response.raise_for_status()
            data = response.json()
            instance_id = data.get("instanceId")
            if instance_id and isinstance(instance_id, str):
                logger.info(f"Discovered and cached Piper Link instanceId: {instance_id}")
                self._discovered_instance_id = instance_id
                return instance_id
            else:
                logger.warning(f"Local Piper Link service responded but instanceId was missing/invalid: {data}")
                self._discovered_instance_id = None
                return None
        except requests.exceptions.ConnectionError:
            logger.warning(f"Local Piper Link service not found/running at {self.piper_link_service_url}.")
            self._discovered_instance_id = None
            return None
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout connecting to local Piper Link service at {self.piper_link_service_url}.")
            self._discovered_instance_id = None
            return None
        except Exception as e: 
            logger.warning(f"Error querying local Piper Link service: {e}")
            self._discovered_instance_id = None
            return None

    def _fetch_agent_token(self, audience: str, instance_id: Optional[str]) -> Tuple[str, float]:
        instance_ctx_log = f"instance_id: {instance_id}" if instance_id else "no instance context (token 'sub' will default to agent owner)"
        logger.info(f"Requesting agent token via client_credentials for audience: {audience}, {instance_ctx_log}")
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        data_dict = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self._client_secret,
            'audience': audience
        }
        if instance_id:
            data_dict['piper_link_instance_id'] = instance_id
        else:
            logger.warning(f"Requesting agent token without piper_link_instance_id for audience {audience}. Token 'sub' will default to agent owner ID. This may lead to permission errors if user context is required for the target resource.")
        
        data_encoded = urlencode(data_dict)
        request_start_time = time.time()
        try:
            response = self._session.post(self.token_url, headers=headers, data=data_encoded, timeout=15)
            if 400 <= response.status_code < 600:
                error_details: Any = None; error_code: str = f'http_{response.status_code}'; error_description: str = f"API Error {response.status_code}"
                try:
                    error_details = response.json(); error_code = error_details.get('error', error_code); error_description = error_details.get('error_description', error_details.get('message', str(error_details)))
                except requests.exceptions.JSONDecodeError:
                    error_details = response.text; error_description = error_details if error_details else error_description
                log_ctx = f"instance {instance_id}" if instance_id else "no instance"
                logger.error(f"Failed to obtain agent token for audience {audience}, {log_ctx}. Status: {response.status_code}, Code: {error_code}, Details: {error_details}")
                raise PiperAuthError(f"API error obtaining agent token: {error_description}", status_code=response.status_code, error_code=error_code, error_details=error_details)
            
            token_data = response.json()
            access_token = token_data.get('access_token')
            expires_in_raw = token_data.get('expires_in', 0)
            try: expires_in = int(expires_in_raw)
            except (ValueError, TypeError): expires_in = 0
            if not access_token:
                raise PiperAuthError("Token missing in response.", status_code=response.status_code, error_details=token_data)
            expiry_timestamp = request_start_time + expires_in
            log_ctx = f"instance {instance_id}" if instance_id else "no instance"
            logger.info(f"Successfully obtained agent token for audience {audience}, {log_ctx} (expires ~{time.ctime(expiry_timestamp)}).")
            return access_token, expiry_timestamp
        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if e.response is not None else None
            error_details = None
            if e.response is not None:
                try:
                    error_details = e.response.json()
                except requests.exceptions.JSONDecodeError:
                    error_details = e.response.text
            log_ctx = f"instance {instance_id}" if instance_id else "no instance"
            logger.error(f"Network error getting agent token for {log_ctx}. Status: {status_code}", exc_info=True)
            raise PiperAuthError(f"Request failed for agent token: {e}", status_code=status_code, error_details=error_details) from e
        except Exception as e:
            log_ctx = f"instance {instance_id}" if instance_id else "no instance"
            logger.error(f"Unexpected error fetching agent token for {log_ctx}: {e}", exc_info=True)
            raise PiperAuthError(f"Unexpected error fetching agent token: {e}") from e

    def _get_valid_agent_token(self, audience: str, instance_id: Optional[str], force_refresh: bool = False) -> str:
        cache_key = (audience, instance_id)
        now = time.time()
        cached_token = self._access_tokens.get(cache_key)
        cached_expiry = self._token_expiries.get(cache_key, 0)
        if not force_refresh and cached_token and cached_expiry > (now + self.DEFAULT_TOKEN_EXPIRY_BUFFER_SECONDS):
            log_ctx = f"instance_id: {instance_id}" if instance_id else "no instance"
            logger.debug(f"Using cached token for audience: {audience}, {log_ctx}")
            return cached_token
        else:
            if cached_token and not force_refresh:
                log_ctx = f"instance_id: {instance_id}" if instance_id else "no instance"
                logger.info(f"Token for audience {audience}, {log_ctx} expired/refreshing.")
            access_token, expiry_timestamp = self._fetch_agent_token(audience=audience, instance_id=instance_id)
            self._access_tokens[cache_key] = access_token
            self._token_expiries[cache_key] = expiry_timestamp
            return access_token

    def _get_instance_id_for_api_call(self, instance_id_param: Optional[str]) -> Optional[str]:
        if instance_id_param: return instance_id_param
        if self._discovered_instance_id: return self._discovered_instance_id
        return self.discover_local_instance_id()

    def _normalize_variable_name(self, variable_name: str) -> str:
        """Converts variable name to lowercase_snake_case."""
        if not variable_name: return "" # Should be caught by earlier validation in calling methods
        s1 = re.sub(r'[-\s]+', '_', variable_name) # Replace hyphens and spaces with underscore
        s2 = re.sub(r'[^\w_]', '', s1)           # Remove non-alphanumeric (except underscore)
        s3 = re.sub(r'_+', '_', s2)              # Replace multiple underscores with single
        return s3.lower()

    def _resolve_piper_variable(self, variable_name: str, instance_id_for_context: str) -> str:
        if not variable_name or not isinstance(variable_name, str): raise ValueError("variable_name must be non-empty string.")
        trimmed_variable_name = variable_name.strip()
        if not trimmed_variable_name: raise ValueError("variable_name cannot be empty after stripping.")
        
        normalized_name = self._normalize_variable_name(trimmed_variable_name)
        if not normalized_name: raise ValueError(f"Original variable name '{variable_name}' normalized to an empty/invalid string.")

        try:
            target_audience = self.resolve_mapping_url
            agent_token = self._get_valid_agent_token(audience=target_audience, instance_id=instance_id_for_context)
            headers = {'Authorization': f'Bearer {agent_token}', 'Content-Type': 'application/json'}
            payload = {'variableName': normalized_name} # Send normalized name
            logger.info(f"Calling (Piper) resolve_variable_mapping for original_var: '{variable_name}', normalized_to: '{normalized_name}', instance: {instance_id_for_context}")
            response = self._session.post(self.resolve_mapping_url, headers=headers, json=payload, timeout=12)
            
            if 400 <= response.status_code < 600:
                error_details: Any = None; error_code: str = f'http_{response.status_code}'; error_description: str = f"API Error {response.status_code}"
                try: error_details = response.json(); error_code = error_details.get('error', error_code); error_description = error_details.get('error_description', error_details.get('message', str(error_details)))
                except requests.exceptions.JSONDecodeError: error_details = response.text; error_description = error_details if error_details else error_description
                logger.error(f"API error resolving mapping for var '{normalized_name}' (original: '{variable_name}'), instance {instance_id_for_context}. Status: {response.status_code}, Code: {error_code}, Details: {error_details}")
                if response.status_code == 401 or error_code == 'invalid_token': self._token_expiries[(target_audience, instance_id_for_context)] = 0
                if response.status_code == 404 or error_code == 'mapping_not_found': raise PiperAuthError(f"No active grant mapping found for var '{normalized_name}' (original: '{variable_name}') for instance '{instance_id_for_context}'. Check Piper UI grants.", status_code=404, error_code='mapping_not_found', error_details=error_details)
                raise PiperAuthError(f"Failed to resolve var mapping: {error_description}", status_code=response.status_code, error_code=error_code, error_details=error_details)
            
            mapping_data = response.json(); credential_id = mapping_data.get('credentialId')
            if not credential_id or not isinstance(credential_id, str):
                raise PiperAuthError("Invalid response from resolve (missing credentialId).", response.status_code, error_details=mapping_data)
            logger.info(f"Piper resolved var '{normalized_name}' (original: '{variable_name}') for instance '{instance_id_for_context}' to credentialId '{credential_id}'.")
            return credential_id
        except (PiperAuthError, ValueError): raise
        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if e.response is not None else None; error_details = None
            if e.response is not None:
                try: error_details = e.response.json()
                except requests.exceptions.JSONDecodeError: error_details = e.response.text
            logger.error(f"Network error calling {self.resolve_mapping_url} for instance {instance_id_for_context} (var: '{normalized_name}'). Status: {status_code}", exc_info=True)
            raise PiperAuthError(f"Network error resolving variable: {e}", status_code=status_code, error_details=error_details) from e
        except Exception as e:
            logger.error(f"Unexpected error resolving variable for instance {instance_id_for_context} (var: '{normalized_name}'): {e}", exc_info=True)
            raise PiperError(f"Unexpected error resolving variable: {e}") from e

    def _fetch_piper_sts_token(self, credential_ids: List[str], instance_id_for_context: str) -> Dict[str, Any]:
        if not credential_ids or not isinstance(credential_ids, list): raise ValueError("credential_ids must be a non-empty list.")
        cleaned_credential_ids = [str(cid).strip() for cid in credential_ids if str(cid).strip()]
        if not cleaned_credential_ids: raise ValueError("credential_ids list empty after cleaning.")
        try:
            target_audience = self.get_scoped_url
            agent_token = self._get_valid_agent_token(audience=target_audience, instance_id=instance_id_for_context)
            scoped_headers = {'Authorization': f'Bearer {agent_token}', 'Content-Type': 'application/json'}
            scoped_payload = {'credentialIds': cleaned_credential_ids}
            logger.info(f"Calling (Piper) get_scoped_credentials for IDs: {cleaned_credential_ids}, instance: {instance_id_for_context}")
            response = self._session.post(self.get_scoped_url, headers=scoped_headers, json=scoped_payload, timeout=15)
            if 400 <= response.status_code < 600:
                error_details: Any = None; error_code: str = f'http_{response.status_code}'; error_description: str = f"API Error {response.status_code}"
                try: error_details = response.json(); error_code = error_details.get('error', error_code); error_description = error_details.get('error_description', error_details.get('message', str(error_details)))
                except requests.exceptions.JSONDecodeError: error_details = response.text; error_description = error_details if error_details else error_description
                logger.error(f"API error getting scoped credentials for instance {instance_id_for_context}. Status: {response.status_code}, Code: {error_code}, Details: {error_details}")
                if response.status_code == 401 or error_code == 'invalid_token': self._token_expiries[(target_audience, instance_id_for_context)] = 0; raise PiperAuthError(f"Agent auth failed for scoped creds: {error_description}", status_code=401, error_code=error_code or 'invalid_token', error_details=error_details)
                if response.status_code == 403 or error_code == 'permission_denied': raise PiperAuthError(f"Permission denied for scoped creds: {error_description}", status_code=403, error_code=error_code or 'permission_denied', error_details=error_details)
                raise PiperAuthError(f"Failed to get scoped creds: {error_description}", status_code=response.status_code, error_code=error_code, error_details=error_details)
            scoped_data = response.json()
            if 'access_token' not in scoped_data or 'granted_credential_ids' not in scoped_data:
                raise PiperAuthError("Invalid response from get_scoped_credentials.", response.status_code, error_details=scoped_data)
            requested_set = set(cleaned_credential_ids); granted_set = set(scoped_data.get('granted_credential_ids', []))
            if requested_set != granted_set: logger.warning(f"Partial success getting credentials for instance {instance_id_for_context}: Granted for {list(granted_set)}, but not for {list(requested_set - granted_set)}.")
            logger.info(f"Piper successfully returned STS token for instance {instance_id_for_context}, granted IDs: {scoped_data.get('granted_credential_ids')}")
            return scoped_data
        except (PiperAuthError, ValueError): raise
        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if e.response is not None else None; error_details = None
            if e.response is not None:
                try: error_details = e.response.json()
                except requests.exceptions.JSONDecodeError: error_details = e.response.text
            logger.error(f"Network error calling {self.get_scoped_url} for instance {instance_id_for_context}. Status: {status_code}", exc_info=True)
            raise PiperAuthError(f"Network error getting scoped creds: {e}", status_code=status_code, error_details=error_details) from e
        except Exception as e:
            logger.error(f"Unexpected error getting scoped creds by ID for instance {instance_id_for_context}: {e}", exc_info=True)
            raise PiperError(f"Unexpected error getting scoped creds: {e}") from e

    def get_secret(self,
                   variable_name: str,
                   instance_id: Optional[str] = None,
                   enable_env_fallback_for_this_call: Optional[bool] = None,
                   fallback_env_var_name: Optional[str] = None
                   ) -> Dict[str, Any]:
        if not variable_name or not isinstance(variable_name, str):
            raise ValueError("variable_name must be a non-empty string.")
        
        piper_error_encountered: Optional[Exception] = None
        effective_instance_id: Optional[str] = None
        
        try:
            effective_instance_id = self._get_instance_id_for_api_call(instance_id)
            if not effective_instance_id:
                raise PiperLinkNeededError()

            logger.info(f"Attempting to retrieve secret for '{variable_name}' via Piper (instance: {effective_instance_id}).")
            # _resolve_piper_variable will use the original variable_name for normalization
            credential_id = self._resolve_piper_variable(variable_name, effective_instance_id)
            piper_sts_response = self._fetch_piper_sts_token([credential_id], effective_instance_id)

            return {
                "value": piper_sts_response.get("access_token"),
                "source": "piper_sts",
                "token_type": "Bearer",
                "expires_in": piper_sts_response.get("expires_in"),
                "piper_credential_id": piper_sts_response.get('granted_credential_ids', [credential_id])[0],
                "piper_instance_id": effective_instance_id
            }
        except PiperLinkNeededError as e:
            piper_error_encountered = e
            logger.info(f"Piper Link setup needed for '{variable_name}'. {e}")
        except PiperAuthError as e:
            piper_error_encountered = e
            if e.error_code in ['mapping_not_found', 'permission_denied']:
                logger.info(f"Piper grant/mapping issue for '{variable_name}' (Code: {e.error_code}). {e}")
            else:
                logger.warning(f"Piper authentication/authorization error for '{variable_name}': {e}")
        except PiperConfigError as e:
            piper_error_encountered = e
            logger.warning(f"Piper SDK configuration error during Piper flow for '{variable_name}': {e}")
        except Exception as e:
            piper_error_encountered = e
            logger.error(f"Unexpected error during Piper credential fetch for '{variable_name}': {e}", exc_info=True)

        _is_fallback_enabled_for_call = self.enable_env_fallback
        if enable_env_fallback_for_this_call is not None:
            _is_fallback_enabled_for_call = enable_env_fallback_for_this_call

        if not _is_fallback_enabled_for_call:
            if piper_error_encountered:
                raise piper_error_encountered
            else: 
                raise PiperConfigError(f"Piper flow not attempted/failed (instanceId: {effective_instance_id}) and fallback disabled for '{variable_name}'.")

        env_var_to_check = fallback_env_var_name
        if not env_var_to_check:
            # Use the original variable_name for map lookup and normalization base
            if self.env_variable_map and variable_name in self.env_variable_map:
                env_var_to_check = self.env_variable_map[variable_name]
                logger.debug(f"Using exact map for original var '{variable_name}': looking for env var '{env_var_to_check}'.")
            else:
                # Normalize the original variable_name for env var construction
                normalized_for_env = variable_name.upper().replace(' ', '_').replace('-', '_')
                # Further cleanup for env var compatibility (remove other special chars if any left)
                normalized_for_env = re.sub(r'[^\w_]', '', normalized_for_env)
                normalized_for_env = re.sub(r'_+', '_', normalized_for_env) # Consolidate underscores

                env_var_to_check = f"{self.env_variable_prefix}{normalized_for_env}"
                logger.debug(f"Using prefix '{self.env_variable_prefix}' for original var '{variable_name}' (normalized to '{normalized_for_env}'): looking for env var '{env_var_to_check}'.")
        else:
            logger.debug(f"Using explicit fallback_env_var_name: '{env_var_to_check}'.")
        
        logger.info(f"Attempting fallback: Reading environment variable '{env_var_to_check}' for Piper variable '{variable_name}'.")
        secret_value_from_env = os.environ.get(env_var_to_check)

        if secret_value_from_env:
            logger.info(f"Successfully retrieved secret from environment variable '{env_var_to_check}'.")
            return {
                "value": secret_value_from_env,
                "source": "environment_variable",
                "env_var_name": env_var_to_check,
                "token_type": "DirectValue",
                "expires_in": None
            }
        else:
            logger.warning(f"Fallback failed: Environment variable '{env_var_to_check}' not set for Piper variable '{variable_name}'.")
            if piper_error_encountered:
                original_error_msg = str(piper_error_encountered)
                appended_msg = f" Also, fallback env var '{env_var_to_check}' not found."
                if isinstance(piper_error_encountered, PiperAuthError):
                    raise PiperAuthError(
                        f"{original_error_msg}{appended_msg}",
                        status_code=getattr(piper_error_encountered, 'status_code', None),
                        error_code=getattr(piper_error_encountered, 'error_code', None),
                        error_details=getattr(piper_error_encountered, 'error_details', None)
                    ) from piper_error_encountered
                elif isinstance(piper_error_encountered, (PiperLinkNeededError, PiperConfigError)):
                    raise type(piper_error_encountered)(
                        f"{original_error_msg}{appended_msg}"
                    ) from piper_error_encountered
                else:
                     raise PiperConfigError(f"Piper flow failed: {original_error_msg}. Fallback env var '{env_var_to_check}' also not found.") from piper_error_encountered
            else:
                raise PiperConfigError(f"Could not retrieve credentials for '{variable_name}'. Piper context not established and environment variable '{env_var_to_check}' not set.")

    def get_credential_id_for_variable(self, variable_name: str, instance_id: Optional[str] = None) -> str:
        logger.warning("get_credential_id_for_variable is an advanced method; prefer get_secret().")
        target_instance_id = self._get_instance_id_for_api_call(instance_id)
        if not target_instance_id:
            raise PiperLinkNeededError("Instance ID required for resolving variable.")
        # _resolve_piper_variable will handle normalization of variable_name
        return self._resolve_piper_variable(variable_name, target_instance_id)

    def get_scoped_credentials_by_id(self, credential_ids: List[str], instance_id: Optional[str] = None) -> Dict[str, Any]:
        logger.warning("get_scoped_credentials_by_id is an advanced method; prefer get_secret().")
        target_instance_id = self._get_instance_id_for_api_call(instance_id)
        if not target_instance_id:
            raise PiperLinkNeededError("Instance ID required for fetching scoped credentials.")
        return self._fetch_piper_sts_token(credential_ids, target_instance_id)