```markdown
# Piper Python SDK

[![PyPI version](https://badge.fury.io/py/piper-sdk.svg)](https://badge.fury.io/py/piper-sdk) <!-- Optional: Only works after publishing to PyPI -->
<!-- Add other badges later: build status, coverage, etc. -->

A Python SDK for Agents to securely retrieve scoped credentials managed by the Piper system.

## Description

This SDK simplifies the process for Piper-integrated agents (client applications) to:

1.  Authenticate themselves using their `client_id` and `client_secret`.
2.  Obtain an Agent JWT scoped to a specific `audience` (the Piper API endpoint being called) and `user_id` context.
3.  Resolve a logical `variable_name` (defined by the agent) to the specific `credentialId` granted by the specified user via the Piper UI.
4.  Obtain short-lived, scoped GCP STS tokens for authorized credentials, using the user-specific Agent JWT for authorization checks.

This allows agents to access secrets stored in Google Secret Manager on behalf of a specific user, without handling the underlying secret material directly, using Piper as the authorization layer.

## Installation

```bash
pip install piper-sdk
```
*(Note: This command will only work after the package is published to the Python Package Index (PyPI). See Publishing section below.)*

For now, you can install directly from GitHub (after pushing the code):
```bash
pip install git+https://github.com/greylab0/piper-python-sdk.git
```
*(Make sure to replace `greylab0` with your actual GitHub username if it's different)*

## Usage

**Important:** The agent application using this SDK is responsible for determining and providing the correct `user_id` context for the end-user it is acting on behalf of.

```python
from piper_sdk.client import PiperClient, PiperAuthError, PiperConfigError
import os
import logging

# Configure logging level for the SDK (optional)
# logging.getLogger('PiperSDK').setLevel(logging.DEBUG) # Use DEBUG for verbose token/API call logging

# --- Configuration ---
# Best practice: Load these from environment variables or a secure config system
CLIENT_ID = os.environ.get("PIPER_CLIENT_ID")
CLIENT_SECRET = os.environ.get("PIPER_CLIENT_SECRET")
# *** IMPORTANT: Update these defaults if your deployment differs ***
PROJECT_ID = os.environ.get("PIPER_PROJECT_ID", "444535882337") # YOUR Piper GCP Project ID
REGION = os.environ.get("PIPER_REGION", "us-central1")         # YOUR Piper GCP Region

# --- Determine User ID Context ---
# CRITICAL: Your application must determine the correct Piper User ID.
# This could come from user input, a web session, host context (MCP), etc.
# Replace this example with your actual user ID retrieval logic.
CURRENT_USER_ID = os.environ.get("PIPER_USER_ID") # Example: loading from env var

if not CLIENT_ID or not CLIENT_SECRET:
    print("Error: PIPER_CLIENT_ID and PIPER_CLIENT_SECRET environment variables must be set.")
    exit(1)

if not CURRENT_USER_ID:
    print("Error: Could not determine Piper User ID context (e.g., set PIPER_USER_ID environment variable).")
    exit(1)

# --- Initialize Client ---
try:
    piper_client = PiperClient(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        project_id=PROJECT_ID,
        region=REGION
        # Optional: Override specific function URLs if not using defaults
        # token_url="https://your-custom-token-url...",
        # resolve_mapping_url="https://your-custom-resolve-url...",
        # get_scoped_url="https://your-custom-getscoped-url..."
    )
    print("PiperClient initialized successfully.")

    # OPTION 1: Set user context once (if the client instance is for one user)
    # If your agent instance only ever acts for ONE user, you can set it once.
    # piper_client.set_active_user(CURRENT_USER_ID)
    # print(f"SDK User context set globally to: {CURRENT_USER_ID}")

except PiperConfigError as e:
    print(f"Configuration Error: {e}")
    exit(1)
except ValueError as e:
    print(f"Initialization Value Error: {e}")
    exit(1)
except Exception as e:
    print(f"Unexpected error during client initialization: {e}")
    exit(1)

# --- Get Scoped Credentials for a Variable ---
# Replace "DATABASE_PASSWORD" with the logical variable name your agent expects.
variable_to_fetch = "DATABASE_PASSWORD"

