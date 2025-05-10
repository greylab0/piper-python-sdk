# test_sdk_v2.py
import os
import logging
import sys # For sys.path printing if needed (can be removed if not debugging path)

# Ensure the SDK is installed from your latest Git changes for this to work
from piper_sdk.client import PiperClient, PiperConfigError, PiperAuthError, PiperLinkNeededError

# --- Test Configuration ---
# Functional Agent that uses pyper-sdk
AGENT_CLIENT_ID = os.environ.get("PIPER_TEST_AGENT_CLIENT_ID")
AGENT_CLIENT_SECRET = os.environ.get("PIPER_TEST_AGENT_CLIENT_SECRET") # Raw secret for this agent

# Piper Variables to test (these are the logical names your agent uses)
PIPER_VAR_GMAIL = "gmail_key"  # Note: Case sensitive as it's passed to Piper
PIPER_VAR_OPENAI = "open_ai_key" # Using uppercase to test normalization
PIPER_VAR_DATABASE = "database_pass" # Using uppercase for consistency

# Distinct Environment Variables for each fallback test case
# These are the exact names the SDK will look for based on variable_name and prefix/map
ENV_VAR_FALLBACK_GMAIL_CASE1_DEFAULT = "GMAIL_KEY" # Default, empty prefix, "Gmail key" -> "GMAIL_KEY"
ENV_VAR_FALLBACK_OPENAI_CASE2_MAPPED = "SDK_TEST_OPENAI_KEY_MAPPED" # Used in client_exact_map
ENV_VAR_FALLBACK_DATABASE_CASE3_PREFIXED = "SDK_TEST_DATABASE_PASSWORD" # Used with client_prefix_sdk_test
ENV_VAR_FALLBACK_OPENAI_CASE4_MYAPP = "MYAPP_OPENAI_API_KEY" # Used with client_custom_prefix_myapp

# Logging Setup
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - TEST_SDK - %(levelname)s - %(message)s')
sdk_logger = logging.getLogger('PiperSDK')
sdk_logger.setLevel(logging.DEBUG) # Set SDK to DEBUG for verbose output
logging.getLogger('urllib3').setLevel(logging.INFO) # Quieten urllib3

def get_and_print_secret(client_name: str, piper_client_instance: PiperClient, piper_variable_name: str):
    print(f"\n--- [{client_name}] Attempting to get secret for Piper Variable: '{piper_variable_name}' ---")
    try:
        secret_info = piper_client_instance.get_secret(
            piper_variable_name,
            # instance_id=None, # Let SDK discover by default
            # enable_env_fallback_for_this_call=True, # Using client's default
            # fallback_env_var_name=None # Using client's default construction or map
        )

        print(f"Successfully retrieved for '{piper_variable_name}':")
        print(f"  Source: {secret_info.get('source')}")
        print(f"  Value (last 6 chars): ...{secret_info.get('value', '')[-6:]}")
        if secret_info.get('source') == 'piper_sts':
            print(f"  Token Type: {secret_info.get('token_type')}")
            print(f"  Expires In: {secret_info.get('expires_in')}")
            print(f"  Piper CredID: {secret_info.get('piper_credential_id')}")
            print(f"  Instance ID Used: {secret_info.get('piper_instance_id')}")
        elif secret_info.get('source') == 'environment_variable':
            print(f"  Env Var Name Found: {secret_info.get('env_var_name')}")
        return secret_info.get('value')

    except PiperLinkNeededError as e:
        print(f"ERROR for '{piper_variable_name}' [{client_name}]: Piper Link setup is needed. {e}")
    except PiperConfigError as e:
        print(f"ERROR for '{piper_variable_name}' [{client_name}]: Configuration error or secret not found. {e}")
    except PiperAuthError as e:
        print(f"ERROR for '{piper_variable_name}' [{client_name}]: Piper Auth error. {e}")
        print(f"  Status: {e.status_code}, Code: {e.error_code}, Details: {e.error_details}")
    except Exception as e:
        # CORRECTED PRINT TO LOGGING
        logging.error(f"UNEXPECTED ERROR for '{piper_variable_name}' [{client_name}]: {e}", exc_info=True)
    return None

