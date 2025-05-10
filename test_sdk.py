# test_sdk_v2.py
import os
import logging
# Ensure the SDK is installed from your latest Git changes for this to work
from piper_sdk.client import PiperClient, PiperConfigError, PiperAuthError, PiperLinkNeededError

# --- Test Configuration ---
# Functional Agent that uses pyper-sdk
AGENT_CLIENT_ID = os.environ.get("PIPER_TEST_AGENT_CLIENT_ID")
AGENT_CLIENT_SECRET = os.environ.get("PIPER_TEST_AGENT_CLIENT_SECRET") # Raw secret for this agent

# Piper Variables to test
PIPER_VAR_GMAIL = "Gmail key"
PIPER_VAR_OPENAI = "OPENAI_API_KEY" # Example, may not exist in your Piper setup
PIPER_VAR_DATABASE = "DATABASE_PASSWORD"

# Corresponding Environment Variables for Fallback
# These names will be derived by the SDK if prefix is used, or can be exact if map is used
ENV_VAR_GMAIL_FALLBACK = "PYPER_SDK_TEST_GMAIL_KEY" # Example
ENV_VAR_OPENAI_FALLBACK = "PYPER_SDK_TEST_OPENAI_API_KEY"
ENV_VAR_DATABASE_FALLBACK = "PYPER_SDK_TEST_DATABASE_PASSWORD"

# Logging Setup
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - TEST_SDK - %(levelname)s - %(message)s')
sdk_logger = logging.getLogger('PiperSDK')
sdk_logger.setLevel(logging.DEBUG) # Set SDK to DEBUG for verbose output
logging.getLogger('urllib3').setLevel(logging.INFO) # Quieten urllib3

def get_and_print_secret(piper_client_instance, piper_variable_name, expected_env_var_name=None):
    print(f"\n--- Attempting to get secret for Piper Variable: '{piper_variable_name}' ---")
    try:
        secret_info = piper_client_instance.get_secret(
            piper_variable_name,
            # instance_id=None, # Let SDK discover
            # enable_env_fallback_for_this_call=True, # Test client's default
            # fallback_env_var_name=expected_env_var_name # Test client's default construction or map
        )

        print(f"Successfully retrieved for '{piper_variable_name}':")
        print(f"  Source: {secret_info.get('source')}")
        print(f"  Value: ...{secret_info.get('value', '')[-6:]}") # Show last 6 chars for demo
        if secret_info.get('source') == 'piper_sts':
            print(f"  Token Type: {secret_info.get('token_type')}")
            print(f"  Expires In: {secret_info.get('expires_in')}")
            print(f"  Piper CredID: {secret_info.get('piper_credential_id')}")
            print(f"  Instance ID Used: {secret_info.get('piper_instance_id')}")
            # Here, you would typically use the STS token (secret_info['value'])
            # with google-cloud-secret-manager to fetch the actual secret.
            # print("  (Next step would be to use this STS token to fetch from GCP Secret Manager)")
        elif secret_info.get('source') == 'environment_variable':
            print(f"  Env Var Name: {secret_info.get('env_var_name')}")
            # Here, secret_info['value'] IS the raw secret
            # print("  (This is the raw secret value from the environment variable)")
        return secret_info.get('value')

    except PiperLinkNeededError as e:
        print(f"ERROR for '{piper_variable_name}': Piper Link setup is needed. {e}")
    except PiperConfigError as e: # Catches if both Piper and fallback fail
        print(f"ERROR for '{piper_variable_name}': Configuration error or secret not found. {e}")
    except PiperAuthError as e: # Should ideally be caught within get_secret for fallback
        print(f"ERROR for '{piper_variable_name}': Piper Auth error. {e}")
    except Exception as e:
        print(f"UNEXPECTED ERROR for '{piper_variable_name}': {e}", exc_info=True)
    return None

