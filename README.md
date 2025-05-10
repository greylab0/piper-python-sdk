
# Pyper SDK for Python

![Piper SDK](https://img.shields.io/badge/piper-sdk-blue)

The official Python SDK for integrating your applications (agents, MCPs, scripts) with **Piper**, the secure credential management system designed for the AI era.

> Stop asking your users to paste sensitive API keys directly into every tool! With Piper, users store their secrets once in a central, secure vault. Your application, using this SDK, can request temporary, scoped access to those secrets only after the user has explicitly granted permission via the Piper dashboard.

---

## Features

- Establish end-user's Piper context via Piper Link
- Authenticate your agent to the Piper system
- Request access to secrets via logical variable names
- Receive short-lived GCP STS tokens to fetch secrets from Google Secret Manager
- Optional fallback to environment variables

---

## 🚩 Problem Piper Solves

Modern AI agents and applications often require access to numerous sensitive user credentials (OpenAI keys, DB passwords, Slack tokens, etc.).

**Problems with the current approach:**

- 🔑 **Secret Sprawl**: Keys duplicated across tools
- 🔓 **Increased Attack Surface**: One weak link exposes everything
- 🔄 **Difficult Revocation**: Manually remove keys across tools
- 📉 **Lack of Control & Audit**: Users lose track of which tool has what

**Piper** solves this with centralized, user-controlled secret management.

---

## 🔧 How it Works

### For Users:

1. **Add Secrets in Piper Dashboard**  
2. **Install Piper Link** (CLI/desktop helper app)  
3. **Login via Piper Link** to establish local context  
4. **Grant Access** to agents in the Piper dashboard  

### For Developers:

1. **Register Agent** in Piper (define logical variable names)
2. **Use SDK in your app** to request secrets via those names
3. SDK retrieves:
    - Piper context (via Link)
    - GCP STS token (if permitted)
    - Actual secret from Google Secret Manager

If Piper fails, environment variable fallback (optional) is used.

---

## 📦 Installation

```bash
pip install pyper-sdk
```

---

## ✅ Prerequisites

### Agent Registration

- Client ID
- Client Secret Name (stored in Piper’s GCP Secret Manager)
- Logical Variable Names

---

## 🧑‍💻 SDK Usage

```python
import os
import logging
from pyper_sdk.client import PiperClient, PiperConfigError, PiperAuthError, PiperLinkNeededError
from google.cloud import secretmanager

AGENT_CLIENT_ID = os.environ.get("MY_AGENT_PIPER_CLIENT_ID")
AGENT_CLIENT_SECRET_NAME_IN_PIPER_SM = os.environ.get("MY_AGENT_PIPER_CLIENT_SECRET_NAME")
PIPER_PROJECT_ID = os.environ.get("PIPER_SYSTEM_PROJECT_ID", "444535882337")

logging.basicConfig(level=logging.INFO)
sdk_logger = logging.getLogger('PiperSDK')
sdk_logger.setLevel(logging.INFO)

def fetch_agent_client_secret_from_piper_sm(piper_gcp_project_id: str, secret_name: str) -> str:
    try:
        sm_client = secretmanager.SecretManagerServiceClient()
        full_secret_name = f"projects/{piper_gcp_project_id}/secrets/{secret_name}/versions/latest"
        response = sm_client.access_secret_version(request={"name": full_secret_name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        logging.error(f"Failed to fetch agent client secret '{secret_name}' from Piper's Secret Manager: {e}", exc_info=True)
        raise PiperConfigError(f"Could not fetch agent client secret '{secret_name}'.") from e
```

---

## 🔐 Getting a Secret

```python
piper_client = PiperClient(
    client_id=AGENT_CLIENT_ID,
    client_secret=fetch_agent_client_secret_from_piper_sm(PIPER_PROJECT_ID, AGENT_CLIENT_SECRET_NAME_IN_PIPER_SM),
    project_id=PIPER_PROJECT_ID
)

try:
    secret_info = piper_client.get_secret("MyGmailVar")
    print(f"Source: {secret_info.get('source')}")
    print(f"Value (last 6): ...{secret_info.get('value', '')[-6:]}")
except PiperLinkNeededError:
    print("ERROR: Piper Link is not set up.")
except PiperAuthError as e:
    print(f"ERROR: Piper authentication error: {e}")
except PiperConfigError as e:
    print(f"ERROR: SDK Configuration Error: {e}")
```

---

## 🔁 Fallback to Environment Variable

```python
os.environ["MY_APP_MYOPENAIVAR"] = "env_secret_value"

secret_info = piper_client.get_secret("MyOpenAIVar")
print(f"Source: {secret_info.get('source')}")
print(f"Value: {secret_info.get('value')}")
```

---

## 🧠 Error Handling

`get_secret()` may raise:

- `ValueError`: Invalid variable
- `PiperLinkNeededError`: Piper Link not running
- `PiperAuthError`: Grant or permission issue
- `PiperConfigError`: Config error, env fallback fails

Always use try/except blocks to catch these.

---

## 🧪 Env Var Fallback Options

### Client init options

```python
PiperClient(
    enable_env_fallback=True,
    env_variable_prefix="MY_APP_",
    env_variable_map={"My API Key": "MY_CUSTOM_ENV_VAR"}
)
```

### Overrides

```python
get_secret("My API Key", enable_env_fallback_for_this_call=True, fallback_env_var_name="MY_API_KEY_OVERRIDE")
```

---

## 📄 License

MIT