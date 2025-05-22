# 🛡️ Pyper SDK: Simple, Secure, & Flexible Access to User-Approved Secrets

Empower your Python applications to securely use your users' API keys and credentials — with user consent at the core, and minimal hassle for you. Pyper SDK intelligently handles secret retrieval from multiple sources, so you can focus on building your app.

✨ **Why Pyper SDK?**

*   🔐 **Offload Secret Management:** Let the Piper system (when enabled by the user) securely store and manage user secrets like OpenAI keys, Notion tokens, and database credentials.

*   🛡️ **Enhance Trust & Security:** Users explicitly grant your app permission via their Piper dashboard for specific secrets. The SDK primarily aims to vend short-lived tokens for services that support them, with an option for securely exchanging for raw secrets when necessary. The agent's own credentials (like its client secret) are managed on the Piper backend, never needing to be handled or stored by the client-side SDK.

*   💡 **Simplified Developer Experience:** A clean API (`PiperClient` and `get_secret()`) with intelligent, configurable, multi-tiered secret acquisition makes integration straightforward.

*   🔄 **Flexible Context Handling:** Supports automatic local context detection via the Piper Link desktop app (for users interacting directly) and explicit context IDs for remote or non-interactive services.

*   🧩 **Graceful Fallbacks & User Guidance (Enhanced in v0.7.0):**
    *   Built-in, configurable fallbacks to environment variables and local agent configuration files ensure your application remains functional even if Piper is not used or encounters an issue.
    *   **New in v0.7.0:** The SDK now enables more resilient applications by allowing non-raising secret acquisition and provides methods to generate user-friendly, actionable advice to help users resolve configuration problems (like missing grants or disconnected Piper Link).

🔁 **Core Flow (with Pyper SDK v0.7.0+)**

1.  **User Setup (Handled by Piper System, if used):**
    *   Users store their secrets (e.g., API keys) in their secure Piper account.

    *   Through the Piper interface (e.g., at `https://agentpiper.com/secrets`), users grant your application ("Agent") permission to access specific secrets, which your application will request by a logical variable name (e.g., "NOTION_API_KEY").

    *   For applications running on the user's desktop, the Piper Link app can provide the necessary local context to the SDK automatically.

