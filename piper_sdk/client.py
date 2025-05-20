# piper_sdk/client.py

import os
import re
import requests
# import time # Not directly used by SDK code itself anymore, but useful for PiperSecretAcquisitionError if it had timestamps
from urllib.parse import urlencode, quote_plus as _quote_plus # For PiperGrantNeededError URL construction
import logging
from typing import List, Dict, Any, Optional, Tuple
import json

# Logging setup
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - PiperSDK - %(levelname)s - %(message)s')

# --- Error classes (Unchanged) ---
class PiperError(Exception):
    """Base class for all Piper SDK errors."""
    pass

class PiperConfigError(PiperError):
    """Errors related to PiperClient configuration."""
    pass

class PiperLinkNeededError(PiperConfigError):
    """Raised when Piper Link context (instanceId) is required but not available."""
    def __init__(self, message="Piper Link instanceId not provided and could not be discovered. Is Piper Link app running?"):
        super().__init__(message)

class PiperAuthError(PiperError):
    """Errors related to authentication or authorization with the Piper backend."""
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

class PiperGrantError(PiperAuthError):
    """Base class for errors related to missing or invalid grants."""
    def __init__(self,
                 message: str,
                 status_code: Optional[int] = None,
                 error_code: Optional[str] = None,
                 error_details: Optional[Any] = None,
                 agent_id_for_grant: Optional[str] = None,
                 variable_name_requested: Optional[str] = None,
                 piper_ui_grant_url_template: Optional[str] = None):
        super().__init__(message, status_code, error_code, error_details)
        self.agent_id_for_grant = agent_id_for_grant
        self.variable_name_requested = variable_name_requested
        self.piper_ui_grant_url_template = piper_ui_grant_url_template
        self.constructed_grant_url = None
        if self.piper_ui_grant_url_template and self.agent_id_for_grant and self.variable_name_requested:
            try:
                base_url = self.piper_ui_grant_url_template.rstrip('/')
                params = {'scope': 'manage_grants', 'client': self.agent_id_for_grant, 'variable': self.variable_name_requested}
                self.constructed_grant_url = f"{base_url}?{urlencode(params, quote_via=_quote_plus)}"
            except Exception as e_url: logger.warning(f"PiperSDK: Could not construct Piper UI grant URL: {e_url}")
    def __str__(self):
        base_str = super().__str__()
        if self.constructed_grant_url: return f"{base_str}\nTo resolve this, you may need to create or activate a grant in Piper. Try visiting: {self.constructed_grant_url}"
        elif self.variable_name_requested: return f"{base_str} (for variable: '{self.variable_name_requested}')"
        return base_str

class PiperGrantNeededError(PiperGrantError):
    def __init__(self, message: str, status_code: Optional[int] = None, error_code: Optional[str] = 'grant_needed', error_details: Optional[Any] = None,
                 agent_id_for_grant: Optional[str] = None, variable_name_requested: Optional[str] = None, piper_ui_grant_url_template: Optional[str] = None):
        super().__init__(message, status_code, error_code, error_details, agent_id_for_grant, variable_name_requested, piper_ui_grant_url_template)

class PiperForbiddenError(PiperAuthError):
    def __init__(self, message: str, status_code: Optional[int] = 403, error_code: Optional[str] = 'permission_denied', error_details: Optional[Any] = None):
        super().__init__(message, status_code, error_code, error_details)

class PiperRawSecretExchangeError(PiperError):
    def __init__(self, message: str, status_code: Optional[int] = None, error_code: Optional[str] = None, error_details: Optional[Any] = None):
        super().__init__(message) # PiperError base takes only message
        self.status_code = status_code
        self.error_code = error_code
        self.error_details = error_details
    def __str__(self): # Custom __str__ to include details
        details_str = f", Details: {self.error_details}" if self.error_details is not None else ""
        status_str = f" (Status: {self.status_code})" if self.status_code is not None else ""
        code_str = f" (Code: {self.error_code})" if self.error_code else ""
        return f"{super().__str__()}{status_str}{code_str}{details_str}"