if __name__ == "__main__":
    print("--- Piper SDK Fallback Test Script ---")

    if not AGENT_CLIENT_ID or not AGENT_CLIENT_SECRET:
        print("FATAL: PIPER_TEST_AGENT_CLIENT_ID and PIPER_TEST_AGENT_CLIENT_SECRET env vars must be set.")
        exit(1)

    # --- Scenario Setup ---
    # To test different scenarios, you'll need to:
    # 1. Have piper_link.py serve running (for Piper success cases) or NOT running (for LinkNeededError).
    # 2. In Piper UI (Bubble), grant/revoke access for the AGENT_CLIENT_ID to secrets mapped to PIPER_VAR_...
    #    for the user linked via piper_link.py.
    # 3. Set/unset the corresponding ENV_VAR_..._FALLBACK environment variables.

    print(f"\nInitializing PiperClient for agent: {AGENT_CLIENT_ID[:8]}...")
    # Test with default fallback prefix (empty)
    # SDK will look for env vars like "GMAIL_KEY", "OPENAI_API_KEY"
    client_default_prefix = PiperClient(
        client_id=AGENT_CLIENT_ID,
        client_secret=AGENT_CLIENT_SECRET,
        enable_env_fallback=True,
        env_variable_prefix="" # Default: uses normalized variable_name
    )
    print("Client with default prefix initialized.")

    # Test with a custom fallback prefix
    client_custom_prefix = PiperClient(
        client_id=AGENT_CLIENT_ID,
        client_secret=AGENT_CLIENT_SECRET,
        enable_env_fallback=True,
        env_variable_prefix="MYAPP_" # SDK will look for "MYAPP_GMAIL_KEY", etc.
    )
    print("Client with custom prefix 'MYAPP_' initialized.")

    # Test with an exact environment variable map
    client_exact_map = PiperClient(
        client_id=AGENT_CLIENT_ID,
        client_secret=AGENT_CLIENT_SECRET,
        enable_env_fallback=True,
        env_variable_map={
            PIPER_VAR_GMAIL: ENV_VAR_GMAIL_FALLBACK, # "Gmail key" -> "PYPER_SDK_TEST_GMAIL_KEY"
            PIPER_VAR_OPENAI: "MY_OWN_OAI_KEY" # Example of different mapping
        }
    )
    print(f"Client with exact map initialized (e.g., '{PIPER_VAR_GMAIL}' maps to '{ENV_VAR_GMAIL_FALLBACK}').")


    # --- Test Case 1: Piper success (Piper Link running, grant exists in Piper UI) ---
    # Setup: Ensure piper_link.py serve is running.
    #        Ensure user linked via piper_link.py has granted AGENT_CLIENT_ID access
    #        to a secret mapped to PIPER_VAR_GMAIL in Piper UI.
    #        UNSET os.environ[ENV_VAR_GMAIL_FALLBACK] to ensure it's not using fallback
    print("\n\n--- TEST CASE 1: Piper Success ---")
    if ENV_VAR_GMAIL_FALLBACK in os.environ: del os.environ[ENV_VAR_GMAIL_FALLBACK]
    get_and_print_secret(client_exact_map, PIPER_VAR_GMAIL) # Using client with exact map

    # --- Test Case 2: Piper fails (e.g., mapping not found), fallback to ENV SUCCEEDS ---
    # Setup: Ensure piper_link.py serve is running.
    #        Ensure NO grant exists for PIPER_VAR_OPENAI for AGENT_CLIENT_ID in Piper UI.
    #        SET os.environ[ENV_VAR_OPENAI_FALLBACK] = "env_openai_key_123"
    print("\n\n--- TEST CASE 2: Piper Fails (No Grant), Env Fallback Success ---")
    os.environ[ENV_VAR_OPENAI_FALLBACK] = "env_openai_key_123_from_test_script"
    get_and_print_secret(client_exact_map, PIPER_VAR_OPENAI, expected_env_var_name="MY_OWN_OAI_KEY") # Uses map
    del os.environ[ENV_VAR_OPENAI_FALLBACK] # Cleanup env var

    # --- Test Case 3: Piper Link not running, fallback to ENV SUCCEEDS ---
    # Setup: STOP piper_link.py serve.
    #        SET os.environ[ENV_VAR_DATABASE_FALLBACK] = "env_db_pass_456"
    print("\n\n--- TEST CASE 3: Piper Link Not Running, Env Fallback Success ---")
    print(">>> Please STOP 'piper_link.py serve' in Terminal 1 for this test, then press Enter here <<<")
    input("Press Enter to continue after stopping Piper Link service...")
    os.environ[ENV_VAR_DATABASE_FALLBACK] = "env_db_pass_456_from_test_script"
    # Using client_default_prefix, expecting fallback to "DATABASE_PASSWORD" env var
    get_and_print_secret(client_default_prefix, PIPER_VAR_DATABASE)
    del os.environ[ENV_VAR_DATABASE_FALLBACK] # Cleanup

    # --- Test Case 4: Both Piper and ENV fail ---
    # Setup: STOP piper_link.py serve (if not already).
    #        Ensure NO grant exists for PIPER_VAR_OPENAI.
    #        UNSET os.environ[ENV_VAR_OPENAI_FALLBACK].
    print("\n\n--- TEST CASE 4: Both Piper and Env Fallback Fail ---")
    print(">>> Ensure 'piper_link.py serve' is STOPPED in Terminal 1 for this test. Press Enter. <<<")
    input("Press Enter to continue...")
    if "MY_OWN_OAI_KEY" in os.environ: del os.environ["MY_OWN_OAI_KEY"] # From exact map test
    # Using client_custom_prefix, expecting fallback to "MYAPP_OPENAI_API_KEY"
    get_and_print_secret(client_custom_prefix, PIPER_VAR_OPENAI)

    print("\n--- All Test Cases Finished ---")