2.  **Your Application Flow (Using Pyper SDK):**
    *   **Initialize `PiperClient`:** Configure it once with your agent's `client_id` and your preferred secret acquisition strategy. You can also check if the client initialized correctly.
        
      ```python
        from piper_sdk import PiperClient, PiperSecretAcquisitionError, PiperConfigError
        import os # For environment variable example

        try:
            piper = PiperClient(
                client_id="YOUR_AGENT_CLIENT_ID", # Only client_id is needed now!
                
                # Configure your preferred acquisition strategy:
                use_piper=True,                      # Attempt to use Piper system (default: True)
                attempt_local_discovery=True,        # If use_piper=True, try to find Piper Link GUI (default: True)
                # piper_link_instance_id=os.environ.get("PIPER_INSTANCE_ID_HOST_PROVIDED"), # Optional explicit instance_id

                fallback_to_env=True,                # Fallback to OS environment variables (default: True)
                # env_variable_prefix="MY_AGENT_",   # Optional prefix for env vars
                # env_variable_map={"NOTION_API_KEY": "AGENT_NOTION_KEY"}, # Optional custom mapping

                fallback_to_local_config=False,      # Fallback to a local JSON config file (default: False)
                # local_config_file_path="~/.my_agent_secrets.json" # Path if local config fallback is enabled
                
                # piper_ui_grant_page_url="https://your.piper-ui.com/grants" # Optional: Override default grant page URL
            )
            
            if piper.client_initialization_ok:
                print("PiperClient ready.")
            else:
                print("ERROR: PiperClient did not initialize correctly. Cannot fetch secrets reliably.")
                # Get advice for the initialization error (v0.7.0+)
                init_advice = piper.get_resolution_advice("") # Empty var_name for init errors
                if init_advice:
                    print("\nClient Initialization Problem:\n", init_advice)
                # Agent might decide to exit or operate in a limited mode.

        except Exception as e: # Catch any other unexpected error during init (though most config errors are now stored)
            print(f"Unexpected critical error initializing PiperClient: {e}")
            # This is for truly unexpected issues, not regular config validation handled by client_initialization_ok
    ```
    *   **Request Secrets:** Call `piper.get_secret("YOUR_VARIABLE_NAME")`. The SDK intelligently tries the configured sources in order:
        1.  Piper System (if `use_piper=True`)

        2.  Environment Variables (if `fallback_to_env=True` and Piper skipped or failed)

        3.  Local Agent Configuration File (if `fallback_to_local_config=True` and previous tiers skipped or failed)

    *   **Handle Secret Info or Failures (v0.7.0+):**

        ```python
        # Assuming piper client was initialized successfully (piper.client_initialization_ok was True)
        if 'piper' in locals() and piper and piper.client_initialization_ok:
            
            # --- Option 1: Default raising behavior (good for critical secrets at startup) ---
            try:
                api_key_info = piper.get_secret("CRITICAL_API_KEY") 
                api_key = api_key_info['value']
                print(f"Got CRITICAL_API_KEY from: {api_key_info['source']}")
                # Use the api_key
            except PiperSecretAcquisitionError as e:
                print(f"CRITICAL ERROR: Could not acquire secret for '{e.variable_name}'. Agent might need to exit or limit functionality.")
                # str(e) is very informative for logs:
                print("Detailed Error:\n", e) 
                
                # For more user-friendly advice (v0.7.0+):
                advice = piper.get_resolution_advice(e.variable_name, error_object=e)
                if advice:
                    print("\nUser Advice to resolve CRITICAL_API_KEY issue:\n", advice)
                    # You might present this advice to the user or log it for support.
            except PiperConfigError as e: 
                 print(f"CRITICAL SDK CONFIG ERROR during get_secret: {e}")


            # --- Option 2: Non-raising behavior (good for non-critical secrets or deferring errors - v0.7.0+) ---
            db_pass_info = piper.get_secret("DATABASE_PASSWORD", fetch_raw_secret=True, raise_on_failure=False)
            
            if db_pass_info and db_pass_info.get("value"):
                db_password = db_pass_info['value']
                print(f"Got DB Password from: {db_pass_info['source']}")
                # Use db_password
            else:
                # Secret not found, or another error occurred. db_pass_info contains details.
                print(f"WARNING: Could not acquire DATABASE_PASSWORD (non-critical).")
                if db_pass_info and db_pass_info.get("error_object"):
                    # The error_object is the actual PiperError instance
                    error_for_db_pass = db_pass_info['error_object'] 
                    # print(f"  Error details for dev: {error_for_db_pass}") # For logging
                    
                    # Generate user-friendly advice. This is typically done when the user
                    # attempts an action that *requires* DATABASE_PASSWORD.
                    advice = piper.get_resolution_advice("DATABASE_PASSWORD", error_object=error_for_db_pass)
                    if advice:
                        print("\nGuidance for DATABASE_PASSWORD issue (if user tries to use related feature):\n", advice)
                        # In a real app, an LLM or UI would present this advice at the point of need.
                else:
                    print("  Could not determine specific reason for DATABASE_PASSWORD failure from SDK (no error object found).")
        ```

✨ **Graceful Startup & User Guidance (New in v0.7.0)**

Pyper SDK v0.7.0 introduces powerful features to help your application start up smoothly even if secrets aren't immediately available, and to provide clear, actionable guidance to your users:

*   ✅ **Non-Raising Secret Acquisition:** The `piper.get_secret()` method now accepts a `raise_on_failure=False` parameter. When set, instead of raising an exception, it returns a detailed dictionary upon failure, allowing your application to continue running and handle the missing secret gracefully (e.g., at the point a feature requiring it is used).

*   🗣️ **Actionable User Advice:** A new method, `piper.get_resolution_advice(variable_name, error_object?)`, intelligently inspects acquisition failures (or client initialization errors) and generates user-friendly, multi-line advice. This helps users understand *why* a secret is missing (e.g., "Grant needed," "Piper Link not connected," "Environment variable not set") and *how* to fix it, often providing direct links to the Piper UI.

*   🔍 **Inspectable Initialization:** `PiperClient` now has a `client_initialization_ok` (bool) attribute. After creating the client, check this attribute. If `False`, critical configuration errors occurred (e.g., missing `client_id`). You can use `piper.get_resolution_advice("")` (with an empty variable name) for guidance on client setup issues.