class PiperSecretAcquisitionError(PiperError):
    def __init__(self, message: str, variable_name: str, attempted_sources_summary: Dict[str, Any]):
        super().__init__(message)
        self.variable_name = variable_name
        self.attempted_sources_summary = attempted_sources_summary
    def __str__(self) -> str:
        details = [f"Failed to retrieve secret for '{self.variable_name}' after trying all configured methods."]
        piper_error = self.attempted_sources_summary.get("Piper")
        if isinstance(piper_error, PiperGrantNeededError): details.append(f"Primary Issue (Piper): {str(piper_error)}")
        elif isinstance(piper_error, PiperLinkNeededError): details.append(f"Primary Issue (Piper): {str(piper_error)} Please ensure Piper Link is running and you are logged in.")
        elif piper_error: details.append(f"Primary Issue (Piper): {str(piper_error)}")
        if len(self.attempted_sources_summary) > 1 or (piper_error and not isinstance(piper_error, (PiperGrantNeededError, PiperLinkNeededError))):
            details.append("Details of all attempts:")
        for source, error_info in self.attempted_sources_summary.items():
            if source == "Piper" and isinstance(piper_error, (PiperGrantNeededError, PiperLinkNeededError)) and len(self.attempted_sources_summary) > 1 :
                 if not details[-1].startswith("Details of all attempts:"): details.append("Details of all attempts:")
                 details.append(f"  - Piper: (See primary issue above)")
                 continue
            details.append(f"  - {source}: {str(error_info)}" if isinstance(error_info, Exception) else f"  - {source}: {error_info}")
        if not self.attempted_sources_summary: details.append("  No acquisition methods were attempted or configured successfully.")
        return "\n".join(details)


