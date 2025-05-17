
# 🛡️ Pyper SDK: Simple & Secure Access to User-Approved Secrets

**Empower your Python applications to securely use your users' API keys and credentials — without the risk or hassle of handling raw secrets directly.**

---

## ✨ Why Pyper SDK?

- **🔐 Offload Secret Management**  
  Let the Piper system handle user secrets like OpenAI keys, Notion tokens, and database credentials. No need to store or manage them yourself.

- **🛡️ Enhance Trust & Security**  
  Users explicitly grant your app permission via their Piper dashboard. Secrets are accessed securely with temporary tokens or encrypted raw secrets.

- **💡 Clean Developer Experience**  
  A simple and powerful API (`PiperClient` and `get_secret()`) makes integration a breeze.

- **🔄 Smart Context Handling**  
  Supports automatic local context detection via the Piper Link desktop app and external context IDs for remote services.

- **🧩 Progressive Adoption**  
  Built-in environment variable fallback ensures functionality for users not yet using Piper.

---

## 🔁 Core Flow

### 1. **User Setup (Handled by Piper)**

- Users store secrets in their Piper account.
- They grant your app ("Agent") permission to access specific secrets, mapped to logical names.
- For local usage, users run the **Piper Link** app to securely share context.

### 2. **App Flow (Using Pyper SDK)**

- Initialize `PiperClient` with your `client_id` and `client_secret`.
- Request secrets using logical variable names your app expects.
- Receive either:
  - 🔁 **STS token** (`piper_sts`) — secure, indirect access.
  - 🔓 **Raw secret** (`piper_raw_secret`) — if explicitly requested.

---

## 🚀 Installation

```bash
pip install pyper-sdk
```

> Requires **Python 3.8+**

---

## 🛠️ Getting Started

### 1. **Register Your App**

Create an Agent on [Piper Console](https://agentpiper.com). You'll receive:

- `AGENT_CLIENT_ID`
- `AGENT_CLIENT_SECRET` (store securely)

---

### 2. **Initialize `PiperClient`**

```python
import os
from piper_sdk.client import PiperClient, PiperConfigError

AGENT_CLIENT_ID = os.environ.get("MY_AGENT_CLIENT_ID")
AGENT_CLIENT_SECRET = os.environ.get("MY_AGENT_CLIENT_SECRET")
EXCHANGE_SECRET_URL = os.environ.get("PIPER_EXCHANGE_URL")

try:
    piper_client = PiperClient(
        client_id=AGENT_CLIENT_ID,
        client_secret=AGENT_CLIENT_SECRET,
        exchange_secret_url=EXCHANGE_SECRET_URL  # Optional, for raw secrets
    )
    print("PiperClient ready.")
except PiperConfigError as e:
    print(f"Configuration error: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

---

### 3. **Request Secrets**

```python
if piper_client:
    try:
        secret_info = piper_client.get_secret("DATABASE_PASSWORD", fetch_raw_secret=True)

        if secret_info.get("source") == "piper_raw_secret":
            db_password = secret_info["value"]
            print("Retrieved raw secret via Piper.")

        elif secret_info.get("source") == "environment_variable":
            db_password = secret_info["value"]
            print(f"Fallback to environment variable: {secret_info['env_var_name_found']}")

    except PiperLinkNeededError:
        print("⚠️ Piper Link is not running. Please start the desktop app.")
    except PiperGrantNeededError as e:
        print(f"Permission needed for secret: {e}")
    except PiperRawSecretExchangeError as e:
        print(f"Exchange error: {e}")
    except PiperAuthError as e:
        print(f"Auth error: {e}")
    except PiperError as e:
        print(f"Piper SDK error: {e}")
    except Exception as e:
        print(f"Unknown error: {e}")
```

---

## 🌐 User Context (`instanceId`)

- **Local (Auto)**: Piper Link provides context automatically.
- **Remote (Manual)**: Supply your own `instanceId`:

```python
piper_client = PiperClient(
    client_id=AGENT_CLIENT_ID,
    client_secret=AGENT_CLIENT_SECRET,
    piper_link_instance_id="ctx_id_from_platform",
    auto_discover_instance_id=False,
    exchange_secret_url=EXCHANGE_SECRET_URL
)
```

---

## 🌱 Environment Variable Fallback

If secrets can't be retrieved via Piper, the SDK will fall back to environment variables (enabled by default).

You can configure:

- `env_variable_prefix`
- `env_variable_map`
- or use `fallback_env_var_name` in `get_secret()`

Return will include `"source": "environment_variable"`.

---

## 🧯 Error Handling

Exception hierarchy:

- `PiperError` (base)
  - `PiperConfigError`
  - `PiperLinkNeededError`
  - `PiperAuthError`
    - `PiperGrantNeededError`
    - `PiperForbiddenError`
  - `PiperRawSecretExchangeError`

Use `try...except` to gracefully handle errors and guide users.

---

## 🎯 Our Mission

**Pyper SDK** is built to make secure, user-consented access to credentials effortless for developers — and safer for users — in a world of growing AI and data integrations.

---

## 🤝 Contributing

Found a bug or have a feature request?  
Please open an issue or PR at [GitHub → Pyper SDK](https://github.com/greylab0/piper-python-sdk)

---

## License

MIT License