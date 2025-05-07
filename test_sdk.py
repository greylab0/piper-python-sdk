# test_sdk.py
import os
import logging
from piper_sdk.client import PiperClient, PiperAuthError, PiperConfigError

# NEW: Import Secret Manager client
from google.cloud import secretmanager
from google.api_core import exceptions as google_exceptions # To catch SM errors

# Configure logging
logging.basicConfig(level=logging.DEBUG) # Use DEBUG to see detailed SDK logs
logging.getLogger('urllib3').setLevel(logging.WARNING) # Silence noisy library logs

print("--- Reading Configuration from Environment Variables ---")
CLIENT_ID = os.environ.get("PIPER_CLIENT_ID")
USER_ID = os.environ.get("PIPER_USER_ID")
PROJECT_ID = os.environ.get("PIPER_PROJECT_ID") # Reads None if not set
REGION = os.environ.get("PIPER_REGION")       # Reads None if not set

# Define how to find the secret in Secret Manager
SECRET_MANAGER_PROJECT_ID = PROJECT_ID or PiperClient.DEFAULT_PROJECT_ID # Assume secret is in same project
SECRET_ID = f"agent-secret-{CLIENT_ID}" # Use the confirmed naming convention
SECRET_VERSION = "latest"

if not CLIENT_ID:
    print("FATAL ERROR: PIPER_CLIENT_ID environment variable must be set.")
    exit(1)
if not USER_ID:
    print("FATAL ERROR: PIPER_USER_ID environment variable must be set.")
    exit(1)

print(f"Using Client ID: {CLIENT_ID}")
print(f"Using User ID: {USER_ID}")

# Fetch Client Secret from Secret Manager
CLIENT_SECRET_VALUE = None
try:
    print(f"\n--- Fetching Client Secret from Secret Manager ---")
    print(f" Secret Project: {SECRET_MANAGER_PROJECT_ID}")
    print(f" Secret ID: {SECRET_ID}")
    print(f" Secret Version: {SECRET_VERSION}")

    sm_client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{SECRET_MANAGER_PROJECT_ID}/secrets/{SECRET_ID}/versions/{SECRET_VERSION}"
    response = sm_client.access_secret_version(request={"name": name})
    CLIENT_SECRET_VALUE = response.payload.data.decode("UTF-8")
    print("Successfully fetched client secret from Secret Manager.")

except google_exceptions.NotFound:
     print(f"FATAL ERROR: Secret version not found in Secret Manager: {name}")
     print(" Verify the naming convention and that the secret exists and is enabled.")
     exit(1)
except google_exceptions.PermissionDenied:
     print(f"FATAL ERROR: Permission denied accessing Secret Manager secret: {name}")
     print(" Ensure the environment's GCP credentials (e.g., service account) have the 'Secret Manager Secret Accessor' role.")
     exit(1)
except Exception as sm_error:
    print(f"FATAL ERROR: Failed to fetch secret from Secret Manager: {sm_error}")
    exit(1)

if not CLIENT_SECRET_VALUE:
     print("FATAL ERROR: Client secret value could not be fetched or was empty.")
     exit(1)


print("\n--- Initializing Piper Client ---")
try:
    piper_client = PiperClient(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET_VALUE, # Use the fetched value
        project_id=PROJECT_ID,
        region=REGION
    )
    print("PiperClient initialized successfully.")

except (PiperConfigError, ValueError) as e:
    print(f"FATAL ERROR: Failed to initialize client: {e}")
    exit(1)
except Exception as e:
    print(f"FATAL ERROR: Unexpected error during client initialization: {e}")
    exit(1)


# ************************************************************
# *** THIS IS THE PART THAT WAS MISSING OR COMMENTED OUT *****
# ************************************************************
print("\n--- Testing get_scoped_credentials_for_variable ---")
# *** CHANGE THIS to a variable name you KNOW is mapped for the test USER_ID ***
variable_to_fetch = "Gmail key"
print(f"Attempting to get credentials for variable: '{variable_to_fetch}' for user: {USER_ID}")

try:
    sts_credentials = piper_client.get_scoped_credentials_for_variable(
        variable_name=variable_to_fetch,
        user_id=USER_ID
    )
    print("\nSuccessfully received STS credentials response:")
    print(f" Granted IDs: {sts_credentials.get('granted_credential_ids')}")
    print(f" Expires In: {sts_credentials.get('expires_in')}")
    print(f" Token Type: {sts_credentials.get('token_type')}")
    print(f" Access Token: {sts_credentials.get('access_token', '')[:15]}...") # Show only start of token

except PiperAuthError as e:
    print(f"\nSDK Authentication/Authorization Error: {e}")
    print(f" Status Code: {e.status_code}")
    print(f" Error Code: {e.error_code}")
    print(f" Details: {e.error_details}")
    if e.error_code == 'invalid_client':
         print(" ---> NOTE: 'invalid_client' likely means the secret fetched by this script")
         print("      does NOT match the secret fetched by the /token endpoint backend.")
         print("      Verify the Secret Manager secret names and values match on both sides.")
except PiperConfigError as e:
     print(f"\nSDK Configuration Error: {e}")
except ValueError as e:
    print(f"\nSDK Value Error: {e}")
except Exception as e:
    print(f"\nUnexpected Error during credential fetch: {e}")

# ************************************************************
# ***************** END OF MISSING PART **********************
# ************************************************************

print("\n--- Test Script Finished ---")