if __name__ == "__main__":
    print("--- Piper SDK Fallback Test Script (v2 - Corrected) ---")

    if not AGENT_CLIENT_ID or not AGENT_CLIENT_SECRET:
        print("FATAL: PIPER_TEST_AGENT_CLIENT_ID and PIPER_TEST_AGENT_CLIENT_SECRET env vars must be set.")
        exit(1)

    # --- Initial Client Initializations (done once, will cache instanceId if Link is running) ---
    print(f"\n--- Initializing PiperClient instances (Piper Link should be RUNNING now if testing discovery) ---")
    # Note: For tests involving Link NOT running, we will re-initialize the client AFTER stopping the link.

    client_default_prefix_initial = PiperClient(
        client_id=AGENT_CLIENT_ID, client_secret=AGENT_CLIENT_SECRET,
        enable_env_fallback=True, env_variable_prefix=""
    )
    print("Initial client_default_prefix_initial initialized.")

    client_custom_prefix_myapp_initial = PiperClient(
        client_id=AGENT_CLIENT_ID, client_secret=AGENT_CLIENT_SECRET,
        enable_env_fallback=True, env_variable_prefix="MYAPP_"
    )
    print("Initial client_custom_prefix_myapp_initial initialized.")

    client_exact_map_initial = PiperClient(
        client_id=AGENT_CLIENT_ID, client_secret=AGENT_CLIENT_SECRET,
        enable_env_fallback=True,
        env_variable_map={
            PIPER_VAR_GMAIL: ENV_VAR_FALLBACK_GMAIL_CASE1_DEFAULT, # "Gmail key" -> "GMAIL_KEY" (Normalized)
            PIPER_VAR_OPENAI: ENV_VAR_FALLBACK_OPENAI_CASE2_MAPPED, # "OPENAI_API_KEY" -> "SDK_TEST_OPENAI_KEY_MAPPED"
        }
    )
    print(f"Initial client_exact_map_initial initialized.")


    # ==================================================================================
    # TEST CASE 1: Piper success (Piper Link running, grant exists in Piper UI)
    # ==================================================================================
    print("\n\n--- TEST CASE 1: Piper Success (Ensure Piper Link IS RUNNING) ---")
    print("    Setup: 1. piper_link.py serve IS RUNNING in Terminal 1.")
    print(f"           2. User linked via piper_link.py has GRANTED agent '{AGENT_CLIENT_ID[:8]}...'")
    print(f"              access to a secret mapped to PIPER VARIABLE '{PIPER_VAR_GMAIL}' in Piper UI.")
    print(f"           3. Fallback ENV VAR for '{PIPER_VAR_GMAIL}' (e.g., '{ENV_VAR_FALLBACK_GMAIL_CASE1_DEFAULT}') is UNSET.")
    input("Press Enter to continue Test Case 1...")

    # Ensure fallback is not used
    if ENV_VAR_FALLBACK_GMAIL_CASE1_DEFAULT in os.environ: del os.environ[ENV_VAR_FALLBACK_GMAIL_CASE1_DEFAULT]
    
    # Use one of the initially created clients that would have discovered the instance ID
    get_and_print_secret("Client ExactMap (Case 1)", client_exact_map_initial, PIPER_VAR_GMAIL)


    # ==================================================================================
    # TEST CASE 2: Piper fails (e.g., mapping not found), fallback to ENV SUCCEEDS
    # ==================================================================================
    print("\n\n--- TEST CASE 2: Piper Fails (No Grant), Env Fallback Success (Piper Link IS RUNNING) ---")
    print("    Setup: 1. piper_link.py serve IS RUNNING in Terminal 1.")
    print(f"           2. Ensure NO GRANT exists in Piper UI for agent '{AGENT_CLIENT_ID[:8]}...'")
    print(f"              for PIPER VARIABLE '{PIPER_VAR_OPENAI}'.")
    print(f"           3. Fallback ENV VAR '{ENV_VAR_FALLBACK_OPENAI_CASE2_MAPPED}' IS SET.")
    input("Press Enter to continue Test Case 2...")

    os.environ[ENV_VAR_FALLBACK_OPENAI_CASE2_MAPPED] = "env_openai_for_case2_mapped_value"
    
    # Use one of the initially created clients
    get_and_print_secret("Client ExactMap (Case 2)", client_exact_map_initial, PIPER_VAR_OPENAI)
    del os.environ[ENV_VAR_FALLBACK_OPENAI_CASE2_MAPPED] # Cleanup


    # ==================================================================================
    # TEST CASE 3: Piper Link not running, fallback to ENV SUCCEEDS
    # ==================================================================================
    print("\n\n--- TEST CASE 3: Piper Link Not Running, Env Fallback Success ---")
    print(">>> Please STOP 'piper_link.py serve' in Terminal 1 for this test. <<<")
    input("Press Enter to continue Test Case 3 after stopping Piper Link service...")
    
    os.environ[ENV_VAR_FALLBACK_DATABASE_CASE3_PREFIXED] = "env_db_pass_for_case3_prefixed_value"
    
    # Re-initialize client AFTER link is stopped to test discovery failure
    client_for_case3_link_stopped = PiperClient(
        client_id=AGENT_CLIENT_ID, client_secret=AGENT_CLIENT_SECRET,
        enable_env_fallback=True, env_variable_prefix="SDK_TEST_",
        auto_discover_instance_id=True # Ensure it tries to discover
    )
    print("Client for Case 3 (link stopped) initialized.")
    # PIPER_VAR_DATABASE = "DATABASE_PASSWORD" -> SDK_TEST_DATABASE_PASSWORD
    get_and_print_secret("Client Prefix SDK_TEST_ (Case 3)", client_for_case3_link_stopped, PIPER_VAR_DATABASE)
    del os.environ[ENV_VAR_FALLBACK_DATABASE_CASE3_PREFIXED] # Cleanup


    # ==================================================================================
    # TEST CASE 4: Both Piper (Link not running) and ENV fallback Fail
    # ==================================================================================
    print("\n\n--- TEST CASE 4: Both Piper (Link Not Running) and Env Fallback Fail ---")
    print(">>> Ensure 'piper_link.py serve' is STILL STOPPED in Terminal 1. <<<")
    input("Press Enter to continue Test Case 4...")

    # Ensure no fallback env var exists for open_ai_key with "MYAPP_" prefix
    if ENV_VAR_FALLBACK_OPENAI_CASE4_MYAPP in os.environ: del os.environ[ENV_VAR_FALLBACK_OPENAI_CASE4_MYAPP]
    
    client_for_case4_link_stopped = PiperClient(
        client_id=AGENT_CLIENT_ID, client_secret=AGENT_CLIENT_SECRET,
        enable_env_fallback=True, env_variable_prefix="MYAPP_",
        auto_discover_instance_id=True
    )
    print("Client for Case 4 (link stopped) initialized.")
    # PIPER_VAR_OPENAI = "OPENAI_API_KEY" -> MYAPP_OPENAI_API_KEY
    get_and_print_secret("Client Prefix MYAPP_ (Case 4)", client_for_case4_link_stopped, PIPER_VAR_OPENAI)

    print("\n--- All Test Cases Finished ---")