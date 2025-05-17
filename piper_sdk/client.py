# piper_sdk/client.py

import os
import re 
import requests
import time
from urllib.parse import urlencode, quote_plus as _quote_plus # Import quote_plus for URL encoding params
import logging
from typing import List, Dict, Any, Optional, Tuple
import uuid 

# Logging setup
logger = logging.getLogger(__name__) 
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - PiperSDK - %(levelname)s - %(message)s')

# --- Error classes ---
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
                 piper_ui_grant_url_template: Optional[str] = None): # Template or base URL
        super().__init__(message, status_code, error_code, error_details)
        self.agent_id_for_grant = agent_id_for_grant
        self.variable_name_requested = variable_name_requested
        self.piper_ui_grant_url_template = piper_ui_grant_url_template # e.g. "https://agentpiper.com/secrets"
        self.constructed_grant_url = None

        if self.piper_ui_grant_url_template and self.agent_id_for_grant and self.variable_name_requested:
            try:
                # Construct URL: https://agentpiper.com/secrets?scope=manage_grants&client=<AGENT_ID>&variable=<VAR_NAME>
                base_url = self.piper_ui_grant_url_template.rstrip('/')
                params = {
                    'scope': 'manage_grants',
                    'client': self.agent_id_for_grant,
                    'variable': self.variable_name_requested # Your /secrets page can use this to guide the user
                }
                self.constructed_grant_url = f"{base_url}?{urlencode(params, quote_via=_quote_plus)}"
            except Exception as e_url:
                logger.warning(f"PiperSDK: Could not construct Piper UI grant URL: {e_url}")

    def __str__(self):
        base_str = super().__str__()
        if self.constructed_grant_url:
            return f"{base_str}\nTo resolve this, you may need to create or activate a grant in Piper. Try visiting: {self.constructed_grant_url}"
        elif self.variable_name_requested:
            return f"{base_str} (for variable: '{self.variable_name_requested}')"
        return base_str


class PiperGrantNeededError(PiperGrantError): # This now inherits from the enhanced PiperGrantError
    """Raised when a specific grant is required but not found or inactive for a variable."""
    def __init__(self, 
                 message: str, # Specific message from backend
                 status_code: Optional[int] = None, 
                 error_code: Optional[str] = 'grant_needed', # Default error code
                 error_details: Optional[Any] = None,
                 agent_id_for_grant: Optional[str] = None,
                 variable_name_requested: Optional[str] = None,
                 piper_ui_grant_url_template: Optional[str] = None
                ):
        # Pass all params up to PiperGrantError which will construct the URL
        super().__init__(message, status_code, error_code, error_details, 
                         agent_id_for_grant, variable_name_requested, piper_ui_grant_url_template)


class PiperForbiddenError(PiperAuthError):
    """Raised when an operation is forbidden, often due to insufficient permissions or invalid scope."""
    def __init__(self, message: str, status_code: Optional[int] = 403, 
                 error_code: Optional[str] = 'permission_denied', 
                 error_details: Optional[Any] = None):
        super().__init__(message, status_code, error_code, error_details)

class PiperRawSecretExchangeError(PiperError):
    """Raised when fetching the raw secret via the exchange GCF fails after obtaining an STS token."""
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