This enables you to build a more resilient and user-friendly experience, deferring error handling until a secret is actually needed and then guiding the user effectively.

🚀 **Installation**
```bash
pip install pyper-sdk
```

Requires Python 3.7+

🛠️ **Complete `PiperClient` Configuration**

The `PiperClient` can be initialized with the following parameters to fine-tune its behavior. Most parameters have sensible defaults.

*   `client_id: str`: **(Required)** Your agent's client ID obtained from the Piper Console. This is the primary identifier for your agent.

*   `use_piper: bool` (default: `True`): Whether to attempt secret retrieval via the Piper system. If `False`, the SDK will only try configured fallback methods.

*   `piper_link_instance_id: Optional[str]` (default: `None`): An explicit Piper Link `instanceId` provided by the host environment. If you provide this, the SDK will use it for Piper operations and skip local discovery for this specific ID.

*   `attempt_local_discovery: bool` (default: `True`): If `use_piper` is `True` and no explicit `piper_link_instance_id` is active for a call (either from constructor or `get_secret`), the SDK will attempt to discover a running Piper Link application on the local machine (typically at `http://localhost:31477`) to get an `instanceId`. Set to `False` to disable this automatic discovery.

*   `fallback_to_env: bool` (default: `True`): If the Piper tier is skipped or fails, setting this to `True` enables the SDK to attempt to retrieve the secret from OS environment variables.

*   `env_variable_prefix: str` (default: `""`): An optional prefix for environment variable names. For example, if `variable_name` is "API\_KEY" and `env_variable_prefix` is "MYAPP\_", the SDK will look for "MYAPP\_API\_KEY".

*   `env_variable_map: Optional[Dict[str, str]]` (default: `None`): For more control over environment variable names, provide a dictionary mapping your logical `variable_name` (e.g., "DATABASE\_USER") to the exact environment variable name you want the SDK to check (e.g., `{"DATABASE_USER": "CUSTOM_APP_DB_USER_ENV"}`). This map takes precedence over the `env_variable_prefix` and default normalization for the mapped names.

*   `fallback_to_local_config: bool` (default: `False`): If prior tiers (Piper, Environment Variables) are skipped or fail, setting this to `True` enables the SDK to attempt to retrieve the secret from a local JSON configuration file.

*   `local_config_file_path: Optional[str]` (default: `None`): **Required if `fallback_to_local_config` is `True`**. Specifies the absolute or user-expanded path (e.g., `"~/.my_agent/secrets.json"`) to the local secrets file. The file should be a flat JSON object where keys are the logical variable names.

*   `piper_ui_grant_page_url: Optional[str]` (default: `"https://agentpiper.com/secrets"`): The base URL of your Piper system's UI page where users manage grants. The SDK uses this to construct helpful deep links (e.g., in `PiperGrantNeededError` and `get_resolution_advice`) to guide users if a grant is missing.

*   `requests_session: Optional[requests.Session]` (default: `None`): Allows advanced users to provide a custom `requests.Session` object. This can be useful for custom SSL configurations, proxies, or default headers for all SDK's HTTP requests. Most users will not need this.

**(Note:** For developers needing to point the SDK at alternative backend service URLs for testing or specialized deployments, additional override parameters are available in the `PiperClient` constructor. These are not typically needed for general use and can be found by inspecting the `PiperClient.__init__` signature in the source code.)

**Key `PiperClient` Attributes & Methods (v0.7.0+):**

*   `piper.client_initialization_ok: bool`: (Read-only attribute) After `PiperClient(...)`, check this. `True` if critical configurations were met, `False` otherwise (e.g., missing `client_id`).

*   `piper.get_secret(variable_name: str, piper_link_instance_id_for_call: Optional[str] = None, fetch_raw_secret: bool = False, raise_on_failure: bool = True) -> Optional[Dict[str, Any]]`:
    The primary method to retrieve secrets. See examples above.
*   `piper.get_last_error_for_variable(variable_name: str) -> Optional[PiperError]`:
    If `get_secret` was called with `raise_on_failure=False` and an error occurred for `variable_name`, this method retrieves that stored `PiperError` object. Returns `None` if no error is stored.
