# piper_sdk/client.py

import requests
import time
from urllib.parse import urlencode, urljoin
import logging
from typing import List, Dict, Any, Optional, Tuple

# Configure logging for the SDK
# Consumers of the SDK can configure logging further if needed
logging.basicConfig(level=logging.INFO, format='%(asctime)s - PiperSDK - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__) # Changed logger name to PiperSDK for clarity

class PiperError(Exception):
    """Base exception for all Piper SDK errors."""
    pass

class PiperAuthError(PiperError):
    """Custom exception for Piper SDK authentication and API errors."""
    def __init__(self, message: str, status_code: Optional[int] = None, error_code: Optional[str] = None, error_details: Optional[Any] = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code # e.g., 'invalid_client', 'mapping_not_found'
        self.error_details = error_details # Raw error details from API (dict or text)
    def __str__(self):
        details_str = f", Details: {self.error_details}" if self.error_details else ""
        status_str = f" (Status: {self.status_code})" if self.status_code is not None else ""
        code_str = f" (Code: {self.error_code})" if self.error_code else ""
        return f"{super().__str__()}{status_str}{code_str}{details_str}"

class PiperConfigError(PiperError):
    """Exception for configuration issues (e.g., missing user_id context)."""
    pass

class PiperClient:
    """
    A Python client for interacting with the Piper API.

    Handles agent authentication (Client Credentials with User Context),
    variable name to credential ID resolution, and retrieving scoped GCP STS
    credentials for authorized secrets. Requires the User ID context for
    most operations.
    """
    DEFAULT_TOKEN_EXPIRY_BUFFER_SECONDS: int = 60
    # *** IMPORTANT: Update these defaults if your deployment differs ***
    DEFAULT_PROJECT_ID: str = "444535882337" # YOUR Piper GCP Project ID
    DEFAULT_REGION: str = "us-central1"     # YOUR Piper GCP Region

    # Endpoint URL Templates (Allow override via init)
    TOKEN_URL_TEMPLATE = "https://piper-token-endpoint-{project_id}.{region}.run.app"
    GET_SCOPED_URL_TEMPLATE = "https://getscopedgcpcredentials-{project_id}.{region}.run.app"
    RESOLVE_MAPPING_URL_TEMPLATE = "https://piper-resolve-variable-mapping-{project_id}.{region}.run.app"

    _active_user_id: Optional[str] = None # Stores user context if set globally

    def __init__(self,
                client_id: str,
                client_secret: str,
                project_id: Optional[str] = None,
                region: Optional[str] = None,
                token_url: Optional[str] = None,
                get_scoped_url: Optional[str] = None,
                resolve_mapping_url: Optional[str] = None,
                requests_session: Optional[requests.Session] = None):
        """
        Initializes the Piper Client for an agent.

        Args:
            client_id: The agent's Client ID.
            client_secret: The agent's Client Secret.
            project_id: GCP Project ID where Piper functions are deployed.
                        Defaults to DEFAULT_PROJECT_ID.
            region: GCP Region where Piper functions are deployed.
                    Defaults to DEFAULT_REGION.
            token_url: (Optional) Override the default URL for the /token endpoint.
            get_scoped_url: (Optional) Override the default URL for the /get-scoped-credentials endpoint.
            resolve_mapping_url: (Optional) Override the default URL for the /resolve-variable-mapping endpoint.
            requests_session: (Optional) A requests.Session object.
        """
        if not client_id or not client_secret:
            raise ValueError("client_id and client_secret are required.")
        self.client_id: str = client_id
        self._client_secret: str = client_secret
        # Use provided project/region or the class defaults
        self.project_id: str = project_id or self.DEFAULT_PROJECT_ID
        self.region: str = region or self.DEFAULT_REGION

        # Construct endpoint URLs, allowing overrides
        self.token_url: str = token_url or self.TOKEN_URL_TEMPLATE.format(project_id=self.project_id, region=self.region)
        self.get_scoped_url: str = get_scoped_url or self.GET_SCOPED_URL_TEMPLATE.format(project_id=self.project_id, region=self.region)
        self.resolve_mapping_url: str = resolve_mapping_url or self.RESOLVE_MAPPING_URL_TEMPLATE.format(project_id=self.project_id, region=self.region)

        self._session = requests_session if requests_session else requests.Session()
        self._session.headers.update({'User-Agent': f'Piper-Python-SDK/0.1.0'}) # Update version eventually

        # Internal state for caching agent tokens
        # Cache key is now (audience, user_id_context) tuple
        self._access_tokens: Dict[Tuple[str, Optional[str]], str] = {}
        self._token_expiries: Dict[Tuple[str, Optional[str]], float] = {}

        logger.info(f"PiperClient initialized for client_id '{self.client_id[:8]}...'.")
        logger.info(f" Token URL: {self.token_url}")
        logger.info(f" Resolve URL: {self.resolve_mapping_url}")
        logger.info(f" GetScoped URL: {self.get_scoped_url}")


    def set_active_user(self, user_id: str):
        """
        Sets the active Piper User ID context for subsequent calls made by this client instance.

        Args:
            user_id: The Piper User ID string.
        """
        if not user_id or not isinstance(user_id, str):
            raise ValueError("user_id must be a non-empty string.")
        logger.info(f"Setting active user context for SDK instance: {user_id}")
        self._active_user_id = user_id

    def _fetch_agent_token(self, audience: str, user_id_context: Optional[str]) -> Tuple[str, float]:
        """
        Internal: Fetches a new agent access token for a specific audience and user context
        using client_credentials grant. Passes user_id_context if provided.
        Returns (access_token, expiry_timestamp). Raises PiperAuthError on failure.
        """
        user_ctx_log = f"user_id_context: {user_id_context}" if user_id_context else "Default (no user context)"
        logger.info(f"Requesting new agent token via client_credentials for audience: {audience}, {user_ctx_log}")
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        data_dict = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self._client_secret,
            # 'scope': 'secret:read', # Scope might not be needed/used by client_credentials
            'audience': audience, # Specify the audience we need the token FOR
        }
        # *** ADD user_id_context if provided ***
        if user_id_context:
            data_dict['user_id_context'] = user_id_context
        else:
             # If no user_id is provided, the token endpoint might default
             # the 'sub' to the agent's own ID or reject the request if
             # user context is mandatory for the target audience.
             # This depends on the /token endpoint implementation.
             logger.warning(f"Requesting agent token without user_id_context for audience {audience}. Behavior depends on /token endpoint.")


        data_encoded = urlencode(data_dict)

        try:
            response = self._session.post(self.token_url, headers=headers, data=data_encoded, timeout=10)

            # Standardize error parsing based on backend convention
            # Assuming backend consistently returns JSON: {"error": "...", "error_description": "..."}
            if 400 <= response.status_code < 600: # Handle 4xx and 5xx
                error_details: Any = None
                error_code: str = f'http_{response.status_code}' # Default error code
                error_description: str = f"API Error {response.status_code}"
                try:
                    error_details = response.json()
                    error_code = error_details.get('error', error_code)
                    # Look for description or message, fallback to raw dict/text
                    error_description = error_details.get('error_description', error_details.get('message', str(error_details)))
                except requests.exceptions.JSONDecodeError:
                    error_details = response.text # Fallback to text if not JSON
                    error_description = error_details if error_details else error_description

                log_ctx = f"user {user_id_context}" if user_id_context else "no user"
                logger.error(f"Failed to obtain agent token for audience {audience}, {log_ctx}. Status: {response.status_code}, Code: {error_code}, Details: {error_details}")

                raise PiperAuthError(f"API error obtaining agent token: {error_description}", status_code=response.status_code, error_code=error_code, error_details=error_details)

            # If status code is 2xx, proceed
            token_data = response.json()
            access_token = token_data.get('access_token')
            # expires_in should be a number, but handle potential string
            expires_in_raw = token_data.get('expires_in', 0)
            try:
                expires_in = int(expires_in_raw)
            except (ValueError, TypeError):
                logger.warning(f"Invalid 'expires_in' value received: {expires_in_raw}. Defaulting to 0.")
                expires_in = 0

            if not access_token:
                logger.error(f"No access token found in successful response from {self.token_url}. Response: {token_data}")
                raise PiperAuthError("Failed to obtain access token (token missing in response).", status_code=response.status_code, error_details=token_data)

            expiry_timestamp = time.time() + expires_in
            log_ctx = f"user {user_id_context}" if user_id_context else "no user"
            logger.info(f"Successfully obtained new agent token for audience {audience}, {log_ctx} (expires ~{time.ctime(expiry_timestamp)}).")
            return access_token, expiry_timestamp

        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if e.response is not None else None
            log_ctx = f"user {user_id_context}" if user_id_context else "no user"
            logger.error(f"Network/Request error getting agent token from {self.token_url} for {log_ctx}. Status: {status_code}", exc_info=True)
            # Try to get details from response if available
            error_details = None
            if e.response is not None:
                try: error_details = e.response.json()
                except requests.exceptions.JSONDecodeError: error_details = e.response.text
            raise PiperAuthError(f"Request failed for agent token: {e}", status_code=status_code, error_details=error_details) from e
        except Exception as e: # Catch unexpected SDK-side errors
            log_ctx = f"user {user_id_context}" if user_id_context else "no user"
            logger.error(f"Unexpected error during agent token fetch for {log_ctx}: {e}", exc_info=True)
            raise PiperAuthError(f"An unexpected error occurred fetching agent token: {e}") from e


    def _get_valid_agent_token(self, audience: str, user_id_context: Optional[str], force_refresh: bool = False) -> str:
        """
        Internal: Gets a valid agent access token for a specific audience and user context.
        Uses (audience, user_id_context) as the cache key.
        """
        cache_key = (audience, user_id_context)
        now = time.time()
        cached_token = self._access_tokens.get(cache_key)
        cached_expiry = self._token_expiries.get(cache_key, 0)

        # Check cache validity
        if not force_refresh and cached_token and cached_expiry > (now + self.DEFAULT_TOKEN_EXPIRY_BUFFER_SECONDS):
            log_ctx = f"user_context: {user_id_context}" if user_id_context else "no user context"
            logger.debug(f"Using cached agent token for audience: {audience}, {log_ctx}")
            return cached_token
        else:
            if cached_token and not force_refresh:
                log_ctx = f"user_context: {user_id_context}" if user_id_context else "no user context"
                logger.info(f"Agent token for audience {audience}, {log_ctx} expired or nearing expiry, refreshing.")

            # Fetch new token for the specific audience and user context
            access_token, expiry_timestamp = self._fetch_agent_token(
                audience=audience,
                user_id_context=user_id_context
            ) # Raises PiperAuthError on failure

            # Update cache using the tuple key
            self._access_tokens[cache_key] = access_token
            self._token_expiries[cache_key] = expiry_timestamp
            return access_token


    def get_credential_id_for_variable(self, variable_name: str, user_id: Optional[str] = None) -> str:
        """
        Resolves an agent's internal variable name to the specific Piper credential ID
        granted by the specified user (or the active user set via set_active_user).

        Args:
            variable_name: The logical variable name defined by the agent (e.g., "GMAIL_API_KEY").
            user_id: (Optional) The Piper User ID whose grant mapping should be resolved.
                     If None, uses the user ID set via set_active_user().

        Returns:
            The Piper credential ID (Bubble unique ID of the Piper - Secret) string.

        Raises:
            PiperConfigError: If user_id is None and no active user has been set.
            PiperAuthError: If authentication fails, the mapping is not found (404),
                          or the API returns an unexpected error.
            ValueError: If variable_name is empty.
        """
        active_user = user_id or self._active_user_id
        if not active_user:
            raise PiperConfigError("User ID context not set. Call set_active_user() or pass user_id.")
        if not variable_name or not isinstance(variable_name, str):
            raise ValueError("variable_name must be a non-empty string.")
        trimmed_variable_name = variable_name.strip()
        if not trimmed_variable_name:
             raise ValueError("variable_name cannot be empty or just whitespace.")

        try:
            # Get an agent token specifically for the resolve mapping endpoint and user context
            target_audience = self.resolve_mapping_url
            agent_token = self._get_valid_agent_token(audience=target_audience, user_id_context=active_user)

            headers = {
                'Authorization': f'Bearer {agent_token}',
                'Content-Type': 'application/json'
            }
            payload = {'variableName': trimmed_variable_name}

            logger.info(f"Calling resolve_variable_mapping for variable: '{trimmed_variable_name}', user: {active_user}")
            response = self._session.post(self.resolve_mapping_url, headers=headers, json=payload, timeout=10)

            # Standardize error parsing (assuming backend now uses JSON errors)
            if 400 <= response.status_code < 600:
                error_details: Any = None
                error_code: str = f'http_{response.status_code}'
                error_description: str = f"API Error {response.status_code}"
                try:
                    error_details = response.json()
                    error_code = error_details.get('error', error_code)
                    error_description = error_details.get('error_description', error_details.get('message', str(error_details)))
                except requests.exceptions.JSONDecodeError:
                    error_details = response.text
                    error_description = error_details if error_details else error_description

                logger.error(f"API error resolving mapping for var '{trimmed_variable_name}', user {active_user}. Status: {response.status_code}, Code: {error_code}, Details: {error_details}")

                # Invalidate token cache only on explicit auth failure
                if response.status_code == 401 or error_code == 'invalid_token':
                    logger.warning(f"Received 401/invalid_token from resolve_variable_mapping for user {active_user}. Forcing token refresh.")
                    self._token_expiries[(target_audience, active_user)] = 0 # Invalidate specific token

                # Specific handling for mapping not found
                if response.status_code == 404 or error_code == 'mapping_not_found':
                    logger.warning(f"Mapping not found for variable '{trimmed_variable_name}', user '{active_user}'. Check grants.")
                    raise PiperAuthError(f"No active grant mapping found for variable '{trimmed_variable_name}' for user '{active_user}'.", status_code=response.status_code or 404, error_code='mapping_not_found', error_details=error_details)

                raise PiperAuthError(f"Failed to resolve variable mapping: {error_description}", status_code=response.status_code, error_code=error_code, error_details=error_details)


            mapping_data = response.json()
            credential_id = mapping_data.get('credentialId')

            if not credential_id or not isinstance(credential_id, str):
                logger.error(f"Invalid response from resolve_variable_mapping: missing or invalid 'credentialId'. Response: {mapping_data}")
                raise PiperAuthError("Received unexpected response format from variable mapping endpoint.", status_code=response.status_code, error_details=mapping_data)

            logger.info(f"Successfully resolved variable '{trimmed_variable_name}' for user '{active_user}' to credentialId '{credential_id}'.")
            return credential_id

        except PiperAuthError: # Re-raise specific auth/API errors
            raise
        except ValueError: # Re-raise validation errors
            raise
        except requests.exceptions.RequestException as e: # Wrap network errors
            status_code = e.response.status_code if e.response is not None else None
            logger.error(f"Network/Request error calling {self.resolve_mapping_url} for user {active_user}. Status: {status_code}", exc_info=True)
            error_details = None
            if e.response is not None:
                try: error_details = e.response.json()
                except requests.exceptions.JSONDecodeError: error_details = e.response.text
            raise PiperAuthError(f"Failed to resolve variable mapping due to network or server error: {e}", status_code=status_code, error_details=error_details) from e
        except Exception as e: # Catch any other unexpected SDK errors
            logger.error(f"Unexpected error during resolve_variable_mapping for user {active_user}: {e}", exc_info=True)
            raise PiperAuthError(f"An unexpected error occurred resolving variable mapping: {e}") from e


    def get_scoped_credentials_by_id(self, credential_ids: List[str], user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Retrieves short-lived GCP STS credentials for the specified credential IDs,
        authorized for the given user context (specified or active).

        Args:
            credential_ids: A list of Piper credential ID strings (Bubble unique IDs).
            user_id: (Optional) The Piper User ID context for which the grants are checked.
                     If None, uses the user ID set via set_active_user().

        Returns:
            A dictionary containing the STS token response. Includes 'access_token' (STS),
            'expires_in', 'token_type', 'granted_credential_ids'.

        Raises:
            PiperConfigError: If user_id is None and no active user has been set.
            PiperAuthError: If authentication fails or Piper API returns an error (4xx/5xx).
            ValueError: If credential_ids is invalid.
        """
        active_user = user_id or self._active_user_id
        if not active_user:
             raise PiperConfigError("User ID context not set. Call set_active_user() or pass user_id.")
        if not credential_ids or not isinstance(credential_ids, list) or not all(isinstance(cid, str) and cid for cid in credential_ids):
            raise ValueError("credential_ids must be a non-empty list of non-empty strings.")

        cleaned_credential_ids = [str(cid).strip() for cid in credential_ids if str(cid).strip()]
        if not cleaned_credential_ids:
            raise ValueError("credential_ids list is empty after cleaning.")

        try:
            # Get an agent token specifically for the get-scoped-credentials endpoint and user context
            target_audience = self.get_scoped_url
            agent_token = self._get_valid_agent_token(audience=target_audience, user_id_context=active_user)

            scoped_headers = {
                'Authorization': f'Bearer {agent_token}',
                'Content-Type': 'application/json'
            }
            scoped_payload = {'credentialIds': cleaned_credential_ids}

            logger.info(f"Calling get_scoped_credentials for IDs: {scoped_payload['credentialIds']}, user: {active_user}")
            response = self._session.post(self.get_scoped_url, headers=scoped_headers, json=scoped_payload, timeout=15)

            # Standardize error parsing (assuming backend now uses JSON errors)
            if 400 <= response.status_code < 600:
                error_details: Any = None
                error_code: str = f'http_{response.status_code}'
                error_description: str = f"API Error {response.status_code}"
                try:
                    error_details = response.json()
                    error_code = error_details.get('error', error_code)
                    error_description = error_details.get('error_description', error_details.get('message', str(error_details)))
                except requests.exceptions.JSONDecodeError:
                    error_details = response.text
                    error_description = error_details if error_details else error_description

                logger.error(f"API error getting scoped credentials for user {active_user}. Status: {response.status_code}, Code: {error_code}, Details: {error_details}")

                # Invalidate token cache only on explicit auth failure
                if response.status_code == 401 or error_code == 'invalid_token':
                    logger.warning(f"Received 401/invalid_token from get_scoped_credentials for user {active_user}. Forcing token refresh.")
                    self._token_expiries[(target_audience, active_user)] = 0 # Force refresh
                    raise PiperAuthError(f"Agent authentication failed: {error_description}", status_code=401, error_code=error_code or 'invalid_token', error_details=error_details)
                elif response.status_code == 403 or error_code == 'permission_denied':
                    logger.warning(f"Received 403/permission_denied from get_scoped_credentials for user {active_user}. Check grants. Details: {error_details}")
                    raise PiperAuthError(f"Permission denied: {error_description}", status_code=403, error_code=error_code or 'permission_denied', error_details=error_details)
                else: # Other 4xx/5xx
                    raise PiperAuthError(f"Failed to get scoped credentials: {error_description}", status_code=response.status_code, error_code=error_code, error_details=error_details)


            scoped_data = response.json()
            # Basic validation of success response structure
            if 'access_token' not in scoped_data or 'granted_credential_ids' not in scoped_data:
                logger.warning(f"Get scoped credentials response missing expected fields for user {active_user}: {scoped_data}")
                raise PiperAuthError("Received unexpected response format from get_scoped_credentials.", status_code=response.status_code, error_details=scoped_data)

            # Log potential partial success
            requested_set = set(cleaned_credential_ids)
            granted_set = set(scoped_data.get('granted_credential_ids', []))
            if requested_set != granted_set:
                missing_ids = requested_set - granted_set
                logger.warning(f"Partial success getting credentials for user {active_user}: Granted for {list(granted_set)}, but requested IDs {list(missing_ids)} were not granted (likely no active grant).")

            logger.info(f"Successfully received scoped credentials response for user {active_user}, granted IDs: {scoped_data.get('granted_credential_ids')}")
            return scoped_data

        except PiperAuthError: # Re-raise specific errors
            raise
        except ValueError: # Re-raise validation errors
            raise
        except requests.exceptions.RequestException as e: # Wrap network/5xx errors
            status_code = e.response.status_code if e.response is not None else None
            logger.error(f"Network/Request error calling {self.get_scoped_url} for user {active_user}. Status: {status_code}", exc_info=True)
            error_details = None
            if e.response is not None:
                try: error_details = e.response.json()
                except requests.exceptions.JSONDecodeError: error_details = e.response.text
            raise PiperAuthError(f"Failed to get scoped credentials due to network or server error: {e}", status_code=status_code, error_details=error_details) from e
        except Exception as e: # Catch any other unexpected SDK errors
            logger.error(f"Unexpected error during get_scoped_credentials for user {active_user}: {e}", exc_info=True)
            raise PiperAuthError(f"An unexpected error occurred getting scoped credentials: {e}") from e


    def get_scoped_credentials_for_variable(self, variable_name: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Retrieves short-lived GCP STS credentials for the credential mapped
        to the given agent variable name by the specified user (or active user).

        This is a convenience method that first resolves the variable name
        to a credential ID and then fetches the scoped credentials for that ID,
        using the appropriate user context throughout.

        Args:
            variable_name: The logical variable name defined by the agent (e.g., "GMAIL_API_KEY").
            user_id: (Optional) The Piper User ID context. If None, uses the ID
                     set via set_active_user().

        Returns:
            A dictionary containing the STS token response from Piper.

        Raises:
            PiperConfigError: If user_id context cannot be determined.
            PiperAuthError: If authentication fails, the variable mapping is not found,
                          no active grant exists, or the API returns an error.
            ValueError: If variable_name is empty.
        """
        active_user = user_id or self._active_user_id
        if not active_user:
             raise PiperConfigError("User ID context not set. Call set_active_user() or pass user_id.")
        # variable_name validation happens in get_credential_id_for_variable

        logger.info(f"Attempting to get scoped credentials for variable: '{variable_name}', user: {active_user}")
        try:
            # Step 1: Resolve variable name to credential ID (passing user_id)
            # This call already ensures active_user is not None
            credential_id = self.get_credential_id_for_variable(
                variable_name=variable_name,
                user_id=active_user # Pass resolved context explicitly
            )

            # Step 2: Get scoped credentials using the resolved ID (passing user_id)
            return self.get_scoped_credentials_by_id(
                credential_ids=[credential_id],
                user_id=active_user # Pass resolved context explicitly
            )

        except (PiperAuthError, PiperConfigError, ValueError) as e:
            # Log the specific error originating from the underlying calls
            logger.error(f"Failed to get scoped credentials for variable '{variable_name}', user '{active_user}': {e}")
            # Re-raise the specific error from the underlying call
            raise e
        except Exception as e: # Catch unexpected errors during orchestration
            logger.error(f"Unexpected error getting credentials for variable '{variable_name}', user '{active_user}': {e}", exc_info=True)
            # Wrap in PiperError for consistency
            raise PiperError(f"An unexpected error occurred retrieving credentials for variable: {e}") from e

    # --- Placeholder for future User Auth methods (Not Implemented) ---
    # def initiate_user_authorization(...) -> str: raise NotImplementedError("User authorization flow not implemented.")
    # def handle_authorization_callback(...) -> Dict[str, Any]: raise NotImplementedError("User authorization flow not implemented.")