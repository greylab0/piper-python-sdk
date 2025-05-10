Pyper SDK for Python
![alt text](https://badge.fury.io/py/pyper-sdk.svg)

![alt text](https://img.shields.io/pypi/pyversions/pyper-sdk.svg)

![alt text](https://img.shields.io/pypi/l/pyper-sdk.svg)
The official Python SDK for integrating your applications (agents, MCPs, scripts) with Piper, the secure credential management system designed for the AI era.
Stop asking your users to paste sensitive API keys directly into every tool! With Piper, users store their secrets once in a central, secure vault. Your application, using this SDK, can then request temporary, scoped access to those secrets only after the user has explicitly granted permission via the Piper dashboard.
This SDK simplifies the process for your agent application to:
Establish the end-user's Piper context via the Piper Link application.
Authenticate your agent application to the Piper system.
Request access to secrets using logical variable names that you define for your agent.
Receive short-lived GCP Security Token Service (STS) tokens, which can then be used to fetch the actual secret value from Google Secret Manager (where Piper stores them securely).
Optionally, fall back to environment variables if Piper access is not configured or a specific grant is missing.
Core Problem Piper Solves
Modern AI agents and applications often require access to numerous sensitive user credentials (OpenAI keys, database passwords, Slack tokens, etc.). Asking users to manage and paste these keys into multiple applications creates significant security risks and a poor user experience:
Secret Sprawl: Keys are duplicated across many tools.
Increased Attack Surface: A vulnerability in any one tool can compromise the key.
Difficult Revocation: Removing access from a specific tool or a compromised key becomes a manual and error-prone process.
Lack of Centralized Control & Audit: Users lose track of which applications have access to which keys.
Piper provides a centralized, user-controlled layer for managing these secrets.
How it Works (for End-Users & Developers)
End-User Stores Secret in Piper: The user adds their sensitive API keys (e.g., "My OpenAI Key") to their personal Piper dashboard once. Piper encrypts and stores the actual secret value in Google Secret Manager.
End-User Installs Piper Link (One-Time): For applications running on their local machine (CLIs, desktop tools, local MCPs), the user installs the "Piper Link" application. They perform a one-time login via Piper Link to securely associate their local environment with their Piper account. This creates a local instanceId.
Developer Registers Agent: You (the developer) register your application ("MyCoolAgent") with Piper, defining the logical variable names your agent will use (e.g., openai_api_token, user_database_url).
End-User Grants Permission in Piper UI: The user goes to their Piper dashboard and explicitly grants "MyCoolAgent" permission to access their specific "My OpenAI Key" secret when "MyCoolAgent" requests it using the variable name openai_api_token.
Agent Uses SDK: Your "MyCoolAgent" application uses this pyper-sdk.
The SDK automatically tries to discover the instanceId from the local Piper Link application.
When your agent calls piper_client.get_secret("openai_api_token"):
The SDK sends your agent's credentials, the instanceId, and the (normalized) variable_name to the Piper backend.
Piper's backend verifies everything: authenticates your agent, resolves the instanceId to the user_id, checks if that user has granted your agent access to a secret for the variable openai_api_token.
If authorized, Piper returns a short-lived GCP STS token to the SDK.
The SDK returns this STS token (and source information) to your agent.
Your agent then uses this STS token to fetch the actual secret value from Google Secret Manager.
Fallback (Optional): If the Piper flow fails (e.g., Piper Link not running, user hasn't granted permission) and you've enabled it, the SDK can attempt to read the secret from a predefined environment variable.
Installation
pip install pyper-sdk
Use code with caution.
Bash
Prerequisites for Your Agent Application
Agent Registration: Your application must be registered as an "Agent" in the Piper system. During registration, you will receive:
A Client ID.
A Client Secret Name (the name of the secret in Piper's Google Secret Manager where your agent's actual client secret value is stored).
You will also define the logical Variable Names your agent uses.
GCP Permissions for Your Agent: Your agent application's runtime environment (e.g., its service account if running on GCP, or Application Default Credentials for local development) needs IAM permission to access its own client secret from Piper's Google Secret Manager. This typically means the secretmanager.secretAccessor role on the specific secret resource (e.g., projects/PIPER_PROJECT_ID/secrets/agent-secret-YOUR_AGENT_CLIENT_ID/versions/latest).
End-User Setup: Your end-users will need to:
Have a Piper account.
Install and run the Piper Link application on their local machine (instructions provided separately by Piper).
Go to their Piper dashboard to grant your agent permission to access their specific secrets using the variable names you defined.
SDK Usage
import os
import logging
from pyper_sdk.client import PiperClient, PiperConfigError, PiperAuthError, PiperLinkNeededError
from google.cloud import secretmanager # To fetch the actual secret using the STS token

# --- Configuration for Your Agent ---
# These should be securely managed by your application
AGENT_CLIENT_ID = os.environ.get("MY_AGENT_PIPER_CLIENT_ID")
# Name of the secret in Piper's GCP project holding YOUR agent's client_secret
AGENT_CLIENT_SECRET_NAME_IN_PIPER_SM = os.environ.get("MY_AGENT_PIPER_CLIENT_SECRET_NAME")
PIPER_PROJECT_ID = os.environ.get("PIPER_SYSTEM_PROJECT_ID", "444535882337") # Piper's GCP Project ID

# --- Logging Setup (Recommended) ---
logging.basicConfig(level=logging.INFO) # Use logging.DEBUG for verbose SDK logs
sdk_logger = logging.getLogger('PiperSDK')
sdk_logger.setLevel(logging.INFO) # Or logging.DEBUG
logging.getLogger('urllib3').setLevel(logging.WARNING)

def fetch_agent_client_secret_from_piper_sm(piper_gcp_project_id: str, secret_name: str) -> str:
    """
    Helper function for your agent to fetch ITS OWN client_secret from Piper's SM.
    Your agent's runtime identity needs 'secretmanager.secretAccessor' permission
    on this specific secret in Piper's GCP project.
    """
    try:
        sm_client = secretmanager.SecretManagerServiceClient()
        full_secret_name = f"projects/{piper_gcp_project_id}/secrets/{secret_name}/versions/latest"
        response = sm_client.access_secret_version(request={"name": full_secret_name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        logging.error(f"Failed to fetch agent client secret '{secret_name}' from Piper's Secret Manager: {e}", exc_info=True)
        raise PiperConfigError(f"Could not fetch agent client secret '{secret_name}'. Ensure your agent's GCP identity has permission.") from e

def fetch_actual_secret_using_sts(sts_token: str, piper_credential_id: str, piper_gcp_project_id: str) -> str:
    """
    Helper function to use the Piper-issued STS token to get the actual secret
    value from Piper's Secret Manager.
    """
    from google.oauth2 import credentials # Local import
    
    logging.info(f"Attempting to fetch actual secret for Piper CredID: {piper_credential_id} using STS token.")
    try:
        # The Piper CredID is the name of the secret in Secret Manager where the user's value is stored
        # (This assumes a naming convention like user-{userId}-cred-{credentialId} or just the credentialId)
        # For this example, we'll assume piper_credential_id IS the secret name or part of it.
        # You may need to adjust the secret_resource_name based on Piper's internal SM naming for user secrets.
        # This is a placeholder - the actual secret name in SM might be different.
        # The STS token allows acting as piper-functions-sa which has access.
        secret_resource_name = f"projects/{piper_gcp_project_id}/secrets/{piper_credential_id}/versions/latest"
        # It's more likely that piper_credential_id is the *Piper system's internal ID* for the secret,
        # and the piper-functions-sa uses *this* ID to look up the actual SM path.
        # The crucial part is the STS token allows calling SM as piper-functions-sa.

        # For this example to directly work, the STS token's identity (piper-functions-sa)
        # needs direct access to a secret named piper_credential_id.
        # In reality, the STS token allows your agent to call a GCP API (like SM)
        # AS the piper-functions-sa. That SA then has granular access.
        
        # Construct temporary credentials using the STS token
        temp_gcp_creds = credentials.Credentials(token=sts_token)
        sm_client = secretmanager.SecretManagerServiceClient(credentials=temp_gcp_creds)
        
        # This is a simplified example; the actual secret name construction might be more complex
        # and depend on information not directly available in the STS response.
        # Often, the STS token is used with Piper's OWN GCFs that then access the secret.
        # For direct SM access by agent: the agent needs to know the SM secret name.
        # Let's assume for now `piper_credential_id` IS the SM secret ID (or a direct part of its path).
        
        # A more realistic flow IF Piper provided the full SM path or if the credentialId was the SM name:
        # full_secret_version_name = f"projects/{piper_gcp_project_id}/secrets/{piper_credential_id}/versions/latest"
        # logging.debug(f"Accessing Secret Manager version: {full_secret_version_name}")
        # response = sm_client.access_secret_version(name=full_secret_version_name)
        # actual_secret_value = response.payload.data.decode("UTF-8")
        # logging.info(f"Successfully fetched actual secret value for {piper_credential_id}.")
        # return actual_secret_value
        
        # Since agents don't know the internal SM path of user secrets, this function
        # is more illustrative. The STS token is meant to be used with Google Cloud client libraries
        # for services piper-functions-sa has access to.
        # For getting the secret value itself, usually an agent would call a Piper endpoint
        # that takes the STS token and returns the secret value (if Piper vends raw secrets).
        # If Piper ONLY vends STS for calling *other* GCP services, then that's the flow.
        # For now, we'll just simulate that the STS token IS the secret for demo purposes.
        logging.warning("fetch_actual_secret_using_sts is illustrative. The STS token is for calling GCP APIs.")
        logging.warning(f"The 'value' from get_secret (if source=piper_sts) IS the STS token itself: ...{sts_token[-6:]}")
        return f"SIMULATED_SECRET_FOR_{piper_credential_id}_USING_STS_TOKEN"

    except Exception as e:
        logging.error(f"Failed to fetch actual secret using STS token for {piper_credential_id}: {e}", exc_info=True)
        raise PiperError(f"Could not fetch actual secret value using STS token for {piper_credential_id}.") from e


if __name__ == "__main__":
    if not AGENT_CLIENT_ID or not AGENT_CLIENT_SECRET_NAME_IN_PIPER_SM:
        print("FATAL: MY_AGENT_PIPER_CLIENT_ID and MY_AGENT_PIPER_CLIENT_SECRET_NAME env vars must be set.")
        exit(1)

    try:
        print("Fetching agent's own client_secret from Piper's Secret Manager...")
        agent_client_secret_value = fetch_agent_client_secret_from_piper_sm(
            PIPER_PROJECT_ID,
            AGENT_CLIENT_SECRET_NAME_IN_PIPER_SM
        )
        print("Successfully fetched agent's client_secret.")

        print(f"\nInitializing PiperClient for agent: {AGENT_CLIENT_ID[:8]}...")
        piper_client = PiperClient(
            client_id=AGENT_CLIENT_ID,
            client_secret=agent_client_secret_value,
            project_id=PIPER_PROJECT_ID, # Pass Piper's project ID if different from SDK default
            # enable_env_fallback=True, # Default is True
            # env_variable_prefix="MY_APP_", # Example
            # env_variable_map={"PiperVarName": "MY_EXACT_ENV_VAR"} # Example
        )
        print("PiperClient initialized.")

        # --- Example 1: Get a secret, relying on Piper Link and Piper grant ---
        # Setup needed: User has run Piper Link. User has granted this agent
        # access to "MyGmailVar" in Piper UI, mapping it to their Gmail secret.
        # Environment variable "MY_APP_MYGMAILVAR" is NOT set.
        gmail_variable_name = "MyGmailVar" # Variable name defined by your agent
        print(f"\n--- Attempting to get secret for Piper Variable: '{gmail_variable_name}' ---")
        try:
            secret_info_gmail = piper_client.get_secret(gmail_variable_name)
            print(f"Successfully retrieved for '{gmail_variable_name}':")
            print(f"  Source: {secret_info_gmail.get('source')}")
            if secret_info_gmail.get('source') == 'piper_sts':
                print(f"  STS Token (last 6): ...{secret_info_gmail.get('value', '')[-6:]}")
                # actual_gmail_secret = fetch_actual_secret_using_sts(
                #     secret_info_gmail['value'],
                #     secret_info_gmail['piper_credential_id'],
                #     PIPER_PROJECT_ID
                # )
                # print(f"  Actual Gmail Secret (simulated, last 6): ...{actual_gmail_secret[-6:]}")
            elif secret_info_gmail.get('source') == 'environment_variable':
                print(f"  Value (from env, last 6): ...{secret_info_gmail.get('value', '')[-6:]}")

        except PiperLinkNeededError:
            print(f"ERROR: Piper Link is not set up. Please ask the user to run the Piper Link application.")
        except PiperAuthError as e:
            if e.error_code == 'mapping_not_found':
                print(f"ERROR: User has not granted this agent access to the variable '{gmail_variable_name}' in Piper.")
                print(f"       Please ask the user to go to their Piper dashboard and grant access.")
            else:
                print(f"ERROR: Piper authentication/authorization error: {e}")
        except PiperConfigError as e:
            print(f"ERROR: SDK Configuration Error: {e}")


        # --- Example 2: Get a secret, Piper grant missing, fallback to env var ---
        # Setup needed: User has run Piper Link. User has NOT granted access to "MyOpenAIVar".
        # Environment variable "MY_APP_MYOPENAIVAR" IS set.
        openai_variable_name = "MyOpenAIVar"
        fallback_openai_env_var = f"{piper_client.env_variable_prefix}{openai_variable_name.upper().replace(' ', '_')}"
        # For this test, temporarily set the env var if not already set by user for testing
        # In a real app, you wouldn't do this, you'd just let it fail or succeed based on user's env.
        print(f"\n--- Attempting to get secret for Piper Variable: '{openai_variable_name}' (expecting fallback) ---")
        print(f"    (Ensuring env var '{fallback_openai_env_var}' is set for this test)")
        os.environ[fallback_openai_env_var] = "env_openai_secret_value_for_test"
        
        try:
            secret_info_openai = piper_client.get_secret(openai_variable_name)
            print(f"Successfully retrieved for '{openai_variable_name}':")
            print(f"  Source: {secret_info_openai.get('source')}")
            if secret_info_openai.get('source') == 'piper_sts':
                print(f"  STS Token (last 6): ...{secret_info_openai.get('value', '')[-6:]}")
            elif secret_info_openai.get('source') == 'environment_variable':
                print(f"  Value (from env, last 6): ...{secret_info_openai.get('value', '')[-6:]}")
                print(f"  Env Var Name: {secret_info_openai.get('env_var_name')}")
        
        except Exception as e: # Catch-all for this example
            print(f"Error getting secret for '{openai_variable_name}': {e}")
        finally:
            if fallback_openai_env_var in os.environ:
                del os.environ[fallback_openai_env_var] # Clean up env var

    except PiperConfigError as e:
        print(f"FATAL SDK/Agent Setup Error: {e}")
    except Exception as e:
        print(f"An unexpected fatal error occurred: {e}", exc_info=True)
Use code with caution.
Python
Error Handling
The primary method piper_client.get_secret() can raise several exceptions:
ValueError: If variable_name is invalid.
PiperLinkNeededError: If the Piper Link application is not running or configured, and Piper access is attempted. Your application should catch this and guide the user to set up Piper Link.
PiperAuthError: If there's an issue with Piper:
error_code='mapping_not_found': The user has not granted your agent access to this variable in their Piper dashboard.
error_code='permission_denied': The grant exists, but some other permission check failed (e.g., Firestore grant status not "ACTIVE" for the underlying credential).
Other codes for invalid_client (agent's own client_id/secret issue), invalid_token, etc.
The exception object contains status_code, error_code, and error_details from the API.
PiperConfigError: If Piper access fails for other configuration reasons, AND environment variable fallback is disabled or also fails. The message will indicate both failures.
Always wrap calls to get_secret() in try...except blocks to handle these cases gracefully.
How Environment Variable Fallback Works
The PiperClient can be configured with fallback behavior:
enable_env_fallback: bool (in __init__, defaults to True): If True, get_secret() will attempt to read from an environment variable if the Piper flow fails (e.g., PiperLinkNeededError, mapping_not_found, permission_denied).
env_variable_prefix: str (in __init__, defaults to ""): If fallback is enabled and no exact map is found, the SDK will construct an environment variable name by:
Taking the variable_name passed to get_secret().
Converting it to UPPERCASE.
Replacing spaces and hyphens with underscores (_).
Prepending your env_variable_prefix.
Example: variable_name="My API Key", env_variable_prefix="MYAPP_" -> SDK looks for MYAPP_MY_API_KEY.
Example: variable_name="My API Key", env_variable_prefix="" -> SDK looks for MY_API_KEY.
env_variable_map: Dict[str, str] (in __init__): Provides an exact mapping.
Example: env_variable_map={"My API Key": "MY_APPS_SPECIFIC_API_KEY_ENV_NAME"}.
The SDK will look for MY_APPS_SPECIFIC_API_KEY_ENV_NAME if get_secret("My API Key") is called. This map takes precedence over the prefix logic.
get_secret() parameters:
enable_env_fallback_for_this_call: Optional[bool]: Overrides the client's default for a single call.
fallback_env_var_name: Optional[str]: Explicitly specifies the environment variable to check for this call, overriding map/prefix.
The get_secret() method returns a dictionary indicating the source ("piper_sts" or "environment_variable") and the value. If from environment, value is the raw secret. If from Piper, value is the STS token.
Development & Contributing
(Standard contribution section - optional)
License
MIT License