try:
    print(f"\nAttempting to get credentials for variable: '{variable_to_fetch}' for user: {CURRENT_USER_ID}")

    # OPTION 2 (Recommended for multi-user agents): Pass user_id directly to the method call
    sts_credentials = piper_client.get_scoped_credentials_for_variable(
        variable_name=variable_to_fetch,
        user_id=CURRENT_USER_ID # Pass the specific user context here
    )

    # If using OPTION 1 (set_active_user), you could just call:
    # sts_credentials = piper_client.get_scoped_credentials_for_variable(variable_to_fetch)

    # --- Process the credentials ---
    sts_token = sts_credentials.get('access_token')
    expires_in = sts_credentials.get('expires_in')
    granted_ids = sts_credentials.get('granted_credential_ids')

    if sts_token:
        print(f"Successfully obtained STS token (expires in {expires_in}s) for user {CURRENT_USER_ID}.")
        print(f"Granted Credential IDs: {granted_ids}")
        print(f"STS Token (first 15 chars): {sts_token[:15]}...")

        # TODO: Use this sts_token with a GCP client library
        # Example (Conceptual - requires google-cloud-secret-manager library):
        # from google.cloud import secretmanager
        # from google.oauth2 import credentials
        #
        # print("Attempting to use STS token with Secret Manager...")
        # try:
        #     gcp_creds = credentials.Credentials(token=sts_token)
        #     secret_client = secretmanager.SecretManagerServiceClient(credentials=gcp_creds)
        #     # You need the actual Secret Manager secret ID mapped in Piper for one of the granted_ids
        #     # Example assumes the first granted ID corresponds to a secret named like this:
        #     secret_name = f"projects/{PROJECT_ID}/secrets/{granted_ids[0]}/versions/latest" # Needs correct secret name!
        #     print(f"Accessing secret version: {secret_name}")
        #     response = secret_client.access_secret_version(request={"name": secret_name})
        #     payload = response.payload.data.decode("UTF-8")
        #     print(f"Successfully accessed secret payload using STS token: {payload[:20]}...") # Print start of payload
        # except Exception as gcp_error:
        #      print(f"Error accessing GCP Secret Manager using STS token: {gcp_error}")

    else:
        # This case shouldn't happen if get_scoped_credentials_for_variable succeeded without error,
        # but defensive check is good.
        print(f"Failed to retrieve STS token for user {CURRENT_USER_ID}, but no exception was raised? Check response: {sts_credentials}")

except PiperConfigError as e:
    # Raised if user_id context is missing and set_active_user wasn't called
    print(f"SDK Configuration Error: {e}")
except PiperAuthError as e:
    print(f"Piper Authentication/Authorization Error for user {CURRENT_USER_ID}: {e}")
    # Example: Handle specific errors based on information in the exception
    if e.error_code == 'mapping_not_found':
        print(f" -> Detail: The variable '{variable_to_fetch}' has not been mapped to an active credential grant in Piper for user '{CURRENT_USER_ID}'. Check Piper UI.")
    elif e.error_code == 'permission_denied':
         print(f" -> Detail: Permission denied. Ensure an active grant exists for the mapped credential(s) for user '{CURRENT_USER_ID}'. Check Piper UI.")
    elif e.status_code == 401 or e.error_code == 'invalid_token':
         print(f" -> Detail: Authentication failed getting Piper token (check client ID/secret or token validity/audience/user_id context).")
    elif e.error_code == 'invalid_client':
         print(f" -> Detail: Client authentication failed (check client ID/secret).")
    # Add more specific handling based on status_code or error_code if needed
except ValueError as e:
    print(f"Input Value Error: {e}")
except Exception as e:
    print(f"An unexpected error occurred trying to get credentials for variable: {e}")


# --- Example: Getting credentials directly by ID ---
# Assume you already know the credential ID from somewhere else
known_credential_id = "17xxxxxxxxxxxxxxx" # Replace with a valid ID you know exists and is granted
print(f"\nAttempting to get credentials for known ID: '{known_credential_id}' for user: {CURRENT_USER_ID}")
try:
    sts_creds_direct = piper_client.get_scoped_credentials_by_id(
        credential_ids=[known_credential_id],
        user_id=CURRENT_USER_ID # Pass the specific user context here
    )
    print(f"Successfully obtained STS token for known ID '{known_credential_id}'.")
    # ... process sts_creds_direct['access_token'] ...
except PiperAuthError as e:
     print(f"Piper Error getting creds by ID for user {CURRENT_USER_ID}: {e}")
except ValueError as e:
    print(f"Input Value Error getting creds by ID: {e}")
except Exception as e:
    print(f"Unexpected error getting creds by ID for user {CURRENT_USER_ID}: {e}")

```

## Error Handling

The SDK raises custom exceptions found in `piper_sdk.client`:

*   `PiperConfigError`: For issues during client initialization (e.g., missing config) or if user context is missing when required.
*   `PiperAuthError`: For errors interacting with the Piper API (authentication failures, permissions issues, mapping not found, API errors, etc.). This exception includes attributes like `status_code`, `error_code`, and `error_details` from the API response where available. Check these for detailed diagnosis.
*   `ValueError`: For invalid input provided to SDK methods (e.g., empty variable name, missing user ID).
*   Standard `requests.exceptions.RequestException` might be raised for underlying network issues, though often wrapped in `PiperAuthError`.

Always wrap SDK calls in `try...except` blocks to handle potential errors gracefully.

## Development & Contributing

(Optional: Add setup instructions for development, testing procedures, contribution guidelines)

1.  Clone the repository: `git clone https://github.com/greylab0/piper-python-sdk.git`
2.  Navigate into the directory: `cd piper-python-sdk`
3.  Create a virtual environment: `python -m venv venv`
4.  Activate it: `source venv/bin/activate` (Linux/macOS) or `venv\Scripts\activate` (Windows)
5.  Install dependencies (including dev tools if added): `pip install requests` (add flake8, pytest, etc. later if needed)
6.  Install in editable mode: `pip install -e .`

## Publishing to PyPI (For Maintainers)

1.  Update version number in `setup.py`.
2.  Install build tools: `pip install build twine`
3.  Clean old builds: `rm -rf dist/ build/ *.egg-info`
4.  Build package: `python -m build`
5.  Upload to TestPyPI: `python -m twine upload --repository testpypi dist/*` (Use `__token__` as username and a TestPyPI API token as password)
6.  Upload to PyPI: `python -m twine upload dist/*` (Use `__token__` as username and a PyPI API token as password)

## License

[MIT License](LICENSE)
```