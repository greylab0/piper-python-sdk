# Pyper SDK for Python (v0.3.0)

[![PyPI version](https://badge.fury.io/py/pyper-sdk.svg)](https://badge.fury.io/py/pyper-sdk)
[![Python Versions](https://img.shields.io/pypi/pyversions/pyper-sdk.svg)](https://pypi.org/project/pyper-sdk/)
[![License: MIT](https://img.shields.io/pypi/l/pyper-sdk.svg)](https://opensource.org/licenses/MIT)

The official Python SDK for integrating your applications (agents, MCPs, scripts) with **Piper**, the secure credential management system designed for the AI era.

Stop asking your users to paste sensitive API keys directly into every tool! With Piper, users store their secrets once in a central, secure vault. Your application, using this SDK, can then request temporary, scoped access to those secrets *only after the user has explicitly granted permission* via the Piper dashboard.

This SDK simplifies the process for your agent application to:

1.  Establish the end-user's Piper context by automatically discovering the **Piper Link application's** local `instanceId`.
2.  Authenticate your agent application to the Piper system using its own credentials.
3.  Request access to secrets using logical **variable names** that you define for your agent (e.g., `my_gmail_token`, `openai_api_key`). The SDK normalizes these names to a canonical format (e.g., `lowercase_snake_case`) for API calls.
4.  Receive short-lived GCP Security Token Service (STS) tokens if a grant exists via Piper.
5.  Optionally, fall back to environment variables if Piper access is not configured, a specific grant is missing, or the Piper Link app is not running.

## Core Problem Piper Solves

Modern AI agents and applications often require access to numerous sensitive user credentials. Manually managing these by asking users to paste keys into multiple applications is risky and inconvenient:

*   **Secret Sprawl**: Keys are duplicated, increasing the attack surface.
*   **Difficult Revocation**: Removing access from a compromised key or specific tool is hard.
*   **Lack of Control & Audit**: Users lose track of which applications access their keys.

Piper provides a centralized, user-controlled layer. Think of it as a **secure wallet or password manager specifically for your application API keys and tokens.**

## How it Works (Simplified Flow)

1.  **User Stores Secret in Piper**: The user adds their API key (e.g., "My Personal OpenAI Key") to their Piper dashboard once. Piper encrypts and stores the actual secret value in Google Secret Manager.
2.  **User Installs & Links "Piper Link" App (One-Time Locally)**:
    *   The user installs the lightweight "Piper Link" application (provided separately by Piper) on their local machine.
    *   They perform a one-time login via Piper Link, which securely associates their local environment (represented by a unique `instanceId`) with their Piper account.
    *   The Piper Link app then runs a local service to provide this `instanceId` to SDK instances.
3.  **Developer Registers Agent**: You register your application ("MyCoolAgent") with Piper, defining the logical **variable names** it will use (e.g., `openai_api_key`). These are stored by Piper in a canonical format (e.g., `lowercase_snake_case`).
4.  **User Grants Permission in Piper UI**: The user goes to their Piper dashboard and explicitly grants "MyCoolAgent" permission to access *their specific* "My Personal OpenAI Key" when "MyCoolAgent" requests it using the (canonical) variable name `openai_api_key`.
5.  **Agent Uses SDK `get_secret()`**:
    *   Your "MyCoolAgent" application initializes the `pyper-sdk`'s `PiperClient` with its own agent `client_id` and `client_secret` value.
    *   When your agent calls `piper_client.get_secret("OpenAI API Key")`:
        *   The SDK normalizes "OpenAI API Key" to `openai_api_key` (example).
        *   It automatically tries to discover the `instanceId` from the local Piper Link app.
        *   It sends your agent's credentials, the discovered `instanceId`, and the normalized `variable_name` (`openai_api_key`) to the Piper backend.
        *   Piper's backend verifies everything, resolves `instanceId` to the `user_id`, and checks if that user has granted your agent access to a secret for `openai_api_key`.
        *   If authorized via Piper, the SDK receives a short-lived GCP STS token.
        *   If the Piper flow fails (e.g., Link app not running, no grant) and fallback is enabled, the SDK attempts to read from a configured environment variable (e.g., `MYAPP_OPENAI_API_KEY`).
        *   The SDK returns a dictionary with the `source` ("piper_sts" or "environment_variable") and the `value` (STS token or raw secret from env var).
6.  **Agent Uses the Secret/Token**:
    *   **If from Piper (`source: 'piper_sts'`):** Your agent uses the returned STS token (`value`) with Google Cloud client libraries (e.g., `google-cloud-secret-manager`) to fetch the actual secret value from Google Secret Manager. For this operation, your agent temporarily acts with the permissions of Piper's internal service account.
    *   **If from an environment variable (`source: 'environment_variable'`):** Your agent uses the raw secret value directly.

## Installation

```bash
pip install pyper-sdk==0.3.0
```
*(Replace `0.3.0` with the latest version if necessary)*

## Prerequisites for Your Agent Application

Before your application can use this SDK to access user secrets via Piper, some setup is required:

1.  **Register Your Agent with Piper:**
    *   Go to the Piper registration portal (e.g., `agentpiper.com` - *replace with actual URL*).
    *   Register your application as an "Agent."
    *   You will receive a **`Client ID`** for your agent.
    *   You will be given a **`Client Secret Name`**. This is the name of the secret in *Piper's own Google Secret Manager project* where your agent's actual `client_secret` value is stored (e.g., `agent-secret-YOUR_AGENT_CLIENT_ID`).
    *   Define the **Variable Names** your agent will use (e.g., `openai_api_key`, `user_database_url`). Piper will store these in a canonical format (e.g., `lowercase_snake_case`). These are the names you will pass to `sdk.get_secret()`.

2.  **GCP IAM Permissions for Your Agent to Fetch its Own Secret:**
    *   Your agent application's runtime identity (e.g., a service account if running on GCP, or your Application Default Credentials for local development) **must have IAM permission to fetch its *own* `client_secret` value from Piper's Secret Manager.**
    *   This typically involves granting the `secretmanager.secretAccessor` role to your agent's identity on the specific secret resource: `projects/PIPER_SYSTEM_PROJECT_ID/secrets/YOUR_AGENT_CLIENT_SECRET_NAME/versions/latest`.
    *   Consult Piper documentation for the exact `PIPER_SYSTEM_PROJECT_ID`.

3.  **Instruct Your End-Users:**
    *   Users must have a Piper account.
    *   Users need to download, install, and run the **Piper Link application** (instructions provided separately by Piper) and link their Piper account through it once on their local machine. This establishes their local context.
    *   Users must go to their Piper dashboard to grant your specific agent permission to access their specific secrets, mapping them to the variable names your agent uses.

## SDK Usage Example

```python
import os
import logging
from pyper_sdk.client import PiperClient, PiperConfigError, PiperAuthError, PiperLinkNeededError
from google.cloud import secretmanager # Required if using STS tokens to fetch from GCP SM
from google.oauth2 import credentials  # For using STS tokens with GCP libraries

```

### --- Agent Configuration ---

```python

# These should be securely managed by your application and set as environment variables
MY_AGENT_CLIENT_ID = os.environ.get("MY_AGENT_PIPER_CLIENT_ID")
MY_AGENT_CLIENT_SECRET_NAME = os.environ.get("MY_AGENT_PIPER_CLIENT_SECRET_NAME") # Name in Piper's SM

# This is Piper's main GCP Project ID - obtain from Piper documentation
PIPER_SYSTEM_GCP_PROJECT_ID = os.environ.get("PIPER_SYSTEM_PROJECT_ID", "444535882337") 

```

### --- Logging Setup ---

```python

logging.basicConfig(level=logging.INFO) 
logging.getLogger('PiperSDK').setLevel(logging.DEBUG) # DEBUG for verbose SDK output
logging.getLogger('urllib3').setLevel(logging.WARNING) # Quieten noisy library

def fetch_this_agent_client_secret_value(piper_gcp_project: str, sm_secret_name_for_this_agent: str) -> str:
    """
    Fetches this agent's own client_secret value from Piper's Secret Manager.
    Your agent's runtime identity needs 'secretmanager.secretAccessor' permission.
    """
    try:
        sm_client = secretmanager.SecretManagerServiceClient() # Uses Application Default Credentials
        full_secret_path = sm_client.secret_version_path(piper_gcp_project, sm_secret_name_for_this_agent, "latest")
        logging.debug(f"Fetching agent's client_secret from: {full_secret_path}")
        response = sm_client.access_secret_version(request={"name": full_secret_path})
        secret_value = response.payload.data.decode("UTF-8")
        if not secret_value:
            raise PiperConfigError(f"Fetched agent client_secret '{sm_secret_name_for_this_agent}' is empty.")
        return secret_value
    except Exception as e:
        logging.error(f"FATAL: Could not fetch this agent's client_secret ('{sm_secret_name_for_this_agent}') from Piper's SM: {e}", exc_info=True)
        raise PiperConfigError(f"Failed to fetch own client_secret '{sm_secret_name_for_this_agent}'. Ensure agent identity has permission in project '{piper_gcp_project}'.") from e

def get_actual_secret_from_sm_using_sts(sts_token_value: str, user_secret_name_in_piper_sm: str, piper_gcp_project: str) -> str:
    """
    Uses a Piper-issued STS token to fetch the actual user secret from Piper's SM.
    The 'user_secret_name_in_piper_sm' is the actual name of the user's secret
    in Secret Manager (this is the 'piper_credential_id' returned by get_secret()).
    """
    try:
        temp_gcp_creds = credentials.Credentials(token=sts_token_value)
        sm_client = secretmanager.SecretManagerServiceClient(credentials=temp_gcp_creds)
        
        # The piper_credential_id *is* the name of the secret in Piper's Secret Manager
        secret_version_path = sm_client.secret_version_path(piper_gcp_project, user_secret_name_in_piper_sm, "latest")
        
        logging.info(f"Fetching actual secret value from SM: {secret_version_path} using STS token.")
        response = sm_client.access_secret_version(name=secret_version_path)
        actual_secret = response.payload.data.decode('UTF-8')
        logging.info(f"Successfully fetched actual secret for {user_secret_name_in_piper_sm}.")
        return actual_secret
    except Exception as e:
        logging.error(f"Failed to fetch actual secret {user_secret_name_in_piper_sm} using STS token: {e}", exc_info=True)
        raise PiperError(f"Could not retrieve actual secret '{user_secret_name_in_piper_sm}' from SM using STS token.") from e

if __name__ == "__main__":
    if not MY_AGENT_CLIENT_ID or not MY_AGENT_CLIENT_SECRET_NAME:
        print("FATAL: MY_AGENT_PIPER_CLIENT_ID and MY_AGENT_PIPER_CLIENT_SECRET_NAME environment variables must be set.")
        exit(1)

    try:
        my_agent_secret_value = fetch_this_agent_client_secret_value(
            PIPER_SYSTEM_GCP_PROJECT_ID,
            MY_AGENT_CLIENT_SECRET_NAME
        )
        print(f"Successfully fetched this agent's client_secret (ending ...{my_agent_secret_value[-4:]}).")

        piper_client = PiperClient(
            client_id=MY_AGENT_CLIENT_ID,
            client_secret=my_agent_secret_value,
            # _piper_system_project_id=PIPER_SYSTEM_GCP_PROJECT_ID, # Only if overriding SDK defaults for URL construction
            # enable_env_fallback=True, # Default is True
            # env_variable_prefix="MYAPP_", 
            # env_variable_map={"My Custom OpenAI Variable": "MY_EXACT_OAI_ENV_VAR"}
        )
        print(f"PiperClient initialized. SDK will attempt Piper Link discovery.")
```

### --- Example 1: Get an OpenAI Key via Piper ---

```python

        # Assumes:
        # 1. User has run Piper Link app.
        # 2. User has granted this agent access to variable "openai_api_key" in Piper UI.
        # 3. Environment variable (e.g., MYAPP_OPENAI_API_KEY) is NOT set, to force Piper attempt.
        
        openai_variable = "openai_api_key" # This is the canonical name your agent defined
        
        print(f"\nAttempting to get secret for Piper Variable: '{openai_variable}'")
        secret_info = piper_client.get_secret(openai_variable) # SDK normalizes "OpenAI API Key" if dev typed that
        
        print(f"  Source: {secret_info['source']}")
        actual_openai_key = None

        if secret_info['source'] == 'piper_sts':
            print(f"  STS Token (last 6): ...{secret_info['value'][-6:]}")
            # The 'piper_credential_id' IS the name of the secret in Piper's Secret Manager
            actual_openai_key = get_actual_secret_from_sm_using_sts(
                secret_info['value'], # This is the STS token
                secret_info['piper_credential_id'], # This is the SM Secret ID
                PIPER_SYSTEM_GCP_PROJECT_ID
            )
        elif secret_info['source'] == 'environment_variable':
            print(f"  Env Var Name: {secret_info['env_var_name']}")
            actual_openai_key = secret_info['value'] # This is the raw secret
        
        if actual_openai_key:
            print(f"  Retrieved Actual OpenAI Key (last 6 chars): ...{actual_openai_key[-6:]}")
            # Now your agent can use actual_openai_key with the OpenAI library
        else:
            print(f"  Could not retrieve OpenAI key value.")

    except PiperLinkNeededError:
        print("ERROR: Piper Link is not set up. Please instruct the user to run the Piper Link application to link their Piper account.")
    except PiperConfigError as e:
        print(f"ERROR: SDK or Agent Configuration Error: {e}")
    except PiperAuthError as e:
        print(f"ERROR: Piper Authentication/Authorization Error: {e}")
    except Exception as e:
        print(f"An unexpected fatal error occurred in the application: {e}", exc_info=True)
```

## Error Handling

The primary method `piper_client.get_secret()` can raise several exceptions:

*   **`ValueError`**: If `variable_name` passed to `get_secret()` is invalid.
*   **`PiperLinkNeededError`**: If the Piper Link application is not running or configured, and Piper access is attempted (and fallback is disabled or also fails). Your application should catch this and guide the user to set up Piper Link.
*   **`PiperAuthError`**: If there's an issue with Piper API calls:
    *   `error_code='mapping_not_found'`: The user has not granted your agent access to this variable in their Piper dashboard.
    *   `error_code='permission_denied'`: The grant exists, but some other permission check failed (e.g., Firestore grant status not "ACTIVE" for the underlying credential).
    *   Other codes for `invalid_client` (your agent's own `client_id`/`secret` issue), `invalid_token`, etc.
    *   The exception object contains `status_code`, `error_code`, and `error_details` from the API.
*   **`PiperConfigError`**: If Piper access fails for other configuration reasons (e.g., could not fetch agent's own client secret), AND environment variable fallback is disabled or also fails. The message will indicate both failures if applicable.

Always wrap calls to `get_secret()` in `try...except` blocks to handle these cases gracefully in your application.

## Environment Variable Fallback

The `PiperClient`'s `get_secret()` method supports falling back to environment variables if the Piper flow cannot retrieve the secret. This allows for flexibility and gradual adoption.

*   **`enable_env_fallback: bool`** (in `PiperClient.__init__`, defaults to `True`): If `True`, `get_secret()` will attempt to read from an environment variable if the Piper flow fails (e.g., `PiperLinkNeededError` is raised internally, or Piper returns `mapping_not_found`, `permission_denied`).
*   **How Fallback Variable Names are Determined:**
    1.  **`fallback_env_var_name` parameter in `get_secret()`:** If you provide this, it uses that exact environment variable name.
    2.  **`env_variable_map: Dict[str, str]`** (in `PiperClient.__init__`): If `fallback_env_var_name` is not given, the SDK checks this map using the original `variable_name` (e.g., `"My OpenAI Key"`) as the key. Example: `env_variable_map={"My OpenAI Key": "MY_APPS_ACTUAL_OAI_ENV_VAR"}`.
    3.  **`env_variable_prefix: str`** (in `PiperClient.__init__`): If no map entry is found, the SDK constructs a name:
        *   Takes the original `variable_name` (e.g., `"My OpenAI Key"`).
        *   Converts it to UPPERCASE_SNAKE_CASE (e.g., `"MY_OPENAI_KEY"`).
        *   Prepends your `env_variable_prefix` (e.g., if prefix is `"AGENTX_"`, it looks for `AGENTX_MY_OPENAI_KEY`). An empty prefix is common.
*   The `get_secret()` method's return dictionary will have `source: "environment_variable"` and `env_var_name` indicating the variable found, if fallback was used. The `value` will be the raw secret string from the environment.

## Security Considerations

*   **Agent `client_secret`:** Your application is responsible for securely fetching and handling its own `client_secret` value (obtained from Piper's Secret Manager).
*   **Piper Link App:** Users need to trust and correctly install the Piper Link application for the `instanceId` discovery to work securely.
*   **STS Token Usage:** The STS tokens vended by Piper are short-lived and grant temporary impersonation of Piper's internal service account (`piper-functions-sa`) to access specific secrets in Google Secret Manager. Handle these STS tokens as sensitive credentials.

## License

MIT License