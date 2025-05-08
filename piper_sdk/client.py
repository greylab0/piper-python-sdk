# piper_sdk/client.py

import requests
import time
from urllib.parse import urlencode, urljoin
import logging
from typing import List, Dict, Any, Optional, Tuple
import uuid # Added for potential instanceId generation

# Configure logging for the SDK
logging.basicConfig(level=logging.INFO, format='%(asctime)s - PiperSDK - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PiperError(Exception):
    """Base exception for all Piper SDK errors."""
    pass

class PiperAuthError(PiperError):
    """Custom exception for Piper SDK authentication and API errors."""
    def __init__(self, message: str, status_code: Optional[int] = None, error_code: Optional[str] = None, error_details: Optional[Any] = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.error_details = error_details
    def __str__(self):
        details_str = f", Details: {self.error_details}" if self.error_details else ""
        status_str = f" (Status: {self.status_code})" if self.status_code is not None else ""
        code_str = f" (Code: {self.error_code})" if self.error_code else ""
        return f"{super().__str__()}{status_str}{code_str}{details_str}"

class PiperConfigError(PiperError):
    """Exception for configuration issues (e.g., missing instanceId context)."""
    pass

# Specific error for when the link needs establishing
class PiperLinkNeededError(PiperConfigError):
    """Exception raised when Piper Link instance ID is needed but cannot be found."""
    def __init__(self, message="Piper Link instanceId not provided and could not be discovered locally. Is the Piper Link app/service running and configured?"):
        super().__init__(message)


class PiperClient:
    """
    A Python client for interacting with the Piper API.

    Handles agent authentication (Client Credentials). Obtains user context by
    discovering a local 'Piper Link' service instance ID or accepting one explicitly.
    Resolves variable names and retrieves scoped GCP STS credentials.
    """
    DEFAULT_TOKEN_EXPIRY_BUFFER_SECONDS: int = 60
    DEFAULT_PROJECT_ID: str = "444535882337" # YOUR Piper GCP Project ID
    DEFAULT_REGION: str = "us-central1"     # YOUR Piper GCP Region

    # Endpoint URL Templates
    TOKEN_URL_TEMPLATE = "https://piper-token-endpoint-{project_id}.{region}.run.app"
    # Use the one that matches the function's actual trigger URL:
    GET_SCOPED_URL_TEMPLATE = "https://getscopedgcpcredentials-{project_id}.{region}.run.app"
    RESOLVE_MAPPING_URL_TEMPLATE = "https://piper-resolve-variable-mapping-{project_id}.{region}.run.app"

    # *** NEW: Default URL for local Piper Link service ***
    DEFAULT_PIPER_LINK_SERVICE_URL = "http://localhost:31477/piper-link-context" # Example

    # --- Internal State ---
    _discovered_instance_id: Optional[str] = None # Cache discovered ID in memory for this instance

    def __init__(self,
                 client_id: str,
                 client_secret: str,
                 project_id: Optional[str] = None,
                 region: Optional[str] = None,
                 token_url: Optional[str] = None,
                 get_scoped_url: Optional[str] = None,
                 resolve_mapping_url: Optional[str] = None,
                 piper_link_service_url: Optional[str] = None, # Allow overriding link service URL
                 requests_session: Optional[requests.Session] = None,
                 auto_discover_instance_id: bool = True): # Flag to control auto-discovery
        """
        Initializes the Piper Client for a functional agent (e.g., GmailMCP).

        Args:
            client_id: The functional agent's Client ID.
            client_secret: The functional agent's Client Secret value.
            project_id: GCP Project ID where Piper functions are deployed.
            region: GCP Region where Piper functions are deployed.
            token_url: (Optional) Override the default URL for the /token endpoint.
            get_scoped_url: (Optional) Override the default URL for the /get-scoped-credentials endpoint.
            resolve_mapping_url: (Optional) Override the default URL for the /resolve-variable-mapping endpoint.
            piper_link_service_url: (Optional) Override the default URL for the local Piper Link service.
            requests_session: (Optional) A requests.Session object.
            auto_discover_instance_id: (Optional) If True (default), attempts to discover the
                                       instanceId from the local Piper Link service during initialization
                                       and before API calls if needed.
        """
        if not client_id or not client_secret:
            raise ValueError("client_id and client_secret are required.")
        self.client_id: str = client_id
        self._client_secret: str = client_secret
        self.project_id: str = project_id or self.DEFAULT_PROJECT_ID
        self.region: str = region or self.DEFAULT_REGION

        # Construct endpoint URLs
        self.token_url: str = token_url or self.TOKEN_URL_TEMPLATE.format(project_id=self.project_id, region=self.region)
        self.get_scoped_url: str = get_scoped_url or self.GET_SCOPED_URL_TEMPLATE.format(project_id=self.project_id, region=self.region)
        self.resolve_mapping_url: str = resolve_mapping_url or self.RESOLVE_MAPPING_URL_TEMPLATE.format(project_id=self.project_id, region=self.region)
        self.piper_link_service_url: str = piper_link_service_url or self.DEFAULT_PIPER_LINK_SERVICE_URL

        self._session = requests_session if requests_session else requests.Session()
        # Read version from setup.py or use a fixed one initially
        sdk_version = "0.2.0" # Example version for this feature change
        self._session.headers.update({'User-Agent': f'Pyper-SDK/{sdk_version}'})

        # Internal state for caching agent tokens
        # Cache key is now (audience, instance_id) tuple
        self._access_tokens: Dict[Tuple[str, Optional[str]], str] = {}
        self._token_expiries: Dict[Tuple[str, Optional[str]], float] = {}

        logger.info(f"PiperClient initialized for agent client_id '{self.client_id[:8]}...'.")
        # Optionally attempt discovery on init
        if auto_discover_instance_id:
             self.discover_local_instance_id() # Attempt discovery, result cached internally

    # --- Instance ID Discovery ---
    def discover_local_instance_id(self, force_refresh: bool = False) -> Optional[str]:
        """
        Attempts to query the local Piper Link service for the active instanceId.
        Caches the result in memory for this client instance.

        Args:
            force_refresh: If True, ignore cached value and query again.

        Returns:
            The discovered instanceId string, or None if not found/error.
            The discovered ID is also cached internally for subsequent calls.
        """
        if self._discovered_instance_id and not force_refresh:
             logger.debug(f"Using cached instanceId: {self._discovered_instance_id}")
             return self._discovered_instance_id

        logger.info(f"Attempting to discover Piper Link instanceId from: {self.piper_link_service_url}")
        try:
            # Use the session for consistency, short timeout for local calls
            response = self._session.get(self.piper_link_service_url, timeout=1.0)
            response.raise_for_status() # Raises HTTPError for 4xx/5xx
            data = response.json()
            # Expecting {"instanceId": "...", "userId": "..."} potentially
            instance_id = data.get("instanceId")
            if instance_id and isinstance(instance_id, str):
                logger.info(f"Discovered and cached active Piper Link instanceId: {instance_id}")
                self._discovered_instance_id = instance_id
                return instance_id
            else:
                logger.warning(f"Local Piper Link service at {self.piper_link_service_url} responded but instanceId was missing or invalid in JSON: {data}")
                self._discovered_instance_id = None # Cache failure
                return None
        except requests.exceptions.ConnectionError:
            logger.warning(f"Local Piper Link service not found or not running at {self.piper_link_service_url}.")
            self._discovered_instance_id = None
            return None
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout connecting to local Piper Link service at {self.piper_link_service_url}.")
            self._discovered_instance_id = None
            return None
        except requests.exceptions.RequestException as e:
            # Includes JSONDecodeError, HTTPError etc.
            status_code = e.response.status_code if e.response is not None else None
            logger.warning(f"Error querying local Piper Link service at {self.piper_link_service_url} (Status: {status_code}): {e}")
            self._discovered_instance_id = None
            return None
        except Exception as e: # Catch any other unexpected errors
             logger.error(f"Unexpected error discovering local Piper Link instanceId: {e}", exc_info=True)
             self._discovered_instance_id = None
             return None

    # --- Internal Token Fetching (Modified) ---
    def _fetch_agent_token(self, audience: str, instance_id: Optional[str]) -> Tuple[str, float]:
        """
        Internal: Fetches token using client_credentials grant.
        Passes piper_link_instance_id if provided. Determines sub claim on backend.
        """
        instance_ctx_log = f"instance_id: {instance_id}" if instance_id else "no instance context (will default to agent owner)"
        logger.info(f"Requesting agent token via client_credentials for audience: {audience}, {instance_ctx_log}")
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        data_dict = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id, # This agent's ID
            'client_secret': self._client_secret, # This agent's secret
            'audience': audience
        }
        # *** ADD piper_link_instance_id if discovered/provided ***
        if instance_id:
            data_dict['piper_link_instance_id'] = instance_id
        else:
            # This case means the SDK couldn't discover the instance ID, and the caller
            # didn't provide one. The /token endpoint will default the 'sub' claim
            # to the agent's owner ID. This might be okay for some agents, but often
            # the agent needs to act as the end-user linked via the instanceId.
             logger.warning(f"Requesting agent token without piper_link_instance_id for audience {audience}. Token 'sub' claim will default to agent owner ID. This may lead to permission errors if user context is required.")

        data_encoded = urlencode(data_dict)
        request_start_time = time.time()

        try:
            response = self._session.post(self.token_url, headers=headers, data=data_encoded, timeout=15) # Slightly longer timeout?

            # Standardize error parsing (assuming backend consistently returns JSON)
            if 400 <= response.status_code < 600:
                error_details: Any = None; error_code: str = f'http_{response.status_code}'; error_description: str = f"API Error {response.status_code}"
                try:
                    error_details = response.json()
                    error_code = error_details.get('error', error_code)
                    error_description = error_details.get('error_description', error_details.get('message', str(error_details)))
                except requests.exceptions.JSONDecodeError:
                    error_details = response.text; error_description = error_details if error_details else error_description

                log_ctx = f"instance {instance_id}" if instance_id else "no instance"
                logger.error(f"Failed to obtain agent token for audience {audience}, {log_ctx}. Status: {response.status_code}, Code: {error_code}, Details: {error_details}")
                # Add specific error code handling if needed (e.g., invalid_client, invalid_request for bad instanceId)
                raise PiperAuthError(f"API error obtaining agent token: {error_description}", status_code=response.status_code, error_code=error_code, error_details=error_details)

            token_data = response.json()
            access_token = token_data.get('access_token')
            expires_in_raw = token_data.get('expires_in', 0)
            try: expires_in = int(expires_in_raw)
            except (ValueError, TypeError): expires_in = 0

            if not access_token:
                 raise PiperAuthError("Failed to obtain access token (token missing in response).", status_code=response.status_code, error_details=token_data)

            expiry_timestamp = request_start_time + expires_in
            log_ctx = f"instance {instance_id}" if instance_id else "no instance"
            logger.info(f"Successfully obtained agent token for audience {audience}, {log_ctx} (expires ~{time.ctime(expiry_timestamp)}).")
            return access_token, expiry_timestamp

        except requests.exceptions.RequestException as e:
            # ... (Network error handling as before, add context) ...
            status_code = e.response.status_code if e.response is not None else None; error_details = None
            if e.response is not None: try: error_details = e.response.json()
            except requests.exceptions.JSONDecodeError: error_details = e.response.text
            log_ctx = f"instance {instance_id}" if instance_id else "no instance"
            logger.error(f"Network/Request error getting agent token from {self.token_url} for {log_ctx}. Status: {status_code}", exc_info=True)
            raise PiperAuthError(f"Request failed for agent token: {e}", status_code=status_code, error_details=error_details) from e
        except Exception as e:
             # ... (Unexpected SDK error handling as before, add context) ...
             log_ctx = f"instance {instance_id}" if instance_id else "no instance"
             logger.error(f"Unexpected error during agent token fetch for {log_ctx}: {e}", exc_info=True)
             raise PiperAuthError(f"An unexpected error occurred fetching agent token: {e}") from e

    def _get_valid_agent_token(self, audience: str, instance_id: Optional[str], force_refresh: bool = False) -> str:
        """
        Internal: Gets token for specific audience and instanceId context.
        Cache key is (audience, instance_id).
        """
        # *** MODIFIED: Use instance_id for caching and fetching ***
        cache_key = (audience, instance_id)
        now = time.time()
        cached_token = self._access_tokens.get(cache_key)
        cached_expiry = self._token_expiries.get(cache_key, 0)

        if not force_refresh and cached_token and cached_expiry > (now + self.DEFAULT_TOKEN_EXPIRY_BUFFER_SECONDS):
            log_ctx = f"instance_id: {instance_id}" if instance_id else "no instance context"
            logger.debug(f"Using cached agent token for audience: {audience}, {log_ctx}")
            return cached_token
        else:
            if cached_token and not force_refresh:
                 log_ctx = f"instance_id: {instance_id}" if instance_id else "no instance context"
                 logger.info(f"Agent token for audience {audience}, {log_ctx} expired or nearing expiry, refreshing.")

            access_token, expiry_timestamp = self._fetch_agent_token(
                audience=audience,
                instance_id=instance_id # Pass instance_id to fetch
            ) # Raises PiperAuthError on failure

            self._access_tokens[cache_key] = access_token
            self._token_expiries[cache_key] = expiry_timestamp
            return access_token

    # --- Public Methods (Modified) ---

    def _get_instance_id_or_raise(self, instance_id_param: Optional[str]) -> str:
        """Internal helper to get instance ID, trying discovery if needed."""
        target_instance_id = instance_id_param or self._discovered_instance_id or self.discover_local_instance_id()
        if not target_instance_id:
            # If discovery failed or wasn't attempted and no ID was passed, raise specific error.
            raise PiperLinkNeededError() # Use the specific error type
        return target_instance_id

    def get_credential_id_for_variable(self, variable_name: str, instance_id: Optional[str] = None) -> str:
        """
        Resolves variable name using the context from the provided or discovered instanceId.

        Args:
            variable_name: The logical variable name defined by the agent.
            instance_id: (Optional) The Piper Link instanceId to use for context.
                         If None, attempts discovery via discover_local_instance_id().

        Returns:
            The Piper credential ID string.

        Raises:
            PiperLinkNeededError: If instanceId is needed but cannot be found/discovered.
            PiperAuthError: For API authentication/authorization errors.
            ValueError: For invalid input.
        """
        target_instance_id = self._get_instance_id_or_raise(instance_id) # Get ID or raise
        if not variable_name or not isinstance(variable_name, str): raise ValueError("variable_name must be non-empty string.")
        trimmed_variable_name = variable_name.strip()
        if not trimmed_variable_name: raise ValueError("variable_name cannot be empty.")

        try:
            target_audience = self.resolve_mapping_url
            agent_token = self._get_valid_agent_token(audience=target_audience, instance_id=target_instance_id)

            headers = {'Authorization': f'Bearer {agent_token}', 'Content-Type': 'application/json'}
            payload = {'variableName': trimmed_variable_name}

            logger.info(f"Calling resolve_variable_mapping for variable: '{trimmed_variable_name}', instance: {target_instance_id}")
            response = self._session.post(self.resolve_mapping_url, headers=headers, json=payload, timeout=12) # Slightly longer?

            # --- More specific error handling based on backend JSON ---
            if 400 <= response.status_code < 600:
                error_details: Any = None; error_code: str = f'http_{response.status_code}'; error_description: str = f"API Error {response.status_code}"
                try: error_details = response.json(); error_code = error_details.get('error', error_code); error_description = error_details.get('error_description', error_details.get('message', str(error_details)))
                except requests.exceptions.JSONDecodeError: error_details = response.text; error_description = error_details if error_details else error_description
                logger.error(f"API error resolving mapping for var '{trimmed_variable_name}', instance {target_instance_id}. Status: {response.status_code}, Code: {error_code}, Details: {error_details}")
                if response.status_code == 401 or error_code == 'invalid_token': self._token_expiries[(target_audience, target_instance_id)] = 0 # Expire token
                if response.status_code == 404 or error_code == 'mapping_not_found': raise PiperAuthError(f"No active grant mapping found for variable '{trimmed_variable_name}' for context of instance '{target_instance_id}'.", status_code=404, error_code='mapping_not_found', error_details=error_details)
                raise PiperAuthError(f"Failed to resolve variable mapping: {error_description}", status_code=response.status_code, error_code=error_code, error_details=error_details)
            # --- End specific error handling ---

            mapping_data = response.json()
            credential_id = mapping_data.get('credentialId')
            if not credential_id or not isinstance(credential_id, str):
                raise PiperAuthError("Received unexpected response format from variable mapping endpoint (missing credentialId).", status_code=response.status_code, error_details=mapping_data)

            logger.info(f"Successfully resolved variable '{trimmed_variable_name}' for instance '{target_instance_id}' to credentialId '{credential_id}'.")
            return credential_id

        # Catch specific exceptions first
        except (PiperAuthError, PiperLinkNeededError, ValueError): raise
        # Wrap network errors
        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if e.response is not None else None; error_details = None
            if e.response is not None: try: error_details = e.response.json()
            except requests.exceptions.JSONDecodeError: error_details = e.response.text
            logger.error(f"Network error calling {self.resolve_mapping_url} for instance {target_instance_id}. Status: {status_code}", exc_info=True)
            raise PiperAuthError(f"Network error resolving variable mapping: {e}", status_code=status_code, error_details=error_details) from e
        # Wrap other unexpected errors
        except Exception as e:
             logger.error(f"Unexpected error during resolve_variable_mapping for instance {target_instance_id}: {e}", exc_info=True)
             raise PiperError(f"An unexpected error occurred resolving variable mapping: {e}") from e


    def get_scoped_credentials_by_id(self, credential_ids: List[str], instance_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Retrieves STS credentials using the context from the provided or discovered instanceId.

        Args:
            credential_ids: A list of Piper credential ID strings.
            instance_id: (Optional) The Piper Link instanceId to use for context.
                         If None, attempts discovery via discover_local_instance_id().

        Returns:
            A dictionary containing the STS token response.

        Raises:
            PiperLinkNeededError: If instanceId is needed but cannot be found/discovered.
            PiperAuthError: For API authentication/authorization errors.
            ValueError: For invalid input.
        """
        target_instance_id = self._get_instance_id_or_raise(instance_id) # Get ID or raise
        if not credential_ids or not isinstance(credential_ids, list): raise ValueError("credential_ids must be a non-empty list.")
        cleaned_credential_ids = [str(cid).strip() for cid in credential_ids if str(cid).strip()]
        if not cleaned_credential_ids: raise ValueError("credential_ids list contains only empty strings.")

        try:
            target_audience = self.get_scoped_url
            agent_token = self._get_valid_agent_token(audience=target_audience, instance_id=target_instance_id)

            scoped_headers = {'Authorization': f'Bearer {agent_token}', 'Content-Type': 'application/json'}
            scoped_payload = {'credentialIds': cleaned_credential_ids}

            logger.info(f"Calling get_scoped_credentials for IDs: {scoped_payload['credentialIds']}, instance: {target_instance_id}")
            response = self._session.post(self.get_scoped_url, headers=scoped_headers, json=scoped_payload, timeout=15)

            # --- More specific error handling based on backend JSON ---
            if 400 <= response.status_code < 600:
                error_details: Any = None; error_code: str = f'http_{response.status_code}'; error_description: str = f"API Error {response.status_code}"
                try: error_details = response.json(); error_code = error_details.get('error', error_code); error_description = error_details.get('error_description', error_details.get('message', str(error_details)))
                except requests.exceptions.JSONDecodeError: error_details = response.text; error_description = error_details if error_details else error_description
                logger.error(f"API error getting scoped credentials for instance {target_instance_id}. Status: {response.status_code}, Code: {error_code}, Details: {error_details}")
                if response.status_code == 401 or error_code == 'invalid_token': self._token_expiries[(target_audience, target_instance_id)] = 0; raise PiperAuthError(f"Agent authentication failed getting scoped credentials: {error_description}", status_code=401, error_code=error_code or 'invalid_token', error_details=error_details)
                if response.status_code == 403 or error_code == 'permission_denied': raise PiperAuthError(f"Permission denied getting scoped credentials: {error_description}", status_code=403, error_code=error_code or 'permission_denied', error_details=error_details)
                raise PiperAuthError(f"Failed to get scoped credentials: {error_description}", status_code=response.status_code, error_code=error_code, error_details=error_details)
            # --- End specific error handling ---

            scoped_data = response.json()
            if 'access_token' not in scoped_data or 'granted_credential_ids' not in scoped_data:
                 raise PiperAuthError("Received unexpected response format from get_scoped_credentials.", status_code=response.status_code, error_details=scoped_data)

            requested_set = set(cleaned_credential_ids); granted_set = set(scoped_data.get('granted_credential_ids', []))
            if requested_set != granted_set: logger.warning(f"Partial success getting credentials for instance {target_instance_id}: Granted for {list(granted_set)}, but not for {list(requested_set - granted_set)}.")

            logger.info(f"Successfully received scoped credentials for instance {target_instance_id}, granted IDs: {scoped_data.get('granted_credential_ids')}")
            return scoped_data

        # Catch specific exceptions first
        except (PiperAuthError, PiperLinkNeededError, ValueError): raise
        # Wrap network errors
        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if e.response is not None else None; error_details = None
            if e.response is not None: try: error_details = e.response.json()
            except requests.exceptions.JSONDecodeError: error_details = e.response.text
            logger.error(f"Network error calling {self.get_scoped_url} for instance {target_instance_id}. Status: {status_code}", exc_info=True)
            raise PiperAuthError(f"Network error getting scoped credentials: {e}", status_code=status_code, error_details=error_details) from e
        # Wrap other unexpected errors
        except Exception as e:
             logger.error(f"Unexpected error during get_scoped_credentials for instance {target_instance_id}: {e}", exc_info=True)
             raise PiperError(f"An unexpected error occurred getting scoped credentials: {e}") from e


    def get_scoped_credentials_for_variable(self, variable_name: str, instance_id: Optional[str] = None) -> Dict[str, Any]:
         """
         Retrieves short-lived GCP STS credentials for the variable name, using context
         from the provided or discovered instanceId.

         This is the primary convenience method. It attempts to discover the local
         Piper Link instanceId if not provided.

         Args:
            variable_name: The logical variable name defined by the agent.
            instance_id: (Optional) The Piper Link instanceId to use for context.

         Returns:
             A dictionary containing the STS token response from Piper.

         Raises:
            PiperLinkNeededError: If instanceId is needed but cannot be found/discovered.
            PiperAuthError: For API authentication/authorization errors.
            ValueError: For invalid input.
         """
         # Discover or validate instanceId first (will raise PiperLinkNeededError if needed)
         target_instance_id = self._get_instance_id_or_raise(instance_id)

         logger.info(f"Attempting to get scoped credentials for variable: '{variable_name}', instance: {target_instance_id}")
         # If we reach here, target_instance_id is valid

         # Step 1: Resolve variable (will use target_instance_id implicitly via token fetch)
         # Pass target_instance_id explicitly to avoid redundant discovery
         credential_id = self.get_credential_id_for_variable(
             variable_name=variable_name,
             instance_id=target_instance_id
         )
         # Step 2: Get credentials (will use target_instance_id implicitly via token fetch)
         # Pass target_instance_id explicitly to avoid redundant discovery
         return self.get_scoped_credentials_by_id(
             credential_ids=[credential_id],
             instance_id=target_instance_id
         )

    # --- Placeholder for User Auth flows (like the one Piper Link app uses) ---
    # These methods would likely live in a separate helper class or module,
    # or potentially be static methods if they don't rely on agent client_id/secret.
    # They would handle the browser opening, code exchange etc for the *linking* process.
    # def initiate_piper_link_flow(...)
    # def complete_piper_link_flow(...)