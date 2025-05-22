# piper_sdk/client.py

import os
import re
import requests
from urllib.parse import urlencode, quote_plus as _quote_plus 
import logging
from typing import List, Dict, Any, Optional, Tuple
import json

logger = logging.getLogger(__name__)
if not logger.handlers:
    _default_handler = logging.StreamHandler()
    _default_formatter = logging.Formatter('%(asctime)s - PiperSDK - %(levelname)s - %(message)s')
    _default_handler.setFormatter(_default_formatter)
    logger.addHandler(_default_handler)
    logger.setLevel(logging.INFO) 
    logger.propagate = False 

class PiperError(Exception): pass
class PiperConfigError(PiperError): pass
class PiperLinkNeededError(PiperConfigError):
    def __init__(self, message="Piper Link instanceId not provided and could not be discovered. Is Piper Link app running?"):
        super().__init__(message)
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

class PiperGrantError(PiperAuthError):
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
                params = {
                    'response_type': 'code',
                    'scope': 'manage_grants', 
                    'client': self.agent_id_for_grant,
                    'variable': self.variable_name_requested 
                }
                self.constructed_grant_url = f"{base_url}?{urlencode(params, quote_via=_quote_plus)}"
            except Exception as e_url: 
                logger.warning(f"PiperSDK: Could not construct Piper UI grant URL: {e_url}")
    
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
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.error_details = error_details
    def __str__(self):
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
    DEFAULT_PIPER_UI_BASE_URL = "https://agentpiper.com/secrets" # Default base for grant UI
    
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
                 piper_ui_grant_page_url: Optional[str] = None # User can override the base URL
                ):
        self._initialization_error: Optional[PiperConfigError] = None
        self.client_initialization_ok: bool = True
        self._last_get_secret_errors: Dict[str, PiperError] = {}

        if not client_id: # type: ignore 
            init_err_msg = "PiperClient critical configuration error: client_id is required."
            logger.critical(init_err_msg)
            self._initialization_error = PiperConfigError(init_err_msg)
            self.client_initialization_ok = False
            self.client_id = "" 
        else:
            self.client_id: str = client_id

        effective_project_id = _piper_system_project_id or self.DEFAULT_PROJECT_ID
        effective_region = _piper_system_region or self.DEFAULT_REGION
        self.get_scoped_url: str = get_scoped_url or f"https://getscopedgcpcredentials-{effective_project_id}.{effective_region}.run.app"
        self.resolve_mapping_url: str = resolve_mapping_url or f"https://piper-resolve-variable-mapping-{effective_project_id}.{effective_region}.run.app"
        self.exchange_secret_url: Optional[str] = exchange_secret_url or f"https://piper-exchange-sts-for-secret-{effective_project_id}.{effective_region}.run.app"
        self.piper_link_service_url: str = piper_link_service_url or self.DEFAULT_PIPER_LINK_SERVICE_URL
        self.piper_ui_grant_page_url: str = piper_ui_grant_page_url or self.DEFAULT_PIPER_UI_BASE_URL

        if self.client_initialization_ok: 
            critical_urls_to_check = {
                "Piper GetScoped URL": self.get_scoped_url,
                "Piper Resolve Mapping URL": self.resolve_mapping_url,
            }
            if self.exchange_secret_url: 
                critical_urls_to_check["Piper Exchange Secret URL"] = self.exchange_secret_url
            for name, url_val in critical_urls_to_check.items():
                if not url_val or not isinstance(url_val, str) or not url_val.startswith('https://'):
                    init_err_msg = f"PiperClient critical configuration error: {name} ('{url_val}') must be a valid HTTPS URL."
                    logger.critical(init_err_msg)
                    if not self._initialization_error: self._initialization_error = PiperConfigError(init_err_msg) 
                    self.client_initialization_ok = False
                    break 
            if self.piper_ui_grant_page_url and not self.piper_ui_grant_page_url.startswith('https://'):
                logger.warning(f"Piper UI Grant Page URL ('{self.piper_ui_grant_page_url}') does not look like a valid HTTPS URL. This might affect grant links.")
            if self.piper_link_service_url != self.DEFAULT_PIPER_LINK_SERVICE_URL and not self.piper_link_service_url.startswith('http://localhost'):
                 logger.warning(f"Piper Link Service URL ('{self.piper_link_service_url}') is not the default localhost URL and does not start with http://localhost. This is unusual for local discovery.")

        self._session = requests_session if requests_session else requests.Session()
        sdk_version = "0.7.0-dev" 
        self._session.headers.update({'User-Agent': f'Pyper-SDK/{sdk_version}'})
        self._configured_instance_id: Optional[str] = piper_link_instance_id
        self._discovered_instance_id: Optional[str] = None 
        self.use_piper = use_piper
        self.attempt_local_discovery = attempt_local_discovery
        self.fallback_to_env = fallback_to_env
        self.env_variable_prefix = env_variable_prefix
        self.env_variable_map = env_variable_map if env_variable_map is not None else {}
        self.fallback_to_local_config = fallback_to_local_config
        self.local_config_file_path = os.path.expanduser(local_config_file_path) if local_config_file_path else None
        if self.client_initialization_ok and fallback_to_local_config and not self.local_config_file_path:
            init_err_msg = "PiperClient critical configuration error: If fallback_to_local_config is True, local_config_file_path must be provided."
            logger.critical(init_err_msg)
            if not self._initialization_error: self._initialization_error = PiperConfigError(init_err_msg)
            self.client_initialization_ok = False

        if not self.client_initialization_ok and self._initialization_error:
            logger.error(f"PiperClient initialization FAILED. Error: {self._initialization_error}")
        else:
            log_msg_parts = [f"PiperClient initialized for agent client_id '{self.client_id[:8]}...' (SDK no longer handles client_secret)."]
            if not self.client_initialization_ok: 
                log_msg_parts.insert(0, "[WARNING: Client initialized but client_initialization_ok is False without a specific error stored, check config]")
            log_msg_parts.append(f"Acquisition Strategy: Piper={'Enabled' if self.use_piper else 'Disabled'}")
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
            elif self.use_piper:
                 log_msg_parts.append("Raw secret exchange URL is not configured (will prevent raw secret fetching via Piper).")
            if self.piper_ui_grant_page_url: log_msg_parts.append(f"Piper UI grant page base: {self.piper_ui_grant_page_url}")
            logger.info(". ".join(log_msg_parts) + ".")

    def discover_local_instance_id(self, force_refresh: bool = False) -> Optional[str]:
        if not self.client_initialization_ok:
            logger.warning("discover_local_instance_id called on a misconfigured client. Discovery will likely fail or be irrelevant.")
            return None
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
        normalized_name = self._normalize_variable_name(variable_name) 
        if not normalized_name: raise ValueError(f"Original variable name '{variable_name}' normalized to an empty/invalid string.")
        try:
            headers = {'Content-Type': 'application/json'}
            payload = {'agentClientId': self.client_id, 'instanceId': instance_id_for_context, 'variableName': normalized_name}
            logger.info(f"Calling (Piper) resolve_variable_mapping for var_for_lookup: '{normalized_name}' (from original: '{variable_name}'), agent: '{self.client_id[:8]}...', instance: {instance_id_for_context}")
            response = self._session.post(self.resolve_mapping_url, headers=headers, json=payload, timeout=12)
            if 400 <= response.status_code < 600:
                error_details: Any = None; error_code_from_resp: str = f'http_{response.status_code}'; error_description: str = f"API Error {response.status_code}"
                try:
                    error_details = response.json(); error_code_from_resp = error_details.get('error', error_code_from_resp)
                    error_description = error_details.get('error_description', error_details.get('message', str(error_details)))
                except requests.exceptions.JSONDecodeError: error_details = response.text; error_description = error_details if error_details else error_description
                logger.error(f"API error resolving mapping for var '{normalized_name}', agent {self.client_id[:8]}, instance {instance_id_for_context}. Status: {response.status_code}, Code: {error_code_from_resp}, Details: {error_details}")
                if response.status_code == 404 and error_code_from_resp == 'mapping_not_found':
                    raise PiperGrantNeededError(message=f"No active grant mapping found for variable '{normalized_name}' (original: '{variable_name}') for this user context.", status_code=404, error_code='mapping_not_found', error_details=error_details, agent_id_for_grant=self.client_id, variable_name_requested=variable_name, piper_ui_grant_url_template=self.piper_ui_grant_page_url)
                if response.status_code == 401:
                     raise PiperAuthError(f"Auth/context error resolving var mapping: {error_description}", status_code=response.status_code, error_code=error_code_from_resp, error_details=error_details)
                if response.status_code == 403:
                     raise PiperForbiddenError(f"Permission denied resolving var mapping: {error_description}", status_code=response.status_code, error_code=error_code_from_resp, error_details=error_details)
                error_msg_with_details = f"Failed to resolve var mapping: {error_description}"
                if error_details:
                    try:
                        details_str = json.dumps(error_details); 
                        if len(details_str) > 200: details_str = details_str[:200] + "..."
                        error_msg_with_details += f" (GCF Details: {details_str})"
                    except TypeError: error_msg_with_details += f" (GCF Details: {str(error_details)[:200]})"
                raise PiperError(error_msg_with_details)
            mapping_data = response.json(); credential_id = mapping_data.get('credentialId')
            if not credential_id or not isinstance(credential_id, str):
                raise PiperError("Invalid response from resolve_variable_mapping (missing or invalid credentialId).")
            logger.info(f"Piper resolved var '{normalized_name}' (from original: '{variable_name}') to credentialId '{credential_id}'.")
            return credential_id
        except (PiperGrantNeededError, PiperAuthError, PiperForbiddenError, ValueError): raise
        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if e.response is not None else None;
            logger.error(f"Network error calling {self.resolve_mapping_url} for var '{normalized_name}'. Status: {status_code}", exc_info=True)
            raise PiperError(f"Network error resolving variable: {e}") from e
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
                    raise PiperForbiddenError(f"Permission denied for scoped creds: {error_description}", status_code=response.status_code or 403, error_code=error_code_from_resp or 'permission_denied', error_details=error_details)
                error_msg_with_details_sts = f"Failed to get scoped creds: {error_description}"
                if error_details:
                    try:
                        details_str_sts = json.dumps(error_details)
                        if len(details_str_sts) > 200: details_str_sts = details_str_sts[:200] + "..."
                        error_msg_with_details_sts += f" (GCF Details: {details_str_sts})"
                    except TypeError:
                        error_msg_with_details_sts += f" (GCF Details: {str(error_details)[:200]})"
                raise PiperError(error_msg_with_details_sts)
            scoped_data = response.json()
            if 'access_token' not in scoped_data or 'granted_credential_ids' not in scoped_data:
                raise PiperError("Invalid response from get_scoped_credentials (missing access_token or granted_credential_ids).")
            requested_set = set(cleaned_credential_ids); granted_set = set(scoped_data.get('granted_credential_ids', []))
            if not granted_set: 
                 logger.error(f"Piper returned no granted_credential_ids for instance {instance_id_for_context} (requested: {cleaned_credential_ids}). This implies no grant for any requested ID.")
                 raise PiperForbiddenError(f"Permission effectively denied for all requested credential_ids: {cleaned_credential_ids}. Check grants.", status_code=response.status_code or 403, error_code='permission_denied_for_all_ids', error_details=scoped_data) 
            if requested_set != granted_set: logger.warning(f"Partial success getting credentials for instance {instance_id_for_context}: Granted for {list(granted_set)}, but not for {list(requested_set - granted_set)}.")
            logger.info(f"Piper successfully returned STS token for instance {instance_id_for_context}, granted IDs: {scoped_data.get('granted_credential_ids')}")
            return scoped_data
        except (PiperAuthError, PiperForbiddenError, ValueError): raise
        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if e.response is not None else None
            logger.error(f"Network error calling {self.get_scoped_url}. Status: {status_code}", exc_info=True)
            raise PiperError(f"Network error getting scoped creds: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error getting scoped creds: {e}", exc_info=True)
            raise PiperError(f"Unexpected error getting scoped creds: {e}") from e

    def _perform_get_secret(self, variable_name: str, piper_link_instance_id_for_call: Optional[str] = None, fetch_raw_secret: bool = False) -> Dict[str, Any]:
        original_variable_name_for_error_reporting = variable_name 
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
                    return {"value": sts_token_value, "source": "piper_sts", "token_type": "Bearer", "expires_in": piper_sts_response_data.get("expires_in"), "piper_credential_id": granted_piper_cred_id, "piper_instance_id": effective_instance_id, "variable_name": original_variable_name_for_error_reporting}
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
                        error_message_raw_missing = "Raw secret value key 'secret_value' missing or null in exchange GCF response."
                        if raw_secret_data:
                            try:
                                details_str_raw = json.dumps(raw_secret_data)
                                if len(details_str_raw) > 150: details_str_raw = details_str_raw[:150] + "..."
                                error_message_raw_missing += f" (Response: {details_str_raw})"
                            except TypeError:
                                 error_message_raw_missing += f" (Response: {str(raw_secret_data)[:150]})"
                        raise PiperError(error_message_raw_missing)
                    logger.info(f"GET_SECRET '{original_variable_name_for_error_reporting}': Successfully retrieved raw secret from Piper.")
                    return {"value": raw_secret_value, "source": "piper_raw_secret", "piper_credential_id": granted_piper_cred_id, "piper_instance_id": effective_instance_id, "variable_name": original_variable_name_for_error_reporting}
            except (PiperLinkNeededError, PiperGrantNeededError, PiperForbiddenError, PiperAuthError, PiperRawSecretExchangeError, PiperConfigError, PiperError) as e:
                piper_tier_error = e; logger.warning(f"GET_SECRET '{original_variable_name_for_error_reporting}': Piper tier failed: {type(e).__name__} - {str(e).splitlines()[0]}")
            except Exception as e:
                error_message = f"Unexpected error during Piper tier operation for '{original_variable_name_for_error_reporting}': {type(e).__name__} - {str(e)}"
                piper_tier_error = PiperError(error_message)
                logger.error(f"GET_SECRET '{original_variable_name_for_error_reporting}': Unexpected error in Piper tier: {error_message}", exc_info=True) 
            if piper_tier_error: attempted_sources_summary["Piper"] = piper_tier_error
        if self.fallback_to_env and (not self.use_piper or attempted_sources_summary.get("Piper") is not None):
            logger.info(f"GET_SECRET '{original_variable_name_for_error_reporting}': Attempting Environment Variable tier.")
            env_var_to_check: Optional[str] = None
            if self.env_variable_map and original_variable_name_for_error_reporting in self.env_variable_map: env_var_to_check = self.env_variable_map[original_variable_name_for_error_reporting]
            else: 
                normalized_for_env = original_variable_name_for_error_reporting.upper(); normalized_for_env = re.sub(r'[^A-Z0-9_]', '_', normalized_for_env); normalized_for_env = re.sub(r'_+', '_', normalized_for_env); env_var_to_check = f"{self.env_variable_prefix}{normalized_for_env}"
            secret_value_from_env = os.environ.get(env_var_to_check)
            if secret_value_from_env is not None:
                logger.info(f"GET_SECRET '{original_variable_name_for_error_reporting}': Successfully retrieved from env var '{env_var_to_check}'.")
                return {"value": secret_value_from_env, "source": "environment_variable", "env_var_name_used": env_var_to_check, "token_type": "DirectValue", "expires_in": None, "variable_name": original_variable_name_for_error_reporting}
            else: 
                failure_msg = f"Environment variable '{env_var_to_check}' not set."; attempted_sources_summary["EnvironmentVariable"] = failure_msg; logger.info(f"GET_SECRET '{original_variable_name_for_error_reporting}': Env tier failed: {failure_msg}")
        if self.fallback_to_local_config and self.local_config_file_path and \
           (not self.use_piper or attempted_sources_summary.get("Piper") is not None) and \
           (not self.fallback_to_env or attempted_sources_summary.get("EnvironmentVariable") is not None):
            logger.info(f"GET_SECRET '{original_variable_name_for_error_reporting}': Attempting Local Config File tier (Path: '{self.local_config_file_path}').")
            local_config_tier_error: Optional[Any] = None; source_key_local_config = f"LocalConfigFile ({self.local_config_file_path})"
            try:
                if not os.path.exists(self.local_config_file_path): raise FileNotFoundError(f"File not found: {self.local_config_file_path}")
                if not os.access(self.local_config_file_path, os.R_OK): raise PermissionError(f"Read permission denied for file: {self.local_config_file_path}")
                with open(self.local_config_file_path, 'r') as f: config_data = json.load(f)
                if original_variable_name_for_error_reporting in config_data:
                    secret_value_from_config = config_data[original_variable_name_for_error_reporting]
                    logger.info(f"GET_SECRET '{original_variable_name_for_error_reporting}': Successfully retrieved from local config file.")
                    return {"value": secret_value_from_config, "source": "local_config_file", "config_file_path": self.local_config_file_path, "token_type": "DirectValue", "expires_in": None, "variable_name": original_variable_name_for_error_reporting}
                else: 
                    local_config_tier_error = f"Variable '{original_variable_name_for_error_reporting}' not found in the config file."
            except FileNotFoundError as e_fnf: local_config_tier_error = e_fnf
            except PermissionError as e_perm: local_config_tier_error = e_perm
            except json.JSONDecodeError as e_json: local_config_tier_error = PiperError(f"Error decoding JSON from local config file '{self.local_config_file_path}': {e_json}")
            except Exception as e_local_cfg: local_config_tier_error = PiperError(f"Unexpected error reading local config file '{self.local_config_file_path}': {e_local_cfg}")
            if local_config_tier_error: 
                attempted_sources_summary[source_key_local_config] = local_config_tier_error
                logger.warning(f"GET_SECRET '{original_variable_name_for_error_reporting}': Local Config tier failed: {str(local_config_tier_error).splitlines()[0]}")
        if not attempted_sources_summary: 
            logger.error(f"GET_SECRET '{original_variable_name_for_error_reporting}': No acquisition tiers were successfully run or configured to attempt."); 
            attempted_sources_summary["SDKInternal"] = "No acquisition methods were enabled or attempted due to client configuration."
        final_error_message = f"Failed to acquire secret for '{original_variable_name_for_error_reporting}'."
        logger.error(f"GET_SECRET '{original_variable_name_for_error_reporting}': All configured tiers failed. Raising PiperSecretAcquisitionError. Summary: {attempted_sources_summary}")
        raise PiperSecretAcquisitionError(message=final_error_message, variable_name=original_variable_name_for_error_reporting, attempted_sources_summary=attempted_sources_summary)

    def get_secret(self, variable_name: str, piper_link_instance_id_for_call: Optional[str] = None, fetch_raw_secret: bool = False, raise_on_failure: bool = True) -> Optional[Dict[str, Any]]:
        _error_key_for_this_call: Optional[str] = None 
        if not isinstance(variable_name, str):
            err = PiperConfigError("variable_name must be a string, not None or other type.")
            _error_key_for_this_call = "INPUT_VALIDATION_NON_STRING_VAR_NAME" # Fixed key
            self._last_get_secret_errors[_error_key_for_this_call] = err
            if raise_on_failure: raise err
            return {"value": None, "source": "config_error_input_type", "variable_name": _error_key_for_this_call, "error_object": err }

        original_variable_name_stripped = variable_name.strip()
        if not original_variable_name_stripped: # Handles "" and "   "
            err = PiperConfigError("variable_name cannot be empty or all whitespace after stripping.")
            _error_key_for_this_call = original_variable_name_stripped # Key will be ""
            self._last_get_secret_errors[_error_key_for_this_call] = err 
            if raise_on_failure: raise err
            return {"value": None, "source": "config_error_input_empty", "variable_name": _error_key_for_this_call, "error_object": err}
        
        error_key_for_storage = original_variable_name_stripped

        if not self.client_initialization_ok:
            init_fail_error = self._initialization_error or PiperConfigError("PiperClient is not properly initialized. Check logs.")
            self._last_get_secret_errors[error_key_for_storage] = init_fail_error
            if raise_on_failure:
                logger.error(f"GET_SECRET '{error_key_for_storage}': Aborted due to client initialization failure. Raising error.")
                raise init_fail_error
            else:
                logger.warning(f"GET_SECRET '{error_key_for_storage}': Aborted due to client initialization failure. Storing error and returning failure dict.")
                return {"value": None, "source": "client_initialization_failure", "variable_name": error_key_for_storage, "error_object": init_fail_error}
        try:
            secret_info = self._perform_get_secret(error_key_for_storage, piper_link_instance_id_for_call, fetch_raw_secret)
            if error_key_for_storage in self._last_get_secret_errors:
                del self._last_get_secret_errors[error_key_for_storage]
            return secret_info
        except PiperError as e: 
            self._last_get_secret_errors[error_key_for_storage] = e
            if raise_on_failure: raise 
            else:
                logger.warning(f"GET_SECRET '{error_key_for_storage}': Acquisition failed. Storing error and returning failure dict as raise_on_failure=False. Error: {type(e).__name__} - {str(e).splitlines()[0]}")
                failure_source = "acquisition_failure" 
                # Updated logic to correctly identify specific failure source from PSAE
                if isinstance(e, PiperSecretAcquisitionError):
                    piper_tier_issue = e.attempted_sources_summary.get("Piper")
                    if isinstance(piper_tier_issue, PiperGrantNeededError): failure_source = "piper_grant_needed"
                    elif isinstance(piper_tier_issue, PiperLinkNeededError): failure_source = "piper_link_needed"
                    # Potentially add more checks here for other Piper tier specific errors if needed for 'source'
                elif isinstance(e, PiperGrantNeededError): failure_source = "piper_grant_needed"
                elif isinstance(e, PiperLinkNeededError): failure_source = "piper_link_needed"
                elif isinstance(e, PiperConfigError): failure_source = "config_error_runtime" 
                return {"value": None, "source": failure_source, "variable_name": error_key_for_storage, "error_object": e}
        except Exception as e_unhandled: 
            wrapped_error = PiperError(f"Unexpected unhandled error during get_secret for '{error_key_for_storage}': {e_unhandled}")
            logger.error(f"GET_SECRET '{error_key_for_storage}': Unexpected unhandled error. Wrapping and processing. Original: {type(e_unhandled).__name__} - {e_unhandled}", exc_info=True)
            self._last_get_secret_errors[error_key_for_storage] = wrapped_error
            if raise_on_failure: raise wrapped_error
            else: return {"value": None, "source": "unexpected_sdk_error", "variable_name": error_key_for_storage, "error_object": wrapped_error}

    def get_last_error_for_variable(self, variable_name: str) -> Optional[PiperError]:
        if not isinstance(variable_name, str):
            logger.warning("get_last_error_for_variable called with non-string variable_name. Returning None.")
            return None
        # Handle special keys used by get_secret's initial validation more directly
        if variable_name == "INPUT_VALIDATION_NON_STRING_VAR_NAME": 
            return self._last_get_secret_errors.get("INPUT_VALIDATION_NON_STRING_VAR_NAME")
        stripped_variable_name = variable_name.strip() 
        return self._last_get_secret_errors.get(stripped_variable_name)

    def get_resolution_advice(self, variable_name: str, error_object: Optional[PiperError] = None) -> Optional[str]:
        advice_parts = []
        error_to_diagnose: Optional[PiperError] = None
        actionable_advice_generated = False 

        if isinstance(variable_name, str) and variable_name.strip():
            display_variable_name = variable_name.strip()
        # Check if the var_name is one of the special keys from input validation
        elif variable_name == "INPUT_VALIDATION_NON_STRING_VAR_NAME":
            display_variable_name = "the provided variable name (invalid type)"
        elif isinstance(variable_name, str) and not variable_name.strip() and variable_name != "": # All whitespace
            display_variable_name = "the provided variable name (all whitespace)"
        elif variable_name == "": # Explicitly empty string
             display_variable_name = "the provided variable name (empty string)"
        elif error_object and hasattr(error_object, 'variable_name') and getattr(error_object, 'variable_name'):
            display_variable_name = getattr(error_object, 'variable_name')
        else:
            display_variable_name = "the requested secret"

        if error_object is not None:
            if isinstance(error_object, PiperError):
                error_to_diagnose = error_object
                if hasattr(error_object, 'variable_name') and getattr(error_object, 'variable_name'):
                    display_variable_name = getattr(error_object, 'variable_name')
            else:
                logger.warning(f"get_resolution_advice called with non-PiperError error_object type: {type(error_object)}. Ignoring it.")
        
        if error_to_diagnose is None and isinstance(variable_name, str) : 
            error_to_diagnose = self.get_last_error_for_variable(variable_name) 
            # display_variable_name already set based on input variable_name logic above
            
        if error_to_diagnose is None and self._initialization_error:
            error_to_diagnose = self._initialization_error
            display_variable_name = "Piper SDK client configuration" 

        if error_to_diagnose is None:
            logger.debug(f"get_resolution_advice: No relevant error found for '{variable_name}'. No advice to generate.")
            return None

        if error_to_diagnose == self._initialization_error:
            advice_parts.append(f"Piper SDK Client Initial Setup Problem:")
        elif isinstance(error_to_diagnose, PiperConfigError) and (display_variable_name == "Piper SDK client configuration" or "input variable name" in display_variable_name):
            advice_parts.append(f"There's a problem with the input or client configuration:")
        else:
            advice_parts.append(f"I need help with the configuration for: '{display_variable_name}'.")

        if error_to_diagnose == self._initialization_error and isinstance(error_to_diagnose, PiperConfigError):
            advice_parts.append(f"  - Detail: {str(error_to_diagnose)}")
            actionable_advice_generated = True 
        elif isinstance(error_to_diagnose, PiperSecretAcquisitionError):
            summary = error_to_diagnose.attempted_sources_summary
            piper_tier_failure = summary.get("Piper")
            if isinstance(piper_tier_failure, PiperGrantNeededError):
                advice_parts.append(f"  - ACTION REQUIRED (Piper System): This application needs your permission for '{piper_tier_failure.variable_name_requested}'.")
                if piper_tier_failure.constructed_grant_url:
                    advice_parts.append(f"    Please visit this URL to grant access: {piper_tier_failure.constructed_grant_url}")
                else:
                    advice_parts.append(f"    Please use the Piper application or interface to grant access for client ID '{piper_tier_failure.agent_id_for_grant}' to variable '{piper_tier_failure.variable_name_requested}'.")
                actionable_advice_generated = True
            elif isinstance(piper_tier_failure, PiperLinkNeededError):
                advice_parts.append(f"  - ACTION REQUIRED (Piper System): The Piper Link application needs to be connected.")
                advice_parts.append(f"    Please ensure Piper Link is running on your computer and you are logged in.")
                if self.attempt_local_discovery and self.piper_link_service_url:
                     advice_parts.append(f"    (The SDK tried to find it at: {self.piper_link_service_url})")
                actionable_advice_generated = True
            elif isinstance(piper_tier_failure, PiperError): 
                advice_parts.append(f"  - Piper System Issue: {str(piper_tier_failure).splitlines()[0]}")
                if hasattr(piper_tier_failure, 'error_details') and getattr(piper_tier_failure, 'error_details'):
                    details_preview = str(getattr(piper_tier_failure, 'error_details')); 
                    if len(details_preview) > 100: details_preview = details_preview[:97] + "..."
                    advice_parts.append(f"    Details: {details_preview}")
            env_fail_msg = summary.get("EnvironmentVariable")
            if env_fail_msg: 
                advice_parts.append(f"  - Environment Variable Check: {env_fail_msg}")
                if "not set" in env_fail_msg: actionable_advice_generated = True 
            local_config_key_prefix = "LocalConfigFile ("; local_config_fail_key = next((k for k in summary if k.startswith(local_config_key_prefix)), None)
            if local_config_fail_key:
                local_fail_info = summary[local_config_fail_key]; path_in_key = local_config_fail_key[len(local_config_key_prefix):-1] 
                target_var_for_local_msg = error_to_diagnose.variable_name if hasattr(error_to_diagnose, 'variable_name') else display_variable_name
                msg_added_for_local = False
                if isinstance(local_fail_info, FileNotFoundError): advice_parts.append(f"  - Local Config File Check ({path_in_key}): File was not found."); msg_added_for_local=True
                elif isinstance(local_fail_info, PermissionError): advice_parts.append(f"  - Local Config File Check ({path_in_key}): Could not read the file due to permissions."); msg_added_for_local=True
                elif isinstance(local_fail_info, PiperError) and "Error decoding JSON" in str(local_fail_info): advice_parts.append(f"  - Local Config File Check ({path_in_key}): The file is not valid JSON."); msg_added_for_local=True
                elif isinstance(local_fail_info, str) and f"Variable '{target_var_for_local_msg}' not found" in local_fail_info: advice_parts.append(f"  - Local Config File Check ({path_in_key}): The variable '{target_var_for_local_msg}' was not found in this file."); msg_added_for_local=True
                else: advice_parts.append(f"  - Local Config File Check ({path_in_key}): Failed - {str(local_fail_info).splitlines()[0]}")
                if msg_added_for_local: actionable_advice_generated = True
            if not piper_tier_failure and not env_fail_msg and not local_config_fail_key and summary.get("SDKInternal"):
                advice_parts.append(f"  - SDK Configuration: {summary.get('SDKInternal')}")
        elif isinstance(error_to_diagnose, PiperLinkNeededError): 
            advice_parts.append(f"  - ACTION REQUIRED (Piper System): The Piper Link application needs to be connected.")
            advice_parts.append(f"    Please ensure Piper Link is running on your computer and you are logged in.")
            if self.attempt_local_discovery and self.piper_link_service_url: advice_parts.append(f"    (The SDK tried to find it at: {self.piper_link_service_url})")
            actionable_advice_generated = True
        elif isinstance(error_to_diagnose, PiperGrantNeededError): 
            advice_parts.append(f"  - ACTION REQUIRED (Piper System): This application needs your permission for '{error_to_diagnose.variable_name_requested}'.")
            if error_to_diagnose.constructed_grant_url: advice_parts.append(f"    Please visit this URL to grant access: {error_to_diagnose.constructed_grant_url}")
            else: advice_parts.append(f"    Please use the Piper application or interface to grant access for client ID '{error_to_diagnose.agent_id_for_grant}' to variable '{error_to_diagnose.variable_name_requested}'.")
            actionable_advice_generated = True
        elif isinstance(error_to_diagnose, PiperConfigError): 
            advice_parts.append(f"  - Configuration Issue: {str(error_to_diagnose)}")
            actionable_advice_generated = True 
        elif isinstance(error_to_diagnose, PiperAuthError): 
            advice_parts.append(f"  - Authentication/Authorization Issue with Piper System: {str(error_to_diagnose).splitlines()[0]}")
            if hasattr(error_to_diagnose, 'error_details') and getattr(error_to_diagnose, 'error_details'):
                details_preview = str(getattr(error_to_diagnose, 'error_details')); 
                if len(details_preview) > 100: details_preview = details_preview[:97] + "..."
                advice_parts.append(f"    Details: {details_preview}")
        elif isinstance(error_to_diagnose, PiperError): 
            advice_parts.append(f"  - Piper SDK System Issue: {str(error_to_diagnose)}")
        else: advice_parts.append(f"  - An unexpected issue occurred: {str(error_to_diagnose)}")

        if actionable_advice_generated:
            advice_parts.append("Once this is resolved, please try your request again.")
        elif len(advice_parts) > 1: 
            advice_parts.append("  Please check the application logs for more technical details about the error.")
        # If only one part (the intro), and no error_to_diagnose was found, method returns None earlier.
        # If error_to_diagnose was found but resulted in only the intro line (highly unlikely), this logic is okay.
            
        return "\n".join(advice_parts)

    def get_credential_id_for_variable(self, variable_name: str, piper_link_instance_id_for_call: Optional[str] = None) -> str:
        logger.warning("get_credential_id_for_variable is an advanced method; prefer get_secret().")
        if not self.client_initialization_ok: raise self._initialization_error or PiperConfigError("PiperClient is not properly initialized.")
        if not self.use_piper: raise PiperConfigError("Cannot get credential_id: Piper usage is disabled in client configuration.")
        target_instance_id = self._get_instance_id_for_api_call(piper_link_instance_id_for_call)
        if not target_instance_id: raise PiperLinkNeededError("Instance ID required for resolving variable (neither provided nor discovered via Piper Link when enabled).")
        if not variable_name or not isinstance(variable_name, str): raise PiperConfigError("variable_name must be a non-empty string for get_credential_id_for_variable.")
        original_variable_name_stripped = variable_name.strip()
        if not original_variable_name_stripped: raise PiperConfigError("variable_name cannot be empty after stripping for get_credential_id_for_variable.")
        return self._resolve_piper_variable(original_variable_name_stripped, target_instance_id)

    def get_scoped_credentials_by_id(self, credential_ids: List[str], piper_link_instance_id_for_call: Optional[str] = None) -> Dict[str, Any]:
        logger.warning("get_scoped_credentials_by_id is an advanced method; prefer get_secret().")
        if not self.client_initialization_ok: raise self._initialization_error or PiperConfigError("PiperClient is not properly initialized.")
        if not self.use_piper: raise PiperConfigError("Cannot get scoped credentials by ID: Piper usage is disabled in client configuration.")
        target_instance_id = self._get_instance_id_for_api_call(piper_link_instance_id_for_call)
        if not target_instance_id: raise PiperLinkNeededError("Instance ID required for fetching scoped credentials (neither provided nor discovered via Piper Link when enabled).")
        if not credential_ids or not isinstance(credential_ids, list) or not all(isinstance(cid, str) and cid.strip() for cid in credential_ids):
            raise PiperConfigError("credential_ids must be a non-empty list of non-empty strings for get_scoped_credentials_by_id.")
        return self._fetch_piper_sts_token(credential_ids, target_instance_id)