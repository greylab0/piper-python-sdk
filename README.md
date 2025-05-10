# Pyper SDK for Python

![Pyper Logo](https://your-logo-url.com) <!-- Replace with actual logo image URL -->

The **official Python SDK** for integrating your applications (agents, MCPs, scripts) with **Piper**, the secure credential management system designed for the AI era.

> ❗ Stop asking users to paste sensitive API keys directly into every tool!  
> With Piper, secrets are stored once in a central, secure vault, and applications can request temporary, scoped access—**only with user permission**.

---

## 🔑 What This SDK Does

This SDK simplifies your agent's integration with Piper by enabling it to:

- Establish the end-user's Piper context (via **Piper Link**).
- Authenticate your application with Piper.
- Request secrets using logical variable names.
- Receive short-lived **GCP STS tokens** to retrieve secrets from **Google Secret Manager**.
- Optionally fall back to environment variables if Piper is unavailable.

---

## 🚨 Core Problem Piper Solves

Modern AI apps need access to user credentials (e.g., OpenAI keys, DB passwords, Slack tokens). Asking users to paste these credentials:

- ❌ Creates **Secret Sprawl**
- ❌ Increases **Attack Surface**
- ❌ Makes **Revocation Difficult**
- ❌ Lacks **Audit & Control**

**✅ Piper** provides centralized, user-controlled secret access.

---

## 🧩 How It Works

### 1. **End-User Setup**
- Adds secrets (e.g., “My OpenAI Key”) via **Piper dashboard**.
- Piper stores secrets securely in **Google Secret Manager**.
- Installs **Piper Link** and performs a one-time login (creates `instanceId`).

### 2. **Developer Setup**
- Register your agent (`MyCoolAgent`) in Piper:
  - Define logical variable names (e.g., `openai_api_token`)
  - Receive `client_id` and `client_secret_name`

### 3. **User Grants Access**
- User maps their secret to the variable name your agent uses in the Piper UI.

### 4. **Your App Uses the SDK**
- Call `get_secret("openai_api_token")`
- Piper authenticates the agent and user
- Returns short-lived **STS token**
- Your agent uses this token to fetch the actual secret from GCP

### 5. **Fallback Option (Optional)**
- If Piper isn't available, the SDK can fall back to environment variables.

---

## 📦 Installation

```bash
pip install pyper-sdk


✅ Prerequisites
For Your Agent
Agent must be registered with Piper:

client_id

client_secret_name

Define logical variable names

Runtime must have IAM access to your agent’s secret:

GCP Role: secretmanager.secretAccessor

For End Users
Piper account

Install and run Piper Link

Grant your agent access via Piper dashboard

🧪 Example Usage
python
Copy
Edit
import os
import logging
from pyper_sdk.client import PiperClient, PiperConfigError, PiperAuthError, PiperLinkNeededError
from google.cloud import secretmanager

# Configuration
AGENT_CLIENT_ID = os.environ.get("MY_AGENT_PIPER_CLIENT_ID")
AGENT_CLIENT_SECRET_NAME_IN_PIPER_SM = os.environ.get("MY_AGENT_PIPER_CLIENT_SECRET_NAME")
PIPER_PROJECT_ID = os.environ.get("PIPER_SYSTEM_PROJECT_ID", "444535882337")

# Logging
logging.basicConfig(level=logging.INFO)
sdk_logger = logging.getLogger('PiperSDK')
sdk_logger.setLevel(logging.INFO)

# Fetch your agent's client secret
def fetch_agent_client_secret_from_piper_sm(piper_gcp_project_id, secret_name):
    try:
        sm_client = secretmanager.SecretManagerServiceClient()
        full_name = f"projects/{piper_gcp_project_id}/secrets/{secret_name}/versions/latest"
        response = sm_client.access_secret_version(request={"name": full_name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        raise PiperConfigError(f"Could not fetch client secret: {e}") from e

# Initialize the Piper Client
agent_client_secret_value = fetch_agent_client_secret_from_piper_sm(
    PIPER_PROJECT_ID, AGENT_CLIENT_SECRET_NAME_IN_PIPER_SM
)
piper_client = PiperClient(
    client_id=AGENT_CLIENT_ID,
    client_secret=agent_client_secret_value,
    project_id=PIPER_PROJECT_ID,
)

# Get a secret from Piper
try:
    result = piper_client.get_secret("MyGmailVar")
    print("Source:", result["source"])
    print("Value (last 6 chars):", result["value"][-6:])
except PiperLinkNeededError:
    print("Piper Link is not running.")
except PiperAuthError as e:
    print(f"Piper authorization error: {e}")
🔁 Environment Variable Fallback
If Piper access fails, the SDK can fall back to env vars:

python
Copy
Edit
piper_client = PiperClient(
    client_id=...,
    client_secret=...,
    enable_env_fallback=True,
    env_variable_prefix="MY_APP_",
    env_variable_map={"MyGmailVar": "MY_GMAIL_SECRET_ENV_VAR"}
)
Fallback lookup order:

env_variable_map (exact match)

env_variable_prefix + UPPERCASE(variable_name)

⚠️ Error Handling
get_secret() may raise:

ValueError: Invalid variable name

PiperLinkNeededError: Piper Link not running

PiperAuthError: Authorization issue

PiperConfigError: Configuration or fallback failure

Always wrap in try...except.

🧑‍💻 Development & Contributing
Standard PR and issue process. Contributions welcome.

🪪 License
MIT License