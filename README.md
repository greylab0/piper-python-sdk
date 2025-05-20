# 🛡️ Pyper SDK: Simple, Secure, & Flexible Access to User-Approved Secrets

Empower your Python applications to securely use your users' API keys and credentials — with user consent at the core, and minimal hassle for you. Pyper SDK intelligently handles secret retrieval from multiple sources, so you can focus on building your app.

✨ **Why Pyper SDK?**

*   🔐 **Offload Secret Management:** Let the Piper system (when enabled by the user) securely store and manage user secrets like OpenAI keys, Notion tokens, and database credentials.
*   🛡️ **Enhance Trust & Security:** Users explicitly grant your app permission via their Piper dashboard for specific secrets. The SDK primarily aims to vend short-lived tokens for services that support them, with an option for securely exchanging for raw secrets when necessary. The agent's own credentials (like its client secret) are managed on the Piper backend, never needing to be handled or stored by the client-side SDK.
*   💡 **Simplified Developer Experience:** A clean API (`PiperClient` and `get_secret()`) with intelligent, configurable, multi-tiered secret acquisition makes integration straightforward.
*   🔄 **Flexible Context Handling:** Supports automatic local context detection via the Piper Link desktop app (for users interacting directly) and explicit context IDs for remote or non-interactive services.
*   🧩 **Graceful Fallbacks:** Built-in, configurable fallbacks to environment variables and local agent configuration files ensure your application remains functional even if Piper is not used or encounters an issue. The SDK manages this complexity.

🔁 **Core Flow (with Pyper SDK v0.6.0+)**

1.  **User Setup (Handled by Piper System, if used):**
    *   Users store their secrets (e.g., API keys) in their secure Piper account.
    *   Through the Piper interface, users grant your application ("Agent") permission to access specific secrets, which your application will request by a logical variable name (e.g., "NOTION_API_KEY").
    *   For applications running on the user's desktop, the Piper Link app can provide the necessary local context to the SDK automatically.

2.  **Your Application Flow (Using Pyper SDK):**
    *   **Initialize `PiperClient`:** Configure it once with your agent's `client_id` and how you want it to acquire secrets (Piper first? Environment variables? Local config file?).
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
            )
            print("PiperClient ready.")
        except PiperConfigError as e:
            print(f"SDK Configuration Error: {e}")
            # Handle error: agent might exit or prompt for manual config
        except Exception as e: # Catch any other unexpected error during init
            print(f"Unexpected error initializing PiperClient: {e}")

        ```
    *   **Request Secrets:** Simply call `piper.get_secret("YOUR_VARIABLE_NAME")`. The SDK intelligently tries the configured sources in order:
        1.  Piper System (if `use_piper=True`)
        2.  Environment Variables (if `fallback_to_env=True` and Piper skipped or failed)
        3.  Local Agent Configuration File (if `fallback_to_local_config=True` and previous tiers skipped or failed)
    *   **Receive Secret Info:** If successful, `get_secret()` returns a dictionary containing the secret `value` and its `source` (e.g., `"piper_sts"`, `"piper_raw_secret"`, `"environment_variable"`, `"local_config_file"`).
        ```python
        # Assuming piper client was initialized successfully
        if 'piper' in locals() and piper:
            try:
                api_key_info = piper.get_secret("OPENAI_API_KEY") # Tries Piper, then Env, then Local Config (if enabled)
                api_key = api_key_info['value']
                print(f"Got OpenAI API Key from: {api_key_info['source']}")

                # Example: Requesting a raw secret specifically (e.g., a database password)
                db_pass_info = piper.get_secret("DATABASE_PASSWORD", fetch_raw_secret=True)
                db_password = db_pass_info['value']
                print(f"Got DB Password from: {db_pass_info['source']}")

            except PiperSecretAcquisitionError as e:
                print(f"ERROR: Could not acquire secret for '{e.variable_name}'.")
                print("Attempted sources and reasons for failure:")
                # e.g. PiperSecretAcquisitionError's __str__ method gives a nice summary:
                # Failed to retrieve secret for 'OPENAI_API_KEY' after trying all configured methods.
                # Primary Issue (Piper): Grant needed for OPENAI_API_KEY. Visit https://agentpiper.com/secrets?....
                # Details of all attempts:
                #   - Piper: (See primary issue above)
                #   - EnvironmentVariable: Environment variable 'MY_AGENT_OPENAI_KEY' not set.
                #   - LocalConfigFile (~/.my_agent_secrets.json): File not found.
                print(e)
                # Your agent can then guide the user based on the most actionable error,
                # e.g., if e.attempted_sources_summary.get("Piper") is a PiperGrantNeededError,
                # you can prominently display e.attempted_sources_summary["Piper"].constructed_grant_url

            except Exception as e:
                print(f"An unexpected error occurred during secret retrieval: {e}")
        ```

🚀 **Installation**
```bash
pip install pyper-sdk
```

Requires Python 3.7+

🛠️ Complete PiperClient Configuration

The PiperClient can be initialized with the following parameters to fine-tune its behavior:

- client_id: str: (Required) Your agent's client ID from the Piper Console. This is now the sole identifier for your agent that the SDK needs.
- use_piper: bool (default: True): Whether to attempt secret retrieval via the Piper system.
- piper_link_instance_id: Optional[str] (default: None): An explicit Piper Link instanceId. If provided, local discovery is skipped.
- attempt_local_discovery: bool (default: True): If use_piper is True and no instanceId is provided, automatically discover Piper Link GUI at http://localhost:31477.
- fallback_to_env: bool (default: True): Fallback to environment variables if Piper tier fails.
- env_variable_prefix: str (default: ""): Prefix for environment variable names.
- env_variable_map: Optional[Dict[str, str]]: Custom mapping from logical names to environment variable names.
- fallback_to_local_config: bool (default: False): Fallback to a local JSON file if prior tiers fail.
- local_config_file_path: Optional[str]: Path to local JSON config file.
- piper_ui_grant_page_url: Optional[str]: Base URL for constructing grant links.
- exchange_secret_url: Optional[str]: URL for raw secret exchange service.

🌐 User Context (instanceId) for Piper Tier

- **Explicitly Provided:** Pass `piper_link_instance_id` in constructor (highest precedence).
- **Automatic Local Discovery:** If no explicit ID and `attempt_local_discovery=True`, the SDK queries the Piper Link GUI's local endpoint.

🧯 **Error Handling**

All secret-retrieval failures raise `PiperSecretAcquisitionError`, which includes:
- `variable_name`: The name of the variable that failed.
- `attempted_sources_summary`: Mapping of source names to specific errors (e.g., `PiperGrantNeededError`, `FileNotFoundError`).

Additional errors may include `PiperLinkNeededError`, `PiperConfigError`, `PiperAuthError`, and `PiperRawSecretExchangeError`.

🤝 **Contributing**

Please open an issue or PR on GitHub → `https://github.com/agentpiper/pyper-sdk`.

License: MIT License