class PiperClient:
    DEFAULT_PROJECT_ID: str = "444535882337"
    DEFAULT_REGION: str = "us-central1"
    DEFAULT_PIPER_GET_SCOPED_URL = f"https://getscopedgcpcredentials-{DEFAULT_PROJECT_ID}.{DEFAULT_REGION}.run.app"
    DEFAULT_PIPER_RESOLVE_MAPPING_URL = f"https://piper-resolve-variable-mapping-{DEFAULT_PROJECT_ID}.{DEFAULT_REGION}.run.app"
    DEFAULT_PIPER_EXCHANGE_SECRET_URL = f"https://piper-exchange-sts-for-secret-{DEFAULT_PROJECT_ID}.{DEFAULT_REGION}.run.app"
    DEFAULT_PIPER_LINK_SERVICE_URL = "http://localhost:31477/piper-link-context"
    DEFAULT_PIPER_UI_BASE_URL = "https://agentpiper.com/secrets"
    
    def __init__(self,
                 client_id: str,
                 _piper_system_project_id: Optional[str] = None,
                 _piper_system_region: Optional[str] = None,
                 get_scoped_url: Optional[str] = None,
                 resolve_mapping_url: Optional[str] = None,
                 exchange_secret_url: Optional[str] = None,
                 piper_link_service_url: Optional[str] = None,
                 requests_session: Optional[requests.Session] = None,
                 piper_link_instance_id: Optional[str] = None, 
                 use_piper: bool = True,
                 attempt_local_discovery: bool = True,
                 fallback_to_env: bool = True,
                 env_variable_prefix: str = "", 
                 env_variable_map: Optional[Dict[str, str]] = None,
                 fallback_to_local_config: bool = False,
                 local_config_file_path: Optional[str] = None,
                 piper_ui_grant_page_url: Optional[str] = None
                ):
        if not client_id:
            raise PiperConfigError("client_id is required.")
        self.client_id: str = client_id
        effective_project_id = _piper_system_project_id or self.DEFAULT_PROJECT_ID
        effective_region = _piper_system_region or self.DEFAULT_REGION
        self.get_scoped_url: str = get_scoped_url or f"https://getscopedgcpcredentials-{effective_project_id}.{effective_region}.run.app"
        self.resolve_mapping_url: str = resolve_mapping_url or f"https://piper-resolve-variable-mapping-{effective_project_id}.{effective_region}.run.app"
        self.exchange_secret_url: Optional[str] = exchange_secret_url or f"https://piper-exchange-sts-for-secret-{effective_project_id}.{effective_region}.run.app"
        self.piper_link_service_url: str = piper_link_service_url or self.DEFAULT_PIPER_LINK_SERVICE_URL
        self.piper_ui_grant_page_url: str = piper_ui_grant_page_url or self.DEFAULT_PIPER_UI_BASE_URL
        if self.piper_ui_grant_page_url and not self.piper_ui_grant_page_url.startswith('https://'):
            logger.warning(f"Piper UI Grant Page URL ('{self.piper_ui_grant_page_url}') does not look like a valid HTTPS URL.")
        if self.exchange_secret_url and not self.exchange_secret_url.startswith('https://'):
            raise PiperConfigError(f"Piper Exchange Secret URL ('{self.exchange_secret_url}') must be a valid HTTPS URL.")
        for url_attr_name, url_value_str in [("Piper GetScoped URL", self.get_scoped_url), ("Piper Resolve Mapping URL", self.resolve_mapping_url)]:
            if not url_value_str or not url_value_str.startswith('https://'):
                raise PiperConfigError(f"{url_attr_name} ('{url_value_str}') must be a valid HTTPS URL.")
        if self.piper_link_service_url != self.DEFAULT_PIPER_LINK_SERVICE_URL and not self.piper_link_service_url.startswith('http://localhost'):
             logger.warning(f"Piper Link Service URL ('{self.piper_link_service_url}') is not the default localhost URL and does not start with http://localhost.")
        self._session = requests_session if requests_session else requests.Session()
        sdk_version = "0.6.0" 
        self._session.headers.update({'User-Agent': f'Pyper-SDK/{sdk_version}'})
        self._configured_instance_id: Optional[str] = piper_link_instance_id
        self._discovered_instance_id: Optional[str] = None
        self.use_piper = use_piper
        self.attempt_local_discovery = attempt_local_discovery
        self.fallback_to_env = fallback_to_env
        self.env_variable_prefix = env_variable_prefix
        self.env_variable_map = env_variable_map if env_variable_map is not None else {}
        self.fallback_to_local_config = fallback_to_local_config
        if fallback_to_local_config and not local_config_file_path:
            raise PiperConfigError("If fallback_to_local_config is True, local_config_file_path must be provided.")
        self.local_config_file_path = os.path.expanduser(local_config_file_path) if local_config_file_path else None
        log_msg_parts = [f"PiperClient initialized for agent client_id '{self.client_id[:8]}...' (SDK no longer handles client_secret).", f"Acquisition Strategy: Piper={'Enabled' if self.use_piper else 'Disabled'}"]
        if self.use_piper:
            if self._configured_instance_id: log_msg_parts.append(f"Using provided instance_id: {self._configured_instance_id}")
            elif self.attempt_local_discovery: log_msg_parts.append("Local Piper Link instance_id discovery: Enabled.")
            else: log_msg_parts.append("Local Piper Link instance_id discovery: Disabled.")
        if self.fallback_to_env: log_msg_parts.append(f"Env Fallback: Enabled (Prefix: '{self.env_variable_prefix}', Map: {'Yes' if self.env_variable_map else 'No'})")
        else: log_msg_parts.append("Env Fallback: Disabled")
        if self.fallback_to_local_config:
            if self.local_config_file_path: log_msg_parts.append(f"Local Config Fallback: Enabled (Path: '{self.local_config_file_path}')")
        else: log_msg_parts.append("Local Config Fallback: Disabled")
        if self.exchange_secret_url:
            source_val = "provided" if exchange_secret_url else "defaulted"
            log_msg_parts.append(f"Raw secret exchange GCF ({source_val}): {self.exchange_secret_url}")
        else: log_msg_parts.append("Raw secret exchange URL is not configured.")
        if self.piper_ui_grant_page_url: log_msg_parts.append(f"Piper UI grant page base: {self.piper_ui_grant_page_url}")
        logger.info(". ".join(log_msg_parts) + ".")

    def discover_local_instance_id(self, force_refresh: bool = False) -> Optional[str]:
        if self._configured_instance_id:
            logger.debug(f"Using instance_id explicitly provided at PiperClient init ('{self._configured_instance_id}'), skipping local discovery.")
            return self._configured_instance_id
        if not self.use_piper or not self.attempt_local_discovery:
            logger.debug("Local discovery skipped: Piper usage or local discovery is disabled in client config.")
            self._discovered_instance_id = None
            return None
        if self._discovered_instance_id and not force_refresh:
            logger.debug(f"Using cached discovered instanceId: {self._discovered_instance_id}")
            return self._discovered_instance_id
        logger.info(f"Attempting to discover Piper Link instanceId from: {self.piper_link_service_url}")
        try:
            response = self._session.get(self.piper_link_service_url, timeout=1.0)
            response.raise_for_status()
            data = response.json()
            instance_id = data.get("instanceId")
            if instance_id and isinstance(instance_id, str):
                logger.info(f"Discovered and cached Piper Link instanceId: {instance_id}")
                self._discovered_instance_id = instance_id; return instance_id
            else: logger.warning(f"Local Piper Link service responded but instanceId was missing/invalid: {data}")
        except requests.exceptions.ConnectionError: logger.warning(f"Local Piper Link service not found/running at {self.piper_link_service_url}.")
        except requests.exceptions.Timeout: logger.warning(f"Timeout connecting to local Piper Link service at {self.piper_link_service_url}.")
        except requests.exceptions.RequestException as e: logger.warning(f"Request error querying local Piper Link service at {self.piper_link_service_url}: {e}")
        except json.JSONDecodeError as e: logger.warning(f"JSON decode error from local Piper Link service at {self.piper_link_service_url}: {e}")
        except Exception as e: logger.error(f"Unexpected error querying local Piper Link service at {self.piper_link_service_url}: {e}", exc_info=True)
        self._discovered_instance_id = None; return None

    def _get_instance_id_for_api_call(self, piper_link_instance_id_for_call: Optional[str]) -> Optional[str]:
        if piper_link_instance_id_for_call:
            logger.debug(f"Using instance_id passed directly to API call method: {piper_link_instance_id_for_call}")
            return piper_link_instance_id_for_call
        if self._configured_instance_id:
            logger.debug(f"Using instance_id explicitly provided at PiperClient initialization: {self._configured_instance_id}")
            return self._configured_instance_id
        if self.attempt_local_discovery:
            return self.discover_local_instance_id()
        logger.debug("No explicit instance_id provided, and local discovery is disabled.")
        return self._discovered_instance_id

    def _normalize_variable_name(self, variable_name: str) -> str:
        if not variable_name: return ""
        s1 = re.sub(r'[-\s]+', '_', variable_name); s2 = re.sub(r'[^\w_]', '', s1)
        s3 = re.sub(r'_+', '_', s2); return s3.lower()

    def _resolve_piper_variable(self, variable_name: str, instance_id_for_context: str) -> str:
        if not variable_name or not isinstance(variable_name, str): raise ValueError("variable_name must be non-empty string.")
        trimmed_variable_name = variable_name.strip()
        if not trimmed_variable_name: raise ValueError("variable_name cannot be empty after stripping.")
        normalized_name = self._normalize_variable_name(trimmed_variable_name)
        if not normalized_name: raise ValueError(f"Original variable name '{variable_name}' normalized to an empty/invalid string.")
        try:
            headers = {'Content-Type': 'application/json'}
            payload = {'agentClientId': self.client_id, 'instanceId': instance_id_for_context, 'variableName': normalized_name}
            logger.info(f"Calling (Piper) resolve_variable_mapping for original_var: '{trimmed_variable_name}' (normalized: '{normalized_name}'), agent: '{self.client_id[:8]}...', instance: {instance_id_for_context}")
            response = self._session.post(self.resolve_mapping_url, headers=headers, json=payload, timeout=12)
            if 400 <= response.status_code < 600:
                error_details: Any = None; error_code_from_resp: str = f'http_{response.status_code}'; error_description: str = f"API Error {response.status_code}"
                try:
                    error_details = response.json(); error_code_from_resp = error_details.get('error', error_code_from_resp)
                    error_description = error_details.get('error_description', error_details.get('message', str(error_details)))
                except requests.exceptions.JSONDecodeError: error_details = response.text; error_description = error_details if error_details else error_description
                logger.error(f"API error resolving mapping for var '{normalized_name}', agent {self.client_id[:8]}, instance {instance_id_for_context}. Status: {response.status_code}, Code: {error_code_from_resp}, Details: {error_details}")
                if response.status_code == 404 and error_code_from_resp == 'mapping_not_found':
                    raise PiperGrantNeededError(message=f"No active grant mapping found for variable '{normalized_name}' (original: '{trimmed_variable_name}') for this user context.", status_code=404, error_code='mapping_not_found', error_details=error_details, agent_id_for_grant=self.client_id, variable_name_requested=trimmed_variable_name, piper_ui_grant_url_template=self.piper_ui_grant_page_url)
                if response.status_code == 401:
                     raise PiperAuthError(f"Auth/context error resolving var mapping: {error_description}", status_code=response.status_code, error_code=error_code_from_resp, error_details=error_details)
                if response.status_code == 403:
                     raise PiperForbiddenError(f"Permission denied resolving var mapping: {error_description}", status_code=response.status_code, error_code=error_code_from_resp, error_details=error_details)
                # *** MODIFICATION 1 START ***
                error_msg_with_details = f"Failed to resolve var mapping: {error_description}"
                if error_details:
                    try:
                        details_str = json.dumps(error_details) 
                        if len(details_str) > 200: details_str = details_str[:200] + "..."
                        error_msg_with_details += f" (GCF Details: {details_str})"
                    except TypeError: 
                        error_msg_with_details += f" (GCF Details: {str(error_details)[:200]})"
                raise PiperError(error_msg_with_details)
                # *** MODIFICATION 1 END ***
            mapping_data = response.json(); credential_id = mapping_data.get('credentialId')
            if not credential_id or not isinstance(credential_id, str):
                raise PiperError("Invalid response from resolve_variable_mapping (missing or invalid credentialId).") # Removed error_details here for simplicity
            logger.info(f"Piper resolved var '{normalized_name}' to credentialId '{credential_id}'.")
            return credential_id
        except (PiperGrantNeededError, PiperAuthError, PiperForbiddenError, ValueError): raise
        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if e.response is not None else None; error_details_text = None
            if e.response is not None: error_details_text = e.response.text
            logger.error(f"Network error calling {self.resolve_mapping_url} for var '{normalized_name}'. Status: {status_code}", exc_info=True)
            raise PiperError(f"Network error resolving variable: {e}") from e # Removed error_details for simplicity
        except Exception as e:
            logger.error(f"Unexpected error resolving variable '{normalized_name}': {e}", exc_info=True)
            raise PiperError(f"Unexpected error resolving variable: {e}") from e

    def _fetch_piper_sts_token(self, credential_ids: List[str], instance_id_for_context: str) -> Dict[str, Any]:
        if not credential_ids or not isinstance(credential_ids, list): raise ValueError("credential_ids must be a non-empty list.")
        cleaned_credential_ids = [str(cid).strip() for cid in credential_ids if str(cid).strip()]
        if not cleaned_credential_ids: raise ValueError("credential_ids list empty after cleaning.")
        try:
            headers = {'Content-Type': 'application/json'}
            payload = {'agentClientId': self.client_id, 'instanceId': instance_id_for_context, 'credentialIds': cleaned_credential_ids}
            logger.info(f"Calling (Piper) get_scoped_credentials for IDs: {cleaned_credential_ids}, agent: '{self.client_id[:8]}...', instance: {instance_id_for_context}")
            response = self._session.post(self.get_scoped_url, headers=headers, json=payload, timeout=15)
            if 400 <= response.status_code < 600:
                error_details: Any = None; error_code_from_resp: str = f'http_{response.status_code}'; error_description: str = f"API Error {response.status_code}"
                try:
                    error_details = response.json(); error_code_from_resp = error_details.get('error', error_code_from_resp)
                    error_description = error_details.get('error_description', error_details.get('message', str(error_details)))
                except requests.exceptions.JSONDecodeError: error_details = response.text; error_description = error_details if error_details else error_description
                logger.error(f"API error getting scoped credentials agent {self.client_id[:8]}, instance {instance_id_for_context}. Status: {response.status_code}, Code: {error_code_from_resp}, Details: {error_details}")
                if response.status_code == 401:
                     raise PiperAuthError(f"Auth/context error for scoped creds: {error_description}", status_code=401, error_code=error_code_from_resp or 'unauthorized', error_details=error_details)
                if response.status_code == 403 or error_code_from_resp == 'permission_denied':
                    raise PiperForbiddenError(f"Permission denied for scoped creds: {error_description}", status_code=403, error_code=error_code_from_resp or 'permission_denied', error_details=error_details)
                # *** MODIFICATION 2 START ***
                error_msg_with_details_sts = f"Failed to get scoped creds: {error_description}"
                if error_details:
                    try:
                        details_str_sts = json.dumps(error_details)
                        if len(details_str_sts) > 200: details_str_sts = details_str_sts[:200] + "..."
                        error_msg_with_details_sts += f" (GCF Details: {details_str_sts})"
                    except TypeError:
                        error_msg_with_details_sts += f" (GCF Details: {str(error_details)[:200]})"
                raise PiperError(error_msg_with_details_sts)
                # *** MODIFICATION 2 END ***
            scoped_data = response.json()
            if 'access_token' not in scoped_data or 'granted_credential_ids' not in scoped_data:
                raise PiperError("Invalid response from get_scoped_credentials (missing access_token or granted_credential_ids).") # Removed error_details for simplicity
            requested_set = set(cleaned_credential_ids); granted_set = set(scoped_data.get('granted_credential_ids', []))
            if not granted_set:
                 logger.error(f"Piper returned no granted_credential_ids for instance {instance_id_for_context} (requested: {cleaned_credential_ids}).")
                 raise PiperForbiddenError(f"Permission effectively denied for all requested credential_ids: {cleaned_credential_ids}", status_code=response.status_code or 403, error_code='permission_denied_for_all_ids', error_details=scoped_data) # Added status_code
            if requested_set != granted_set: logger.warning(f"Partial success getting credentials for instance {instance_id_for_context}: Granted for {list(granted_set)}, but not for {list(requested_set - granted_set)}.")
            logger.info(f"Piper successfully returned STS token for instance {instance_id_for_context}, granted IDs: {scoped_data.get('granted_credential_ids')}")
            return scoped_data
        except (PiperAuthError, PiperForbiddenError, ValueError): raise
        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if e.response is not None else None; error_details_text = None
            if e.response is not None: error_details_text = e.response.text
            logger.error(f"Network error calling {self.get_scoped_url}. Status: {status_code}", exc_info=True)
            raise PiperError(f"Network error getting scoped creds: {e}") from e # Removed error_details
        except Exception as e:
            logger.error(f"Unexpected error getting scoped creds: {e}", exc_info=True)
            raise PiperError(f"Unexpected error getting scoped creds: {e}") from e

    def get_secret(self, variable_name: str, piper_link_instance_id_for_call: Optional[str] = None, fetch_raw_secret: bool = False) -> Dict[str, Any]:
        if not variable_name or not isinstance(variable_name, str): raise PiperConfigError("variable_name must be a non-empty string.")
        original_variable_name_for_error_reporting = variable_name.strip()
        if not original_variable_name_for_error_reporting: raise PiperConfigError("variable_name cannot be empty after stripping.")
        attempted_sources_summary: Dict[str, Any] = {}
        if self.use_piper:
            logger.info(f"GET_SECRET '{original_variable_name_for_error_reporting}': Attempting Piper tier.")
            effective_instance_id: Optional[str] = None; piper_tier_error: Optional[Exception] = None
            try:
                effective_instance_id = self._get_instance_id_for_api_call(piper_link_instance_id_for_call)
                if not effective_instance_id:
                    missing_reason_parts = []
                    if piper_link_instance_id_for_call: missing_reason_parts.append("provided to get_secret()")
                    if self._configured_instance_id: missing_reason_parts.append("provided at PiperClient initialization")
                    if not missing_reason_parts and self.attempt_local_discovery: missing_reason_parts.append("discovered via Piper Link service (discovery may have failed or is disabled)")
                    elif not missing_reason_parts and not self.attempt_local_discovery: missing_reason_parts.append("no instance_id provided and local discovery is disabled")
                    link_needed_msg = f"Piper Link instanceId is required for Piper tier but was not ({' or '.join(missing_reason_parts) if missing_reason_parts else 'available'})."
                    raise PiperLinkNeededError(link_needed_msg)
                logger.debug(f"GET_SECRET '{original_variable_name_for_error_reporting}': Using instance_id '{effective_instance_id}' for Piper flow (Agent: {self.client_id[:8]}...).")
                credential_id = self._resolve_piper_variable(original_variable_name_for_error_reporting, effective_instance_id)
                piper_sts_response_data = self._fetch_piper_sts_token([credential_id], effective_instance_id)
                sts_token_value = piper_sts_response_data.get("access_token"); granted_piper_cred_id = piper_sts_response_data.get('granted_credential_ids', [credential_id])[0]
                if not fetch_raw_secret:
                    logger.info(f"GET_SECRET '{original_variable_name_for_error_reporting}': Successfully retrieved STS token from Piper.")
                    return {"value": sts_token_value, "source": "piper_sts", "token_type": "Bearer", "expires_in": piper_sts_response_data.get("expires_in"), "piper_credential_id": granted_piper_cred_id, "piper_instance_id": effective_instance_id}
                else:
                    logger.info(f"GET_SECRET '{original_variable_name_for_error_reporting}': STS token obtained, now attempting raw secret exchange from Piper.")
                    if not self.exchange_secret_url: raise PiperConfigError("Raw secret fetch requested, but 'exchange_secret_url' is not configured.")
                    if not granted_piper_cred_id: raise PiperError("Internal SDK Error: piper_credential_id missing before raw exchange.")
                    exchange_headers = {"Content-Type": "application/json"}
                    exchange_payload = {"agentClientId": self.client_id, "instanceId": effective_instance_id, "piperCredentialId": granted_piper_cred_id}
                    logger.debug(f"SDK: Calling exchange_secret_url ('{self.exchange_secret_url}') for raw secret. Payload: {exchange_payload}")
                    api_response = self._session.post(self.exchange_secret_url, headers=exchange_headers, json=exchange_payload, timeout=10)
                    if 400 <= api_response.status_code < 600:
                        err_details_exc: Any = None; err_code_exc: str = f'http_{api_response.status_code}'; err_desc_exc: str = f"Raw Secret Exchange GCF Error {api_response.status_code}"
                        try:
                            err_details_exc = api_response.json(); err_code_exc = err_details_exc.get('error', err_code_exc); err_desc_exc = err_details_exc.get('error_description', err_details_exc.get('message', str(err_details_exc)))
                        except requests.exceptions.JSONDecodeError: err_details_exc = api_response.text; err_desc_exc = err_details_exc if err_details_exc else err_desc_exc
                        raise PiperRawSecretExchangeError(f"Failed to exchange STS for raw secret: {err_desc_exc}", status_code=api_response.status_code, error_code=err_code_exc, error_details=err_details_exc)
                    raw_secret_data = api_response.json(); raw_secret_value = raw_secret_data.get('secret_value')
                    if raw_secret_value is None:
                        # *** MODIFICATION 3 START ***
                        error_message_raw_missing = "Raw secret value key 'secret_value' missing or null in exchange GCF response."
                        if raw_secret_data:
                            try:
                                details_str_raw = json.dumps(raw_secret_data)
                                if len(details_str_raw) > 150: details_str_raw = details_str_raw[:150] + "..."
                                error_message_raw_missing += f" (Response: {details_str_raw})"
                            except TypeError:
                                 error_message_raw_missing += f" (Response: {str(raw_secret_data)[:150]})"
                        raise PiperError(error_message_raw_missing)
                        # *** MODIFICATION 3 END ***
                    logger.info(f"GET_SECRET '{original_variable_name_for_error_reporting}': Successfully retrieved raw secret from Piper.")
                    return {"value": raw_secret_value, "source": "piper_raw_secret", "piper_credential_id": granted_piper_cred_id, "piper_instance_id": effective_instance_id}
            except (PiperLinkNeededError, PiperGrantNeededError, PiperForbiddenError, PiperAuthError, PiperRawSecretExchangeError, PiperConfigError, PiperError) as e:
                piper_tier_error = e; logger.warning(f"GET_SECRET '{original_variable_name_for_error_reporting}': Piper tier failed: {type(e).__name__} - {str(e).splitlines()[0]}")
            except Exception as e:
                # *** MODIFICATION 4 START ***
                error_message = f"Unexpected error during Piper tier operation for '{original_variable_name_for_error_reporting}': {type(e).__name__} - {str(e)}"
                piper_tier_error = PiperError(error_message)
                # *** MODIFICATION 4 END ***
                logger.error(f"GET_SECRET '{original_variable_name_for_error_reporting}': Unexpected error in Piper tier: {error_message}", exc_info=True) # Log original error too
            if piper_tier_error: attempted_sources_summary["Piper"] = piper_tier_error
        if self.fallback_to_env and ("Piper" not in attempted_sources_summary or attempted_sources_summary.get("Piper") is not None):
            logger.info(f"GET_SECRET '{original_variable_name_for_error_reporting}': Attempting Environment Variable tier.")
            env_var_to_check: Optional[str] = None
            if self.env_variable_map and original_variable_name_for_error_reporting in self.env_variable_map: env_var_to_check = self.env_variable_map[original_variable_name_for_error_reporting]
            else: normalized_for_env = original_variable_name_for_error_reporting.upper(); normalized_for_env = re.sub(r'[^A-Z0-9_]', '_', normalized_for_env); normalized_for_env = re.sub(r'_+', '_', normalized_for_env); env_var_to_check = f"{self.env_variable_prefix}{normalized_for_env}"
            secret_value_from_env = os.environ.get(env_var_to_check)
            if secret_value_from_env is not None:
                logger.info(f"GET_SECRET '{original_variable_name_for_error_reporting}': Successfully retrieved from env var '{env_var_to_check}'.")
                return {"value": secret_value_from_env, "source": "environment_variable", "env_var_name_used": env_var_to_check, "token_type": "DirectValue", "expires_in": None}
            else: failure_msg = f"Environment variable '{env_var_to_check}' not set."; attempted_sources_summary["EnvironmentVariable"] = failure_msg; logger.info(f"GET_SECRET '{original_variable_name_for_error_reporting}': Env tier failed: {failure_msg}")
        if self.fallback_to_local_config and self.local_config_file_path and (("Piper" not in attempted_sources_summary or attempted_sources_summary.get("Piper") is not None) and ("EnvironmentVariable" not in attempted_sources_summary or attempted_sources_summary.get("EnvironmentVariable") is not None) ):
            logger.info(f"GET_SECRET '{original_variable_name_for_error_reporting}': Attempting Local Config File tier (Path: '{self.local_config_file_path}').")
            local_config_tier_error: Optional[Any] = None; source_key_local_config = f"LocalConfigFile ({self.local_config_file_path})"
            try:
                if not os.path.exists(self.local_config_file_path): raise FileNotFoundError(f"File not found: {self.local_config_file_path}")
                if not os.access(self.local_config_file_path, os.R_OK): raise PermissionError(f"Read permission denied for file: {self.local_config_file_path}")
                with open(self.local_config_file_path, 'r') as f: config_data = json.load(f)
                if original_variable_name_for_error_reporting in config_data:
                    secret_value_from_config = config_data[original_variable_name_for_error_reporting]
                    logger.info(f"GET_SECRET '{original_variable_name_for_error_reporting}': Successfully retrieved from local config file.")
                    return {"value": secret_value_from_config, "source": "local_config_file", "config_file_path": self.local_config_file_path, "token_type": "DirectValue", "expires_in": None}
                else: local_config_tier_error = f"Variable '{original_variable_name_for_error_reporting}' not found in the config file."
            except FileNotFoundError as e_fnf: local_config_tier_error = e_fnf
            except PermissionError as e_perm: local_config_tier_error = e_perm
            except json.JSONDecodeError as e_json: local_config_tier_error = PiperError(f"Error decoding JSON from local config file '{self.local_config_file_path}': {e_json}")
            except Exception as e_local_cfg: local_config_tier_error = PiperError(f"Unexpected error reading local config file '{self.local_config_file_path}': {e_local_cfg}")
            if local_config_tier_error: attempted_sources_summary[source_key_local_config] = local_config_tier_error; logger.warning(f"GET_SECRET '{original_variable_name_for_error_reporting}': Local Config tier failed: {str(local_config_tier_error).splitlines()[0]}")
        if not attempted_sources_summary: logger.error(f"GET_SECRET '{original_variable_name_for_error_reporting}': No acquisition tiers were successfully run or configured."); attempted_sources_summary["SDKInternal"] = "No acquisition methods were enabled or attempted."
        final_error_message = f"Failed to acquire secret for '{original_variable_name_for_error_reporting}'."; logger.error(f"GET_SECRET '{original_variable_name_for_error_reporting}': All configured tiers failed. Raising PiperSecretAcquisitionError. Summary: {attempted_sources_summary}")
        raise PiperSecretAcquisitionError(message=final_error_message, variable_name=original_variable_name_for_error_reporting, attempted_sources_summary=attempted_sources_summary)

    def get_credential_id_for_variable(self, variable_name: str, piper_link_instance_id_for_call: Optional[str] = None) -> str:
        logger.warning("get_credential_id_for_variable is an advanced method; prefer get_secret().")
        if not self.use_piper: raise PiperConfigError("Cannot get credential_id: Piper usage is disabled in client configuration.")
        target_instance_id = self._get_instance_id_for_api_call(piper_link_instance_id_for_call)
        if not target_instance_id: raise PiperLinkNeededError("Instance ID required for resolving variable (neither provided nor discovered via Piper Link when enabled).")
        return self._resolve_piper_variable(variable_name, target_instance_id)

    def get_scoped_credentials_by_id(self, credential_ids: List[str], piper_link_instance_id_for_call: Optional[str] = None) -> Dict[str, Any]:
        logger.warning("get_scoped_credentials_by_id is an advanced method; prefer get_secret().")
        if not self.use_piper: raise PiperConfigError("Cannot get scoped credentials by ID: Piper usage is disabled in client configuration.")
        target_instance_id = self._get_instance_id_for_api_call(piper_link_instance_id_for_call)
        if not target_instance_id: raise PiperLinkNeededError("Instance ID required for fetching scoped credentials (neither provided nor discovered via Piper Link when enabled).")
        return self._fetch_piper_sts_token(credential_ids, target_instance_id)