*   `piper.get_resolution_advice(variable_name: str, error_object: Optional[PiperError] = None) -> Optional[str]`:
    Generates a user-friendly, multi-line string with actionable advice for resolving secret acquisition or client initialization issues.
    - If `error_object` is provided, it generates advice for that error.
    - Else, if `variable_name` is provided, it uses `get_last_error_for_variable(variable_name)`.
    - Else (e.g., if `variable_name` is `""`), it uses any stored client initialization error.
    Returns `None` if no relevant error is found.

🌐 **User Context (`instanceId`) for Piper Tier**

When using the Piper system, a user context (`instanceId`) is needed:

*   **Explicitly Provided:** Pass `piper_link_instance_id` in the `PiperClient` constructor (highest precedence for client-wide default) or to a specific `get_secret(..., piper_link_instance_id_for_call=...)` call (overrides client default for that call). This is useful for services or when the context is known externally.

*   **Automatic Local Discovery:** If no explicit `instanceId` is active for a call, and `attempt_local_discovery=True` (default), the SDK queries the Piper Link GUI's local endpoint (typically `http://localhost:31477/piper-link-context`) to get the current `instanceId`. This is ideal for desktop applications where the user interacts with Piper Link.

🧯 **Error Handling (Enhanced in v0.7.0)**

The SDK provides robust error information:

*   **`get_secret(..., raise_on_failure=True)` (Default Behavior):**
    *   All secret-retrieval failures from any tier raise `PiperSecretAcquisitionError`. This error includes:
        *   `variable_name`: The name of the variable that failed.
        *   `attempted_sources_summary`: A dictionary mapping source names (e.g., "Piper", "EnvironmentVariable", "LocalConfigFile") to specific errors or failure messages (e.g., a `PiperGrantNeededError` object, a string like "Environment variable 'X' not set", or a `FileNotFoundError`). Its `__str__` method provides a comprehensive summary ideal for logging.

    *   Other errors like `PiperConfigError` (for SDK setup issues found during a call) or more specific `PiperAuthError` subtypes might be raised directly from the Piper tier if they occur before all tiers are exhausted.

*   **`get_secret(..., raise_on_failure=False)` (New in v0.7.0):**
    *   If an error occurs (client initialization issue passed down, configuration problem during the call, or secret acquisition failure across tiers), this mode does *not* raise an exception.
    
    *   Instead, it returns a dictionary containing details about the failure, including an `error_object` key holding the actual `PiperError` instance (e.g., `PiperSecretAcquisitionError`, `PiperConfigError`). The dictionary also includes `value: None`, `source` (e.g., "client\_initialization\_failure", "piper\_grant\_needed"), and `variable_name`.

    *   The error is also stored internally and can be retrieved using `piper.get_last_error_for_variable(variable_name)`.

*   **`get_resolution_advice(variable_name, error_object?)` (New in v0.7.0):**
    *   Use this method to convert an error object into a user-friendly, actionable string. This is the **recommended way to generate messages for your users** when `get_secret` (non-raising) indicates a failure, or if `piper.client_initialization_ok` is `False`.

**Key Error Types you might interact with:**
- `PiperConfigError`: Issues with how `PiperClient` is configured or invalid inputs to its methods.

- `PiperLinkNeededError`: Piper Link context (`instanceId`) is required for a Piper tier operation but is missing.

- `PiperGrantNeededError`: User needs to grant permission in the Piper UI for the requested variable. Contains a `constructed_grant_url` attribute with a direct link for the user (e.g., `https://agentpiper.com/secrets?response_type=code&scope=manage_grants&client=YOUR_AGENT_ID&variable=REQUESTED_VAR_NAME`).

- `PiperAuthError` / `PiperForbiddenError`: Authentication or permission issues with the Piper backend services.

- `PiperRawSecretExchangeError`: Errors specific to the raw secret exchange step if `fetch_raw_secret=True`.

- `PiperSecretAcquisitionError`: The umbrella error when `get_secret` (in raising mode) fails after trying all configured tiers, or the `error_object` returned by non-raising `get_secret` if all tiers fail.

🤝 **Contributing**

Please open an issue or PR on GitHub → `https://github.com/greylab0/piper-python-sdk`.

License: MIT License