class PiperClient:
    DEFAULT_TOKEN_EXPIRY_BUFFER_SECONDS: int = 60
    DEFAULT_PROJECT_ID: str = "444535882337" 
    DEFAULT_REGION: str = "us-central1"     

    DEFAULT_PIPER_TOKEN_URL = f"https://piper-token-endpoint-{DEFAULT_PROJECT_ID}.{DEFAULT_REGION}.run.app"
    DEFAULT_PIPER_GET_SCOPED_URL = f"https://getscopedgcpcredentials-{DEFAULT_PROJECT_ID}.{DEFAULT_REGION}.run.app"
    DEFAULT_PIPER_RESOLVE_MAPPING_URL = f"https://piper-resolve-variable-mapping-{DEFAULT_PROJECT_ID}.{DEFAULT_REGION}.run.app"
    DEFAULT_PIPER_LINK_SERVICE_URL = "http://localhost:31477/piper-link-context"
    DEFAULT_PIPER_UI_BASE_URL = "https://agentpiper.com/secrets" # Default for grant links

    def __init__(self,
                 client_id: str,
                 client_secret: str,
                 _piper_system_project_id: Optional[str] = None, 
                 _piper_system_region: Optional[str] = None,     
                 token_url: Optional[str] = None,
                 get_scoped_url: Optional[str] = None,
                 resolve_mapping_url: Optional[str] = None,
                 piper_link_service_url: Optional[str] = None,
                 requests_session: Optional[requests.Session] = None,
                 auto_discover_instance_id: bool = True, 
                 enable_env_fallback: bool = True,
                 env_variable_prefix: str = "",
                 env_variable_map: Optional[Dict[str, str]] = None,
                 piper_link_instance_id: Optional[str] = None,
                 exchange_secret_url: Optional[str] = None,
                 # --- NEW PARAMETER ---
                 piper_ui_grant_page_url: Optional[str] = None # e.g., "https://agentpiper.com/secrets"
                ):

        if not client_id or not client_secret:
            raise ValueError("client_id and client_secret are required.")
        self.client_id: str = client_id
        self._client_secret: str = client_secret
        
        effective_project_id = _piper_system_project_id or self.DEFAULT_PROJECT_ID
        effective_region = _piper_system_region or self.DEFAULT_REGION

        self.token_url: str = token_url or f"https://piper-token-endpoint-{effective_project_id}.{effective_region}.run.app"
        self.get_scoped_url: str = get_scoped_url or f"https://getscopedgcpcredentials-{effective_project_id}.{effective_region}.run.app"
        self.resolve_mapping_url: str = resolve_mapping_url or f"https://piper-resolve-variable-mapping-{effective_project_id}.{effective_region}.run.app"
        self.piper_link_service_url: str = piper_link_service_url or self.DEFAULT_PIPER_LINK_SERVICE_URL
        self.exchange_secret_url: Optional[str] = exchange_secret_url
        
        # --- ADDED: Store and validate piper_ui_grant_page_url ---
        self.piper_ui_grant_page_url: str = piper_ui_grant_page_url or self.DEFAULT_PIPER_UI_BASE_URL
        if self.piper_ui_grant_page_url and not self.piper_ui_grant_page_url.startswith('https://'):
            logger.warning(f"Piper UI Grant Page URL ('{self.piper_ui_grant_page_url}') does not look like a valid HTTPS URL. Grant links may be incorrect.")
        
        if self.exchange_secret_url and not self.exchange_secret_url.startswith('https://'):
            raise PiperConfigError(f"Piper Exchange Secret URL ('{self.exchange_secret_url}') must be a valid HTTPS URL if provided.")

        for url_attr_name, url_value_str in [
            ("Piper Token URL", self.token_url), ("Piper GetScoped URL", self.get_scoped_url),
            ("Piper Resolve Mapping URL", self.resolve_mapping_url)
        ]:
            if not url_value_str or not url_value_str.startswith('https://'):
                raise PiperConfigError(f"{url_attr_name} ('{url_value_str}') must be a valid HTTPS URL.")
        if not self.piper_link_service_url or not self.piper_link_service_url.startswith('http://localhost'):
             if self.piper_link_service_url != self.DEFAULT_PIPER_LINK_SERVICE_URL:
                logger.warning(f"Piper Link Service URL ('{self.piper_link_service_url}') is not the default localhost URL.")

        self._session = requests_session if requests_session else requests.Session()
        # --- MODIFIED SDK VERSION ---
        sdk_version = "0.4.2" 
        self._session.headers.update({'User-Agent': f'Pyper-SDK/{sdk_version}'})
        
        self._access_tokens: Dict[Tuple[str, Optional[str]], str] = {}
        self._token_expiries: Dict[Tuple[str, Optional[str]], float] = {}
        self._configured_instance_id: Optional[str] = piper_link_instance_id
        self._discovered_instance_id: Optional[str] = None
        self.enable_env_fallback = enable_env_fallback
        self.env_variable_prefix = env_variable_prefix
        self.env_variable_map = env_variable_map if env_variable_map is not None else {}

        log_msg_parts = [
            f"PiperClient initialized for agent client_id '{self.client_id[:8]}...'",
            f"Env fallback: {self.enable_env_fallback}"
        ]
        if self._configured_instance_id:
            log_msg_parts.append(f"Using provided instance_id: {self._configured_instance_id}")
        elif auto_discover_instance_id:
            log_msg_parts.append("Auto-discovery of instance_id is enabled.")
            self.discover_local_instance_id() 
        else:
            log_msg_parts.append("Auto-discovery of instance_id is disabled and no instance_id provided at init.")
        if self.exchange_secret_url:
            log_msg_parts.append(f"Raw secret exchange configured via: {self.exchange_secret_url}")
        if self.piper_ui_grant_page_url:
            log_msg_parts.append(f"Piper UI grant page base: {self.piper_ui_grant_page_url}")
        logger.info(". ".join(log_msg_parts) + ".")

    # discover_local_instance_id, _fetch_agent_token, _get_valid_agent_token, 
    # _get_instance_id_for_api_call, _normalize_variable_name
    # --- THESE METHODS REMAIN UNCHANGED FROM v0.4.0 DRAFT ---
    # ... (paste them here from the previous full SDK code block I gave you for v0.4.0) ...
    def discover_local_instance_id(self, force_refresh: bool = False) -> Optional[str]:
        if self._configured_instance_id: 
            logger.debug(f"Using instance_id provided at init ('{self._configured_instance_id}'), skipping local discovery.")
            return self._configured_instance_id 
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
                self._discovered_instance_id = instance_id
                return instance_id
            else:
                logger.warning(f"Local Piper Link service responded but instanceId was missing/invalid: {data}")
        except requests.exceptions.ConnectionError:
            logger.warning(f"Local Piper Link service not found/running at {self.piper_link_service_url}.")
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout connecting to local Piper Link service at {self.piper_link_service_url}.")
        except Exception as e: 
            logger.warning(f"Error querying local Piper Link service at {self.piper_link_service_url}: {e}")
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
            logger.warning(f"Requesting agent token without piper_link_instance_id for audience {audience}. Token 'sub' will default to agent owner ID.")
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
            expires_in = int(token_data.get('expires_in', 0))
            if not access_token:
                raise PiperAuthError("Token missing in response.", status_code=response.status_code, error_details=token_data)
            expiry_timestamp = request_start_time + expires_in
            logger.info(f"Successfully obtained agent token for audience {audience}, instance {instance_id or 'N/A'} (expires ~{time.ctime(expiry_timestamp)}).")
            return access_token, expiry_timestamp
        except requests.exceptions.RequestException as e:
            # ... (handle specific request errors) ...
            raise PiperAuthError(f"Request failed for agent token: {e}") from e
        except Exception as e:
            raise PiperAuthError(f"Unexpected error fetching agent token: {e}") from e

    def _get_valid_agent_token(self, audience: str, instance_id: Optional[str], force_refresh: bool = False) -> str:
        cache_key = (audience, instance_id)
        now = time.time()
        if not force_refresh and \
           cache_key in self._access_tokens and \
           self._token_expiries.get(cache_key, 0) > (now + self.DEFAULT_TOKEN_EXPIRY_BUFFER_SECONDS):
            logger.debug(f"Using cached token for audience: {audience}, instance: {instance_id or 'N/A'}")
            return self._access_tokens[cache_key]
        logger.info(f"Fetching new token for audience: {audience}, instance: {instance_id or 'N/A'}")
        access_token, expiry_timestamp = self._fetch_agent_token(audience=audience, instance_id=instance_id)
        self._access_tokens[cache_key] = access_token
        self._token_expiries[cache_key] = expiry_timestamp
        return access_token

    def _get_instance_id_for_api_call(self, piper_link_instance_id_for_call: Optional[str]) -> Optional[str]:
        if piper_link_instance_id_for_call:
            logger.debug(f"Using instance_id passed directly to API call method: {piper_link_instance_id_for_call}")
            return piper_link_instance_id_for_call
        if self._configured_instance_id:
            logger.debug(f"Using instance_id provided at PiperClient initialization: {self._configured_instance_id}")
            return self._configured_instance_id
        if self._discovered_instance_id:
            logger.debug(f"Using auto-discovered and cached instance_id: {self._discovered_instance_id}")
            return self._discovered_instance_id
        return self.discover_local_instance_id()

    def _normalize_variable_name(self, variable_name: str) -> str:
        if not variable_name: return "" 
        s1 = re.sub(r'[-\s]+', '_', variable_name) 
        s2 = re.sub(r'[^\w_]', '', s1)          
        s3 = re.sub(r'_+', '_', s2)             
        return s3.lower()


    def _resolve_piper_variable(self, variable_name: str, instance_id_for_context: str) -> str:
        if not variable_name or not isinstance(variable_name, str): raise ValueError("variable_name must be non-empty string.")
        trimmed_variable_name = variable_name.strip() # Use original for display/grant URL
        if not trimmed_variable_name: raise ValueError("variable_name cannot be empty after stripping.")
        
        normalized_name = self._normalize_variable_name(trimmed_variable_name)
        if not normalized_name: raise ValueError(f"Original variable name '{variable_name}' normalized to an empty/invalid string.")

        try:
            target_audience = self.resolve_mapping_url
            agent_token = self._get_valid_agent_token(audience=target_audience, instance_id=instance_id_for_context)
            headers = {'Authorization': f'Bearer {agent_token}', 'Content-Type': 'application/json'}
            payload = {'variableName': normalized_name} 
            logger.info(f"Calling (Piper) resolve_variable_mapping for original_var: '{trimmed_variable_name}', normalized_to: '{normalized_name}', instance: {instance_id_for_context}")
            response = self._session.post(self.resolve_mapping_url, headers=headers, json=payload, timeout=12)
            
            if 400 <= response.status_code < 600:
                error_details: Any = None; error_code_from_resp: str = f'http_{response.status_code}'; error_description: str = f"API Error {response.status_code}"
                try: 
                    error_details = response.json(); 
                    error_code_from_resp = error_details.get('error', error_code_from_resp); 
                    error_description = error_details.get('error_description', error_details.get('message', str(error_details)))
                except requests.exceptions.JSONDecodeError: 
                    error_details = response.text; error_description = error_details if error_details else error_description
                
                logger.error(f"API error resolving mapping for var '{normalized_name}' (original: '{trimmed_variable_name}'), instance {instance_id_for_context}. Status: {response.status_code}, Code: {error_code_from_resp}, Details: {error_details}")
                if response.status_code == 401 or error_code_from_resp == 'invalid_token': 
                    self._token_expiries[(target_audience, instance_id_for_context)] = 0 # Expire this specific token
                
                # --- MODIFIED: Raise enhanced PiperGrantNeededError ---
                if response.status_code == 404 and error_code_from_resp == 'mapping_not_found': 
                    raise PiperGrantNeededError( 
                        message=f"No active grant mapping found for variable '{normalized_name}' (original: '{trimmed_variable_name}') for this user context. Please create or activate the grant in Piper.", 
                        status_code=404, error_code='mapping_not_found', error_details=error_details,
                        agent_id_for_grant=self.client_id, 
                        variable_name_requested=trimmed_variable_name, # Pass original variable name
                        piper_ui_grant_url_template=self.piper_ui_grant_page_url 
                    )
                # --- END MODIFICATION ---
                raise PiperAuthError(f"Failed to resolve var mapping: {error_description}", status_code=response.status_code, error_code=error_code_from_resp, error_details=error_details)
            
            mapping_data = response.json(); credential_id = mapping_data.get('credentialId')
            if not credential_id or not isinstance(credential_id, str):
                raise PiperError("Invalid response from resolve_variable_mapping (missing or invalid credentialId).", error_details=mapping_data)
            logger.info(f"Piper resolved var '{normalized_name}' (original: '{trimmed_variable_name}') for instance '{instance_id_for_context}' to credentialId '{credential_id}'.")
            return credential_id
        except (PiperGrantNeededError, PiperAuthError, ValueError): raise 
        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if e.response is not None else None; error_details = None
            if e.response is not None:
                try: error_details = e.response.json()
                except requests.exceptions.JSONDecodeError: error_details = e.response.text
            logger.error(f"Network error calling {self.resolve_mapping_url} for instance {instance_id_for_context} (var: '{normalized_name}'). Status: {status_code}", exc_info=True)
            raise PiperError(f"Network error resolving variable: {e}", error_details=error_details) from e 
        except Exception as e:
            logger.error(f"Unexpected error resolving variable for instance {instance_id_for_context} (var: '{normalized_name}'): {e}", exc_info=True)
            raise PiperError(f"Unexpected error resolving variable: {e}") from e

    def _fetch_piper_sts_token(self, credential_ids: List[str], instance_id_for_context: str) -> Dict[str, Any]:
        # ... (This method remains largely unchanged from v0.4.0 but ensure it raises specific errors like PiperForbiddenError)
        if not credential_ids or not isinstance(credential_ids, list): raise ValueError("credential_ids must be a non-empty list.")
        cleaned_credential_ids = [str(cid).strip() for cid in credential_ids if str(cid).strip()]
        if not cleaned_credential_ids: raise ValueError("credential_ids list empty after cleaning.")
        try:
            target_audience = self.get_scoped_url
            agent_token = self._get_valid_agent_token(audience=target_audience, instance_id=instance_id_for_context)
            # ... (rest of the method as in v0.4.0, ensuring PiperForbiddenError is raised for 403/permission_denied)
            scoped_headers = {'Authorization': f'Bearer {agent_token}', 'Content-Type': 'application/json'}
            scoped_payload = {'credentialIds': cleaned_credential_ids}
            logger.info(f"Calling (Piper) get_scoped_credentials for IDs: {cleaned_credential_ids}, instance: {instance_id_for_context}")
            response = self._session.post(self.get_scoped_url, headers=scoped_headers, json=scoped_payload, timeout=15)
            if 400 <= response.status_code < 600:
                error_details: Any = None; error_code_from_resp: str = f'http_{response.status_code}'; error_description: str = f"API Error {response.status_code}"
                try: 
                    error_details = response.json(); 
                    error_code_from_resp = error_details.get('error', error_code_from_resp); 
                    error_description = error_details.get('error_description', error_details.get('message', str(error_details)))
                except requests.exceptions.JSONDecodeError: 
                    error_details = response.text; error_description = error_details if error_details else error_description
                logger.error(f"API error getting scoped credentials for instance {instance_id_for_context}. Status: {response.status_code}, Code: {error_code_from_resp}, Details: {error_details}")
                if response.status_code == 401 or error_code_from_resp == 'invalid_token': 
                    self._token_expiries[(target_audience, instance_id_for_context)] = 0
                    raise PiperAuthError(f"Agent auth failed for scoped creds: {error_description}", status_code=401, error_code=error_code_from_resp or 'invalid_token', error_details=error_details)
                if response.status_code == 403 or error_code_from_resp == 'permission_denied': 
                    raise PiperForbiddenError(f"Permission denied for scoped creds: {error_description}", status_code=403, error_code=error_code_from_resp or 'permission_denied', error_details=error_details)
                raise PiperAuthError(f"Failed to get scoped creds: {error_description}", status_code=response.status_code, error_code=error_code_from_resp, error_details=error_details)
            
            scoped_data = response.json()
            if 'access_token' not in scoped_data or 'granted_credential_ids' not in scoped_data:
                raise PiperError("Invalid response from get_scoped_credentials (missing access_token or granted_credential_ids).", error_details=scoped_data)
            
            requested_set = set(cleaned_credential_ids); granted_set = set(scoped_data.get('granted_credential_ids', []))
            if not granted_set: # If no IDs were granted at all
                 logger.error(f"Piper returned no granted_credential_ids for instance {instance_id_for_context} (requested: {cleaned_credential_ids}). This implies a permission issue for all requested IDs.")
                 # This situation should ideally be caught by a 403 from the GCF, but if GCF returns 200 with empty granted_ids:
                 raise PiperForbiddenError(f"Permission effectively denied for all requested credential_ids: {cleaned_credential_ids}", status_code=response.status_code, error_code='permission_denied_for_all_ids', error_details=scoped_data)

            if requested_set != granted_set: 
                logger.warning(f"Partial success getting credentials for instance {instance_id_for_context}: Granted for {list(granted_set)}, but not for {list(requested_set - granted_set)}.")
            
            logger.info(f"Piper successfully returned STS token for instance {instance_id_for_context}, granted IDs: {scoped_data.get('granted_credential_ids')}")
            return scoped_data

        except (PiperAuthError, PiperForbiddenError, ValueError): raise 
        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if e.response is not None else None; error_details = None
            if e.response is not None:
                try: error_details = e.response.json()
                except requests.exceptions.JSONDecodeError: error_details = e.response.text
            logger.error(f"Network error calling {self.get_scoped_url} for instance {instance_id_for_context}. Status: {status_code}", exc_info=True)
            raise PiperError(f"Network error getting scoped creds: {e}", error_details=error_details) from e
        except Exception as e:
            logger.error(f"Unexpected error getting scoped creds by ID for instance {instance_id_for_context}: {e}", exc_info=True)
            raise PiperError(f"Unexpected error getting scoped creds: {e}") from e


    def get_secret(self,
                   variable_name: str,
                   piper_link_instance_id_for_call: Optional[str] = None, 
                   enable_env_fallback_for_this_call: Optional[bool] = None,
                   fallback_env_var_name: Optional[str] = None,
                   fetch_raw_secret: bool = False 
                   ) -> Dict[str, Any]:
        
        if not variable_name or not isinstance(variable_name, str):
            raise ValueError("variable_name must be a non-empty string.")
        
        # Store original variable name for potential use in grant URL
        original_variable_name_for_grant_link = variable_name.strip()

        piper_error_encountered: Optional[Exception] = None
        initial_piper_response: Optional[Dict[str, Any]] = None 
        effective_instance_id: Optional[str] = None

        try:
            effective_instance_id = self._get_instance_id_for_api_call(piper_link_instance_id_for_call)
            if not effective_instance_id:
                missing_reason_parts = []
                if piper_link_instance_id_for_call: missing_reason_parts.append("provided to get_secret()")
                if self._configured_instance_id: missing_reason_parts.append("provided at PiperClient initialization")
                if not missing_reason_parts : missing_reason_parts.append("discovered via Piper Link service")
                raise PiperLinkNeededError(f"Piper Link instanceId is required but was not ({' or '.join(missing_reason_parts)}) or discovery failed.")

            logger.info(f"Attempting to retrieve secret for '{original_variable_name_for_grant_link}' via Piper (instance: {effective_instance_id}).")
            credential_id = self._resolve_piper_variable(original_variable_name_for_grant_link, effective_instance_id) # Pass original name
            piper_sts_response_data = self._fetch_piper_sts_token([credential_id], effective_instance_id)

            initial_piper_response = {
                "value": piper_sts_response_data.get("access_token"),
                "source": "piper_sts",
                "token_type": "Bearer", 
                "expires_in": piper_sts_response_data.get("expires_in"),
                "piper_credential_id": piper_sts_response_data.get('granted_credential_ids', [credential_id])[0],
                "piper_instance_id": effective_instance_id
            }
        
        except PiperLinkNeededError as e: piper_error_encountered = e; logger.info(f"Piper Link context needed for '{original_variable_name_for_grant_link}': {e}")
        except PiperGrantNeededError as e: # This will now be the enhanced error from _resolve_piper_variable
            piper_error_encountered = e; logger.info(f"Piper grant needed for '{original_variable_name_for_grant_link}': {e}") 
        except PiperForbiddenError as e: piper_error_encountered = e; logger.info(f"Piper access forbidden for '{original_variable_name_for_grant_link}': {e}") 
        except PiperAuthError as e: piper_error_encountered = e; logger.warning(f"Piper authentication/authorization error for '{original_variable_name_for_grant_link}': {e}")
        except PiperConfigError as e: piper_error_encountered = e; logger.warning(f"Piper SDK configuration error for '{original_variable_name_for_grant_link}': {e}")
        except PiperError as e: piper_error_encountered = e; logger.error(f"General Piper SDK error for '{original_variable_name_for_grant_link}': {e}", exc_info=True)
        except Exception as e: 
            piper_error_encountered = e; logger.error(f"Unexpected error during Piper credential fetch for '{original_variable_name_for_grant_link}': {e}", exc_info=True)

        if fetch_raw_secret and initial_piper_response and initial_piper_response.get('source') == 'piper_sts':
            logger.info(f"Raw secret requested for '{original_variable_name_for_grant_link}'. Attempting to exchange STS token.")
            if not self.exchange_secret_url:
                logger.error("SDK_CONFIG_ERROR: Cannot fetch raw secret. 'exchange_secret_url' is not configured in PiperClient.")
                raise PiperConfigError("Raw secret fetch requested, but 'exchange_secret_url' is not configured in PiperClient.")

            try:
                piper_credential_id_for_exchange = initial_piper_response.get('piper_credential_id')
                if not piper_credential_id_for_exchange: 
                     raise PiperError("Internal SDK error: piper_credential_id missing from successful STS response before exchange.")

                agent_jwt_for_exchange = self._get_valid_agent_token(
                    audience=self.exchange_secret_url, 
                    instance_id=effective_instance_id 
                )
                exchange_headers = {"Authorization": f"Bearer {agent_jwt_for_exchange}", "Content-Type": "application/json"}
                exchange_payload = {"piper_credential_id": piper_credential_id_for_exchange}
                
                logger.info(f"SDK: Calling exchange_secret_url ('{self.exchange_secret_url}') for raw secret. CredID: {piper_credential_id_for_exchange}, Instance: {effective_instance_id}")
                api_response = self._session.post(self.exchange_secret_url, headers=exchange_headers, json=exchange_payload, timeout=10)
                
                if 400 <= api_response.status_code < 600: 
                    err_details_exc: Any = None; err_code_exc: str = f'http_{api_response.status_code}'; err_desc_exc: str = f"Raw Secret Exchange GCF Error {api_response.status_code}"
                    try: 
                        err_details_exc = api_response.json(); err_code_exc = err_details_exc.get('error', err_code_exc); err_desc_exc = err_details_exc.get('error_description', err_details_exc.get('message', str(err_details_exc)))
                    except requests.exceptions.JSONDecodeError: 
                        err_details_exc = api_response.text; err_desc_exc = err_details_exc if err_details_exc else err_desc_exc
                    logger.error(f"SDK: Raw secret exchange failed. Status: {api_response.status_code}, Code: {err_code_exc}, Details: {err_details_exc}")
                    raise PiperRawSecretExchangeError(f"Failed to exchange for raw secret: {err_desc_exc}", status_code=api_response.status_code, error_code=err_code_exc, error_details=err_details_exc)
                
                raw_secret_data = api_response.json()
                raw_secret_value = raw_secret_data.get('secret_value')
                if raw_secret_value is None: 
                    raise PiperError("Raw secret value key 'secret_value' missing or null in exchange GCF response.", error_details=raw_secret_data)

                logger.info(f"SDK: Successfully fetched raw secret for CredID: {piper_credential_id_for_exchange}")
                return { 
                    "value": raw_secret_value, "source": "piper_raw_secret",
                    "piper_credential_id": piper_credential_id_for_exchange,
                    "piper_instance_id": effective_instance_id
                }
            except Exception as exchange_err: 
                logger.error(f"SDK: Error during raw secret exchange for '{original_variable_name_for_grant_link}': {exchange_err}", exc_info=True)
                if isinstance(exchange_err, PiperError): raise 
                raise PiperRawSecretExchangeError(f"Failed to process raw secret exchange for '{original_variable_name_for_grant_link}': {exchange_err}") from exchange_err
        
        if initial_piper_response and not fetch_raw_secret:
             logger.debug(f"Returning initially fetched Piper info (source: {initial_piper_response.get('source')}) as raw secret was not requested.")
             return initial_piper_response

        _is_fallback_enabled_for_call = self.enable_env_fallback
        if enable_env_fallback_for_this_call is not None:
            _is_fallback_enabled_for_call = enable_env_fallback_for_this_call

        if not _is_fallback_enabled_for_call: 
            if piper_error_encountered: raise piper_error_encountered
            else: raise PiperConfigError(f"Piper flow did not yield a result and fallback is disabled for '{original_variable_name_for_grant_link}'.")

        env_var_to_check = fallback_env_var_name
        if not env_var_to_check:
            if self.env_variable_map and original_variable_name_for_grant_link in self.env_variable_map: # Use original name for map
                env_var_to_check = self.env_variable_map[original_variable_name_for_grant_link]
            else:
                normalized_for_env = original_variable_name_for_grant_link.upper().replace(' ', '_').replace('-', '_')
                normalized_for_env = re.sub(r'[^\w_]', '', normalized_for_env)
                normalized_for_env = re.sub(r'_+', '_', normalized_for_env) 
                env_var_to_check = f"{self.env_variable_prefix}{normalized_for_env}"
        
        logger.info(f"Attempting fallback: Reading environment variable '{env_var_to_check}' for Piper variable '{original_variable_name_for_grant_link}'.")
        secret_value_from_env = os.environ.get(env_var_to_check)

        if secret_value_from_env:
            logger.info(f"Successfully retrieved secret from environment variable '{env_var_to_check}'.")
            return {
                "value": secret_value_from_env, "source": "environment_variable",
                "env_var_name_found": env_var_to_check, "token_type": "DirectValue", "expires_in": None
            }
        else: 
            logger.warning(f"Fallback failed: Environment variable '{env_var_to_check}' not set for Piper variable '{original_variable_name_for_grant_link}'.")
            if piper_error_encountered: 
                original_error_msg = str(piper_error_encountered)
                # Preserve the specific type and details of piper_error_encountered if it's a PiperGrantNeededError
                if isinstance(piper_error_encountered, PiperGrantNeededError):
                    piper_error_encountered.message = f"{piper_error_encountered.message.splitlines()[0]} Also, fallback environment variable '{env_var_to_check}' was not found."
                    # The constructed_grant_url will still be part of its __str__ if applicable
                    raise piper_error_encountered from None # Raise the modified original error
                
                appended_msg = f" Additionally, fallback environment variable '{env_var_to_check}' was not found."
                if hasattr(piper_error_encountered, 'status_code') and hasattr(piper_error_encountered, 'error_code'): 
                     raise type(piper_error_encountered)(f"{original_error_msg}{appended_msg}", 
                                                          status_code=getattr(piper_error_encountered,'status_code'), 
                                                          error_code=getattr(piper_error_encountered,'error_code'), 
                                                          error_details=getattr(piper_error_encountered,'error_details')) from piper_error_encountered
                else: 
                    raise type(piper_error_encountered)(f"{original_error_msg}{appended_msg}") from piper_error_encountered
            else: 
                raise PiperConfigError(f"Could not retrieve credentials for '{original_variable_name_for_grant_link}'. Piper context could not be established AND environment variable '{env_var_to_check}' is not set.")

    def get_credential_id_for_variable(self, variable_name: str, piper_link_instance_id_for_call: Optional[str] = None) -> str:
        logger.warning("get_credential_id_for_variable is an advanced method; prefer get_secret().")
        target_instance_id = self._get_instance_id_for_api_call(piper_link_instance_id_for_call) 
        if not target_instance_id:
            raise PiperLinkNeededError("Instance ID required for resolving variable (neither provided nor discovered).")
        return self._resolve_piper_variable(variable_name, target_instance_id) # Pass original variable name

    def get_scoped_credentials_by_id(self, credential_ids: List[str], piper_link_instance_id_for_call: Optional[str] = None) -> Dict[str, Any]:
        logger.warning("get_scoped_credentials_by_id is an advanced method; prefer get_secret().")
        target_instance_id = self._get_instance_id_for_api_call(piper_link_instance_id_for_call)
        if not target_instance_id:
            raise PiperLinkNeededError("Instance ID required for fetching scoped credentials (neither provided nor discovered).")
        return self._fetch_piper_sts_token(credential_ids, target_instance_id)