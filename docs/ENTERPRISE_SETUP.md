# MARS-NewsLetter — Enterprise Setup Guide

This guide covers production deployment of the MARS-NewsLetter application for
enterprise environments. It assumes you have already cloned the repository and
have Python 3.11+ and Node.js 18+ available.

---

## Table of Contents

1. [Supported LLM Providers](#1-supported-llm-providers)
2. [How the Pipeline Picks a Model](#2-how-the-pipeline-picks-a-model)
3. [Azure OpenAI Onboarding](#3-azure-openai-onboarding-step-by-step)
4. [AWS Bedrock Onboarding](#4-aws-bedrock-onboarding-step-by-step)
5. [Enterprise Gateway Onboarding](#5-enterprise-gateway-onboarding)
6. [Multi-Tenant / Shared Deployment](#6-multi-tenant--shared-deployment)
7. [Production Hardening](#7-production-hardening)
8. [Environment Variable Reference Table](#8-environment-variable-reference-table)

---

## 1. Supported LLM Providers

MARS-NewsLetter delegates all LLM calls to **mars_cmbagent** (PyPI package
`mars-cmbagent`, imported as `cmbagent`). The application auto-detects which
provider to use from environment variables. Configure exactly one provider block
in `backend/.env`; the optional `CMBAGENT_LLM_PROVIDER` variable lets you pin a
specific provider when more than one set of credentials is present.

### 1.1 OpenAI (Direct API)

Suitable for teams with an OpenAI organization account.

```bash
# backend/.env
OPENAI_API_KEY=sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890AbCdEfGhIj
```

The application uses `gpt-4o` as the automatic default when this key is the
only credential present.

---

### 1.2 Anthropic Claude (Direct API)

```bash
# backend/.env
ANTHROPIC_API_KEY=sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890-AbCdEfGh-AAAA
```

When only the Anthropic key is present, the pipeline defaults to
`claude-3-5-sonnet-20241022`.

---

### 1.3 Azure OpenAI

Azure OpenAI requires an endpoint, a deployment name, and an API key. The
`AZURE_OPENAI_API_VERSION` field is optional but must match a version that your
Azure resource supports; `2024-12-01-preview` works for GPT-4o deployments
created in 2024 or later.

```bash
# backend/.env
AZURE_OPENAI_API_KEY=7a3b5c1d2e4f6g8h9i0j1k2l3m4n5o6p
AZURE_OPENAI_ENDPOINT=https://mycompany-openai.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=my-gpt4o-deployment
AZURE_OPENAI_API_VERSION=2024-12-01-preview
AZURE_OPENAI_VERIFY_SSL=true
```

When these three variables are set, the dispatcher automatically computes the
LiteLLM model string `azure/<deployment-name>` and injects it into every
cmbagent role that has not been explicitly overridden at runtime.

The application also sets the LiteLLM environment aliases
(`AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION`) at startup so LiteLLM
and the OpenAI SDK both resolve the same endpoint.

---

### 1.4 AWS Bedrock

AWS Bedrock supports Claude (Anthropic), Amazon Nova, and Meta Llama models.
Two authentication paths are supported:

**Path A — IAM Instance Profile (recommended for EC2 / ECS / EKS)**

Leave all `AWS_*` credential variables blank. The boto3 credential chain
picks up the instance profile automatically.

```bash
# backend/.env
AWS_DEFAULT_REGION=us-east-1
# AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are intentionally omitted
```

**Path B — Static Access Key Pair**

```bash
# backend/.env
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_DEFAULT_REGION=us-east-1
# AWS_SESSION_TOKEN is required only for assumed-role or temporary credentials
AWS_SESSION_TOKEN=
```

To select a specific Bedrock model, set `NEWSLETTER_DEFAULT_MODEL` (see
[Section 2](#2-how-the-pipeline-picks-a-model)) or per-stage model overrides in
the UI. Example Bedrock model identifiers understood by LiteLLM:

```
bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0
bedrock/anthropic.claude-3-haiku-20240307-v1:0
bedrock/amazon.nova-pro-v1:0
bedrock/meta.llama3-70b-instruct-v1:0
```

---

### 1.5 Google Gemini

```bash
# backend/.env
GOOGLE_API_KEY=AIzaSyAbCdEfGhIjKlMnOpQrStUvWxYz1234567
# Alias also read by KeyManager:
GEMINI_API_KEY=AIzaSyAbCdEfGhIjKlMnOpQrStUvWxYz1234567
```

Note: cmbagent's internal KeyManager reads `GEMINI_API_KEY` first and falls
back to `GOOGLE_API_KEY`. Set both to the same value to avoid silent mismatches.

---

### 1.6 Mistral (Direct API)

```bash
# backend/.env
MISTRAL_API_KEY=AbCdEfGhIjKlMnOpQrStUvWxYz1234567890abcd
```

---

### 1.7 Enterprise Gateway

For organizations that route all LLM traffic through an internal
OpenAI-wire-compatible gateway with a multi-stage OAuth2 authentication flow.
Full onboarding details are in [Section 5](#5-enterprise-gateway-onboarding).

```bash
# backend/.env — minimal activation block
CMBAGENT_LLM_PROVIDER=enterprise_gateway
ENTERPRISE_LLM_TOKEN_URL=https://idp.mycompany.com/oauth2/token
ENTERPRISE_LLM_GRANT_TYPE=client_credentials
ENTERPRISE_LLM_CLIENT_ID=newsletter-svc-client
ENTERPRISE_LLM_PASSWORD=s3cr3tC1i3ntS3cr3t
ENTERPRISE_LLM_GATEWAY_BASE_URL=https://llm-gateway.mycompany.com/v1/
ENTERPRISE_LLM_DEFAULT_MODEL=gpt-4o
```

---

## 2. How the Pipeline Picks a Model

The pipeline uses a three-level resolution order. The first non-empty value in
the chain wins for each agent role:

```
Per-stage model override (UI)
        ↓
NEWSLETTER_DEFAULT_MODEL  (env var)
        ↓
Auto-detected provider default
```

**Level 1 — Per-stage UI override**

Each of Stages 2–5 exposes model fields in the Setup form:
`researcher_model`, `engineer_model`, `planner_model`, `plan_reviewer_model`,
`web_surfer_model`, `formatter_model`, and `orchestration_model`. Any field
left blank falls through to the next level.

**Level 2 — `NEWSLETTER_DEFAULT_MODEL`**

Set this variable to pin every un-overridden agent role to a single model for
the entire pipeline run:

```bash
# backend/.env

# Use a specific Azure deployment for every stage:
NEWSLETTER_DEFAULT_MODEL=azure/my-gpt4o-deployment

# Use a Bedrock model for every stage:
NEWSLETTER_DEFAULT_MODEL=bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0

# Use OpenAI GPT-4.1 for every stage:
NEWSLETTER_DEFAULT_MODEL=gpt-4.1
```

This is the recommended way to enforce a single model across a shared
deployment without editing any code.

**Level 3 — Auto-detected provider default**

When no override is present, the dispatcher inspects available credentials in
the following priority order and selects the model string shown:

| Priority | Credentials present | Auto-selected model |
|----------|--------------------|--------------------|
| 1 | `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_DEPLOYMENT` | `azure/<deployment>` |
| 2 | `OPENAI_API_KEY` | `gpt-4o` |
| 3 | `ANTHROPIC_API_KEY` | `claude-3-5-sonnet-20241022` |
| 4 | _(none of the above)_ | cmbagent internal default |

---

## 3. Azure OpenAI Onboarding (Step-by-Step)

### Step 1 — Create an Azure OpenAI Resource

1. Open the [Azure Portal](https://portal.azure.com) and navigate to
   **Create a resource → Azure OpenAI**.
2. Choose a subscription, resource group, and region. Pick the region that
   has quota for the model you need (e.g. **East US** for GPT-4o).
3. Select the **Standard S0** pricing tier and click **Review + Create**.

### Step 2 — Create a Deployment

1. After the resource is provisioned, open it and navigate to
   **Azure OpenAI Studio → Deployments → + Create new deployment**.
2. Select model **gpt-4o** (or another supported model).
3. Give the deployment a name — for example `my-gpt4o-deployment`. This name
   is what you put in `AZURE_OPENAI_DEPLOYMENT`.
4. Set a tokens-per-minute quota appropriate for your team (100K TPM is a
   reasonable starting point for newsletter generation).

### Step 3 — Copy Keys and Endpoint

1. In the Azure Portal, open the resource and go to
   **Resource Management → Keys and Endpoint**.
2. Copy **KEY 1** (or KEY 2 for rotation) and the **Endpoint** URL.

### Step 4 — Configure `.env`

Create or edit `backend/.env` with the following block:

```bash
# ── Azure OpenAI ──────────────────────────────────────────────────────────────
AZURE_OPENAI_API_KEY=7a3b5c1d2e4f6g8h9i0j1k2l3m4n5o6p
AZURE_OPENAI_ENDPOINT=https://mycompany-openai.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=my-gpt4o-deployment
AZURE_OPENAI_API_VERSION=2024-12-01-preview
AZURE_OPENAI_VERIFY_SSL=true

# Optional: pin this deployment for every pipeline stage
NEWSLETTER_DEFAULT_MODEL=azure/my-gpt4o-deployment
```

> **API Version Note:** The `AZURE_OPENAI_API_VERSION` value must match an API
> version your deployment supports. `2024-12-01-preview` enables structured
> outputs and the latest chat-completions features. If your resource was created
> before mid-2024, try `2024-05-01-preview` or `2023-12-01-preview`.

### Step 5 — Verify

Start the backend and check the health endpoint:

```bash
cd MARS-NewsLetter
python backend/run.py &
curl http://localhost:5678/api/health
```

Then open the UI, create a new newsletter task, and observe that Stage 2 logs
show `auto_injected_default_model` with `model=azure/my-gpt4o-deployment`.

---

## 4. AWS Bedrock Onboarding (Step-by-Step)

### Path A — IAM Role with Instance Profile (Recommended for EC2 / ECS / EKS)

This path requires no long-lived credentials in environment variables, which is
the preferred approach for workloads running inside AWS.

#### Step 1 — Create the IAM Policy

Create a policy that grants `bedrock:InvokeModel` on the specific model ARNs
your deployment uses. Restrict to the minimum required models.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowBedrockNewsletterModels",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0",
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
        "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-pro-v1:0",
        "arn:aws:bedrock:us-east-1::foundation-model/meta.llama3-70b-instruct-v1:0"
      ]
    }
  ]
}
```

Save this as `mars-newsletter-bedrock-policy.json` and apply it:

```bash
aws iam create-policy \
  --policy-name MARSNewsletterBedrock \
  --policy-document file://mars-newsletter-bedrock-policy.json
```

#### Step 2 — Attach Policy to the Instance / Task Role

For EC2 instance profile:

```bash
aws iam attach-role-policy \
  --role-name my-ec2-instance-role \
  --policy-arn arn:aws:iam::123456789012:policy/MARSNewsletterBedrock
```

For ECS task role, attach via the ECS task definition's `taskRoleArn`.

#### Step 3 — Enable Model Access in the AWS Console

1. Open the **AWS Console → Amazon Bedrock → Model access**.
2. Click **Manage model access** and enable the models you need (Claude models
   require Anthropic's terms to be accepted).

#### Step 4 — `.env` for Instance Profile

```bash
# backend/.env — Path A (no static credentials needed)
AWS_DEFAULT_REGION=us-east-1

# Pin the model for all pipeline stages:
NEWSLETTER_DEFAULT_MODEL=bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0
```

---

### Path B — Static Access Key Pair

Use this path for local development or for workloads that cannot use instance
profiles (e.g. on-premises servers).

#### Step 1 — Create a Dedicated IAM User

```bash
aws iam create-user --user-name mars-newsletter-svc
aws iam attach-user-policy \
  --user-name mars-newsletter-svc \
  --policy-arn arn:aws:iam::123456789012:policy/MARSNewsletterBedrock
aws iam create-access-key --user-name mars-newsletter-svc
```

Save the `AccessKeyId` and `SecretAccessKey` from the output.

#### Step 2 — `.env` for Static Key Pair

```bash
# backend/.env — Path B (static credentials)
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_DEFAULT_REGION=us-east-1
# For assumed-role sessions (optional):
# AWS_SESSION_TOKEN=AQoDYXdzEJr...

# Pin the model for all pipeline stages:
NEWSLETTER_DEFAULT_MODEL=bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0
```

#### Selecting Alternative Bedrock Models

Override the model per stage via `NEWSLETTER_DEFAULT_MODEL` or via the UI
model override fields. Valid LiteLLM model identifiers:

| Model | LiteLLM Identifier |
|-------|-------------------|
| Claude 3.5 Sonnet v2 | `bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0` |
| Claude 3 Haiku | `bedrock/anthropic.claude-3-haiku-20240307-v1:0` |
| Amazon Nova Pro | `bedrock/amazon.nova-pro-v1:0` |
| Amazon Nova Lite | `bedrock/amazon.nova-lite-v1:0` |
| Llama 3 70B Instruct | `bedrock/meta.llama3-70b-instruct-v1:0` |

---

## 5. Enterprise Gateway Onboarding

Many large enterprises route all external LLM traffic through an internal proxy
that enforces data-loss-prevention (DLP) policies and centralizes cost
attribution. MARS-NewsLetter natively supports gateways that implement the
following authentication pattern:

1. **Stage 1** — OAuth2 token request (`password` or `client_credentials`
   grant) to an identity provider, yielding a bearer access token.
2. **Stage 2** _(optional)_ — Session JWT exchange: the access token is
   presented to a secondary endpoint that issues a short-lived session token
   (common in ADFS-rooted or proprietary SSO setups). Omit if your gateway
   only requires the Stage 1 token.
3. **Gateway call** — Standard OpenAI-wire-compatible
   `/chat/completions` request with bearer + session headers injected
   per-call.

The adapter caches both tokens in-process (thread-safe, single-flight), auto-
refreshes on TTL expiry, and transparently retries once on HTTP 401 after
invalidating cached tokens.

### Step 1 — Gather Gateway Credentials

Work with your platform team to obtain:

- The **OAuth2 token endpoint URL** (e.g. `https://idp.mycompany.com/oauth2/token`)
- **Grant type**: `password` (for service-account username/password flows) or
  `client_credentials` (for machine-to-machine OAuth2)
- For `password` grant: service account **username** and **password**
- For `client_credentials` grant: **client ID** and **client secret**
- The **gateway base URL** (the OpenAI-wire-compatible endpoint, e.g.
  `https://llm-gateway.mycompany.com/v1/`)
- Any required **extra request headers** for gateway calls
- The **corporate CA bundle** path if the gateway uses a private TLS certificate
- Whether a **session JWT exchange** (Stage 2) is required, and if so its
  endpoint and body template

### Step 2 — Configure `.env` (Password Grant Flow — minimal)

Only the following variables are required for a typical two-stage
enterprise gateway. Everything else has a sensible default. A fresh
W3C `traceparent` header is auto-injected on every session-JWT and
gateway call — **do not configure it manually**.

```bash
# backend/.env — Enterprise Gateway, grant_type=password

CMBAGENT_LLM_PROVIDER=enterprise_gateway

# Stage 1: OAuth2 token endpoint
ENTERPRISE_LLM_TOKEN_URL=https://idp.mycompany.com/oauth2/token
ENTERPRISE_LLM_GRANT_TYPE=password
ENTERPRISE_LLM_USERNAME=svc-newsletter
ENTERPRISE_LLM_PASSWORD=P@ssw0rdF0rSvcAccount!
ENTERPRISE_LLM_CLIENT_ID=mars-newsletter-client

# Stage 2: session JWT exchange (skip entirely by leaving SESSION_URL blank)
ENTERPRISE_LLM_SESSION_URL=https://gateway-portal.mycompany.com/api/auth/session-jwt
# Set only if the endpoint expects a body (supports {access_token}, {username}):
# ENTERPRISE_LLM_SESSION_BODY={"username":"{username}"}

# Gateway call
ENTERPRISE_LLM_GATEWAY_BASE_URL=https://llm-gateway.mycompany.com/v1/
ENTERPRISE_LLM_CONSUMER_APPLICATION=mars-newsletter
ENTERPRISE_LLM_DEFAULT_MODEL=gpt-4o

# TLS (only if the defaults don't match your setup)
ENTERPRISE_LLM_CA_BUNDLE=/etc/ssl/certs/mycompany-ca-bundle.pem
```

Optional additions (only when the defaults don't fit):

```bash
# Model name mapping (canonical → gateway-native), scope, proxies
ENTERPRISE_LLM_MODEL_MAP_JSON={"gpt-4o":"gpt-4-omni","gpt-4.1":"gpt-4.1"}
ENTERPRISE_LLM_SCOPE=llm.access
ENTERPRISE_LLM_PROXIES_JSON={"https":"http://proxy.mycompany.com:8080"}
```

### Step 3 — Configure `.env` (Client Credentials Flow — minimal)

```bash
# backend/.env — Enterprise Gateway, grant_type=client_credentials

CMBAGENT_LLM_PROVIDER=enterprise_gateway

ENTERPRISE_LLM_TOKEN_URL=https://idp.mycompany.com/oauth2/token
ENTERPRISE_LLM_GRANT_TYPE=client_credentials
ENTERPRISE_LLM_CLIENT_ID=mars-newsletter-client
ENTERPRISE_LLM_PASSWORD=AbCdEfGhIjKlMnOpQrStUvWxYz-client-secret
ENTERPRISE_LLM_SCOPE=api://llm-gateway/.default

# No Stage 2 session exchange needed for this gateway — omit SESSION_URL.

ENTERPRISE_LLM_GATEWAY_BASE_URL=https://llm-gateway.mycompany.com/v1/
ENTERPRISE_LLM_CONSUMER_APPLICATION=mars-newsletter
ENTERPRISE_LLM_DEFAULT_MODEL=gpt-4o
ENTERPRISE_LLM_CA_BUNDLE=/etc/ssl/certs/mycompany-ca-bundle.pem
```

### Variable Reference for Enterprise Gateway

**Required (or nearly always set):**

| Variable | Required | Description |
|----------|----------|-------------|
| `ENTERPRISE_LLM_TOKEN_URL` | Yes | OAuth2 token endpoint |
| `ENTERPRISE_LLM_GRANT_TYPE` | Yes | `password` or `client_credentials` |
| `ENTERPRISE_LLM_USERNAME` | password only | Service account username |
| `ENTERPRISE_LLM_PASSWORD` | Yes | Password (for `password` grant) or client secret |
| `ENTERPRISE_LLM_CLIENT_ID` | Yes | OAuth2 client ID |
| `ENTERPRISE_LLM_RESOURCE` | No | ADFS-style resource claim |
| `ENTERPRISE_LLM_SESSION_URL` | No | Stage 2 session JWT endpoint — leave blank to skip Stage 2 |
| `ENTERPRISE_LLM_SESSION_BODY` | No | JSON body template for Stage 2 — supports `{access_token}`, `{username}` |
| `ENTERPRISE_LLM_GATEWAY_BASE_URL` | Yes | OpenAI-wire-compatible gateway base URL |
| `ENTERPRISE_LLM_CONSUMER_APPLICATION` | No | Consumer application ID value (many gateways require it) |
| `ENTERPRISE_LLM_DEFAULT_MODEL` | Yes | Model name to use (after mapping) |
| `ENTERPRISE_LLM_MODEL_MAP_JSON` | No | JSON map from canonical model names to gateway-native names |
| `ENTERPRISE_LLM_CA_BUNDLE` | No | Path to corporate CA certificate bundle |
| `ENTERPRISE_LLM_VERIFY_SSL` | No | `true` (default) or `false` (development only) |
| `ENTERPRISE_LLM_PROXIES_JSON` | No | JSON proxy map e.g. `{"https":"http://proxy:8080"}` |
| `ENTERPRISE_LLM_SCOPE` | No | OAuth2 scope (space-separated) |

**Automatic — do NOT configure:**

- Fresh W3C `traceparent` header is injected on every session-JWT and gateway
  call. If your gateway does not need it, override with an empty string via
  `ENTERPRISE_LLM_SESSION_EXTRA_HEADERS_JSON={"traceparent":""}` (rare).
- Token cache TTL is derived from the `expires_in` field returned by the
  identity provider, minus a 60-second safety margin.
- 401 responses from the gateway automatically invalidate both cached
  tokens and retry once.

**Advanced overrides (rarely needed — the shown value is the default):**

| Variable | Default | Description |
|----------|---------|-------------|
| `ENTERPRISE_LLM_TOKEN_ENCODING` | `form` | Stage-1 body encoding (`form` or `json`) |
| `ENTERPRISE_LLM_TOKEN_FIELD` | `access_token` | Stage-1 response field containing the access token |
| `ENTERPRISE_LLM_TOKEN_TTL_SECONDS` | `3300` | Fallback TTL used only when `expires_in` is absent |
| `ENTERPRISE_LLM_SESSION_METHOD` | `POST` | HTTP method for Stage 2 |
| `ENTERPRISE_LLM_SESSION_TOKEN_FIELD` | `token` | Response field for the session token |
| `ENTERPRISE_LLM_SESSION_TTL_SECONDS` | `900` | Fallback TTL used only when `expires_in` is absent |
| `ENTERPRISE_LLM_SESSION_EXTRA_HEADERS_JSON` | — | Additional headers for the Stage 2 call. Supports `${traceparent}` (already auto-added) and `${env:VARNAME}` |
| `ENTERPRISE_LLM_ACCESS_HEADER` | `Authorization` | Header name for the access token (sent as `Bearer …`) |
| `ENTERPRISE_LLM_SESSION_HEADER` | `X-Authorization-Session` | Header name for the session token |
| `ENTERPRISE_LLM_CONSUMER_HEADER` | `X-Consumer-Application` | Header name for the consumer identifier |
| `ENTERPRISE_LLM_EXTRA_HEADERS_JSON` | — | Additional per-call gateway headers |
| `ENTERPRISE_LLM_AUTH_TIMEOUT_SECONDS` | `30` | Timeout for token-endpoint calls |
| `ENTERPRISE_LLM_CHAT_TIMEOUT_SECONDS` | `120` | Timeout for `/chat/completions` calls |
| `ENTERPRISE_LLM_MAX_AUTH_RETRIES` | `2` | Retries on transient failures before hard failure |

### TLS and Proxy Notes

- Set `ENTERPRISE_LLM_CA_BUNDLE` to the absolute path of your organization's
  CA bundle (PEM format). The adapter passes this path to both `requests`
  (used for token exchanges) and the underlying HTTP client for gateway calls.
- If your network requires an outbound HTTP proxy, set
  `ENTERPRISE_LLM_PROXIES_JSON={"https":"http://proxy.mycompany.com:8080"}`.
  The proxy applies to token endpoint calls and gateway calls alike.
- Never set `ENTERPRISE_LLM_VERIFY_SSL=false` in production. Disabling TLS
  verification exposes credentials to interception.

### Model Mapping

When the gateway exposes models under non-standard identifiers, use
`ENTERPRISE_LLM_MODEL_MAP_JSON` to translate:

```bash
ENTERPRISE_LLM_MODEL_MAP_JSON={"gpt-4o":"gpt-4-omni-2024","gpt-4.1":"gpt-4.1-2025"}
```

Model names supplied in the UI or via `NEWSLETTER_DEFAULT_MODEL` are run
through this map before the gateway call is made.

---

## 6. Multi-Tenant / Shared Deployment

### Current Architecture

MARS-NewsLetter currently reads all LLM provider credentials from process
environment variables at startup. This means a single running backend instance
uses a single set of credentials for all users.

### Recommended Patterns for Multi-Tenant Use

#### Pattern A — One Backend Instance Per Team (Simplest)

Run separate backend processes, each with its own `.env` pointing to that
team's API key or deployment:

```bash
# Team A backend — port 5680
PORT=5680 OPENAI_API_KEY=sk-proj-team-a-key python backend/run.py

# Team B backend — port 5681
PORT=5681 AZURE_OPENAI_API_KEY=team-b-key \
  AZURE_OPENAI_ENDPOINT=https://team-b.openai.azure.com/ \
  AZURE_OPENAI_DEPLOYMENT=gpt4o-team-b \
  python backend/run.py
```

Each team's Next.js frontend points `NEXT_PUBLIC_API_URL` at its own backend
port. This is the simplest approach and requires no application changes.

#### Pattern B — Credential-Injection Middleware (Advanced)

For deployments where a single backend must serve multiple teams using
different credentials, the recommended approach is to insert a middleware
layer between the reverse proxy and the FastAPI backend that:

1. Authenticates the inbound request (e.g. reads a JWT from the
   `Authorization` header).
2. Resolves the tenant's credential set from a secrets manager (AWS Secrets
   Manager, Azure Key Vault, HashiCorp Vault, etc.).
3. Forwards the resolved credential as a custom request header
   (e.g. `X-Tenant-API-Key: sk-proj-...`).
4. The FastAPI backend reads this header and uses it for the duration of the
   request instead of the process-level environment variable.

> **Implementation note:** The application does not yet include built-in
> per-request credential injection. This pattern requires a small wrapper
> around `services/config_bridge.py` or a FastAPI middleware that calls
> `ProviderRegistry.set_credentials(provider_id, creds)` with the per-request
> credentials before dispatching the stage runner.

Until per-request credential injection is implemented, run separate backend
instances per team. This is operationally equivalent and avoids cross-tenant
credential leakage at the application layer.

---

## 7. Production Hardening

### 7.1 Reverse Proxy Configuration

Run the FastAPI backend behind nginx or Traefik to terminate TLS and expose
the application on standard HTTPS port 443.

**nginx configuration:**

```nginx
# /etc/nginx/sites-available/mars-newsletter
server {
    listen 443 ssl http2;
    server_name newsletter.mycompany.com;

    ssl_certificate     /etc/ssl/certs/mycompany-newsletter.crt;
    ssl_certificate_key /etc/ssl/private/mycompany-newsletter.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    # Frontend (Next.js)
    location / {
        proxy_pass         http://127.0.0.1:3000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }

    # Backend API
    location /api/ {
        proxy_pass         http://127.0.0.1:5678;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }

    # WebSocket endpoint (used for stage status events)
    location /ws/ {
        proxy_pass             http://127.0.0.1:5678;
        proxy_http_version     1.1;
        proxy_set_header       Upgrade $http_upgrade;
        proxy_set_header       Connection "Upgrade";
        proxy_set_header       Host $host;
        proxy_read_timeout     3600s;
    }
}

server {
    listen 80;
    server_name newsletter.mycompany.com;
    return 301 https://$host$request_uri;
}
```

**Traefik (Docker Compose label approach):**

```yaml
# docker-compose.yml (excerpt)
services:
  backend:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.newsletter-api.rule=Host(`newsletter.mycompany.com`) && PathPrefix(`/api/`, `/ws/`)"
      - "traefik.http.routers.newsletter-api.tls=true"
      - "traefik.http.routers.newsletter-api.tls.certresolver=letsencrypt"
      - "traefik.http.services.newsletter-api.loadbalancer.server.port=5678"
```

### 7.2 CORS

Set `NEWSLETTER_CORS_ORIGINS` to the exact frontend origin. A trailing slash
or mismatched scheme (http vs https) will cause all API calls from the browser
to fail.

```bash
# backend/.env — production
NEWSLETTER_CORS_ORIGINS=https://newsletter.mycompany.com
```

To allow multiple origins (e.g. staging + production):

```bash
NEWSLETTER_CORS_ORIGINS=https://newsletter.mycompany.com,https://newsletter-staging.mycompany.com
```

### 7.3 Disable Debug and Auto-Reload

```bash
# backend/.env — production
NEWSLETTER_DEBUG=false
NEWSLETTER_ENABLE_RELOAD=false
LOG_LEVEL=WARNING
```

Auto-reload causes uvicorn to watch source files for changes and restart the
process. In production this risks restarting mid-stage and losing in-flight
work. Always set `NEWSLETTER_ENABLE_RELOAD=false`.

### 7.4 Persistent Work Directory

Stage outputs, SQLite databases, and logs are written to
`NEWSLETTER_DEFAULT_WORK_DIR`. In containerized or ephemeral environments this
directory must be mounted from a persistent volume:

```bash
# backend/.env — production
NEWSLETTER_DEFAULT_WORK_DIR=/data/mars-newsletter/workdir
```

In Docker Compose:

```yaml
services:
  backend:
    volumes:
      - newsletter-workdir:/data/mars-newsletter/workdir
volumes:
  newsletter-workdir:
    driver: local
```

This ensures that completed newsletter outputs and session history survive
container restarts.

### 7.5 Systemd Service Unit

To keep the backend running as a system service on Linux:

```ini
# /etc/systemd/system/mars-newsletter-backend.service
[Unit]
Description=MARS-NewsLetter FastAPI Backend
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=newsletter
Group=newsletter
WorkingDirectory=/opt/mars-newsletter/MARS-NewsLetter
ExecStart=/opt/mars-newsletter/venv/bin/python backend/run.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=mars-newsletter-backend

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=/data/mars-newsletter/workdir

# Environment file (keeps secrets off the command line)
EnvironmentFile=/opt/mars-newsletter/MARS-NewsLetter/backend/.env

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable mars-newsletter-backend
sudo systemctl start mars-newsletter-backend
sudo journalctl -u mars-newsletter-backend -f
```

### 7.6 Frontend Build

Build the Next.js frontend once and serve the static output via a CDN or the
built-in Next.js server:

```bash
cd MARS-NewsLetter/frontend
cp .env.local.example .env.local
# Edit NEXT_PUBLIC_API_URL=https://newsletter.mycompany.com
npm install --production=false
npm run build
npm run start -- --port 3000
```

For a systemd unit for the frontend:

```ini
# /etc/systemd/system/mars-newsletter-frontend.service
[Unit]
Description=MARS-NewsLetter Next.js Frontend
After=network.target

[Service]
Type=simple
User=newsletter
Group=newsletter
WorkingDirectory=/opt/mars-newsletter/MARS-NewsLetter/frontend
ExecStart=/usr/bin/npm run start -- --port 3000
Restart=on-failure
RestartSec=10
EnvironmentFile=/opt/mars-newsletter/MARS-NewsLetter/frontend/.env.local

[Install]
WantedBy=multi-user.target
```

---

## 8. Environment Variable Reference Table

All variables are read from `backend/.env` (or the shell environment) at
startup. Variables marked **Required** must be set for the application to
function. Variables marked **Optional** have defaults and can be omitted.

### 8.1 Application / Server

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `HOST` | Optional | `0.0.0.0` | Bind address for the uvicorn server |
| `PORT` | Optional | `8000` | TCP port for the FastAPI backend (configure frontend to match via `NEXT_PUBLIC_API_URL`) |
| `NEWSLETTER_APP_TITLE` | Optional | `MARS-NewsLetter API` | Application title shown in the OpenAPI docs |
| `NEWSLETTER_APP_VERSION` | Optional | `1.0.0` | Application version string |
| `NEWSLETTER_DEBUG` | Optional | `false` | Enable debug mode and verbose logging. Always `false` in production |
| `NEWSLETTER_ENABLE_RELOAD` | Optional | `false` | Enable uvicorn auto-reload on source changes. Development only; always `false` in production |
| `NEWSLETTER_CORS_ORIGINS` | Optional | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated list of CORS-allowed origins. Set to your frontend domain in production |
| `NEWSLETTER_DEFAULT_WORK_DIR` | Optional | `./cmbdir_newsletter` | Absolute or relative path for stage outputs, logs, and the SQLite session database. Relative paths resolve against the `backend/` directory |
| `NEWSLETTER_MAX_FILE_SIZE_MB` | Optional | `10` | Maximum upload file size in megabytes |

### 8.2 Logging

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LOG_LEVEL` | Optional | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). Use `WARNING` in production |
| `LOG_JSON` | Optional | `false` | Emit logs as structured JSON (useful for log-aggregation pipelines) |
| `LOG_FILE` | Optional | _(work_dir/logs/newsletter-backend.log)_ | Override log file path. Leave blank to use the default inside `NEWSLETTER_DEFAULT_WORK_DIR` |

### 8.3 Provider Selection

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CMBAGENT_LLM_PROVIDER` | Optional | _(auto-detected)_ | Explicit provider ID: `openai`, `anthropic`, `azure`, `aws_bedrock`, `google`, `mistral`, or `enterprise_gateway` |
| `CMBAGENT_ENTERPRISE_GATEWAY_ENABLED` | Optional | `false` | Alternative to `CMBAGENT_LLM_PROVIDER=enterprise_gateway`; auto-activates the gateway when set to `true` |

### 8.4 OpenAI

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | Conditional | — | OpenAI API key. Required when using the OpenAI provider |

### 8.5 Anthropic

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Conditional | — | Anthropic API key. Required when using the Anthropic provider |

### 8.6 Azure OpenAI

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AZURE_OPENAI_API_KEY` | Conditional | — | Azure OpenAI resource key |
| `AZURE_OPENAI_ENDPOINT` | Conditional | — | Azure OpenAI resource endpoint URL (e.g. `https://myco.openai.azure.com/`) |
| `AZURE_OPENAI_DEPLOYMENT` | Conditional | — | Deployment name created in Azure OpenAI Studio (e.g. `my-gpt4o-deployment`) |
| `AZURE_OPENAI_API_VERSION` | Optional | `2024-12-01-preview` | Azure OpenAI API version string |
| `AZURE_OPENAI_VERIFY_SSL` | Optional | `true` | Verify TLS certificates for Azure endpoint calls |

### 8.7 AWS Bedrock

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AWS_ACCESS_KEY_ID` | Conditional | — | AWS access key ID. Omit when using instance profile |
| `AWS_SECRET_ACCESS_KEY` | Conditional | — | AWS secret access key. Omit when using instance profile |
| `AWS_SESSION_TOKEN` | Optional | — | Temporary session token for assumed-role credentials |
| `AWS_DEFAULT_REGION` | Conditional | `us-east-1` | AWS region where Bedrock is enabled |
| `AWS_PROFILE` | Optional | — | Named AWS profile from `~/.aws/credentials` (alternative to key variables) |

### 8.8 Google Gemini

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOOGLE_API_KEY` | Conditional | — | Google AI API key for Gemini models |
| `GEMINI_API_KEY` | Conditional | — | Alias read by cmbagent's KeyManager with higher priority than `GOOGLE_API_KEY`. Set to the same value |

### 8.9 Mistral

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MISTRAL_API_KEY` | Conditional | — | Mistral API key |

### 8.10 Enterprise Gateway

> Most deployments only need the variables marked **Yes (gateway)** plus
> `ENTERPRISE_LLM_SESSION_URL`, `ENTERPRISE_LLM_CONSUMER_APPLICATION`,
> and `ENTERPRISE_LLM_CA_BUNDLE`. Everything else has a sensible default.
> A fresh W3C `traceparent` header is auto-injected on every request —
> do NOT configure `ENTERPRISE_LLM_SESSION_EXTRA_HEADERS_JSON` or
> `ENTERPRISE_LLM_EXTRA_HEADERS_JSON` for that purpose.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ENTERPRISE_LLM_TOKEN_URL` | Yes (gateway) | — | OAuth2 token endpoint URL |
| `ENTERPRISE_LLM_GRANT_TYPE` | Yes (gateway) | `password` | OAuth2 grant type: `password` or `client_credentials` |
| `ENTERPRISE_LLM_USERNAME` | password grant | — | Service account username |
| `ENTERPRISE_LLM_PASSWORD` | Yes (gateway) | — | Password (for `password` grant) or client secret (for `client_credentials`) |
| `ENTERPRISE_LLM_CLIENT_ID` | Yes (gateway) | — | OAuth2 client ID |
| `ENTERPRISE_LLM_RESOURCE` | Optional | — | ADFS-style resource claim |
| `ENTERPRISE_LLM_SCOPE` | Optional | — | OAuth2 scope |
| `ENTERPRISE_LLM_TOKEN_ENCODING` | Optional | `form` | Request encoding: `form` or `json` |
| `ENTERPRISE_LLM_TOKEN_FIELD` | Optional | `access_token` | JSON field name in the token response |
| `ENTERPRISE_LLM_TOKEN_TTL_SECONDS` | Optional | `3300` | Fallback token TTL when `expires_in` is absent |
| `ENTERPRISE_LLM_SESSION_URL` | Optional | — | Stage 2 session JWT endpoint; leave blank to skip |
| `ENTERPRISE_LLM_SESSION_METHOD` | Optional | `POST` | HTTP method for session exchange |
| `ENTERPRISE_LLM_SESSION_BODY` | Optional | `{}` | JSON body template for session exchange |
| `ENTERPRISE_LLM_SESSION_TOKEN_FIELD` | Optional | `token` | Field name in the session JWT response |
| `ENTERPRISE_LLM_SESSION_TTL_SECONDS` | Optional | `900` | Session token TTL in seconds |
| `ENTERPRISE_LLM_SESSION_EXTRA_HEADERS_JSON` | Optional | — | Extra headers for the session exchange; supports `${traceparent}` and `${env:VARNAME}` |
| `ENTERPRISE_LLM_GATEWAY_BASE_URL` | Yes (gateway) | — | Base URL of the OpenAI-wire-compatible gateway |
| `ENTERPRISE_LLM_ACCESS_HEADER` | Optional | `Authorization` | Header name for the bearer access token |
| `ENTERPRISE_LLM_SESSION_HEADER` | Optional | `X-Authorization-Session` | Header name for the session JWT |
| `ENTERPRISE_LLM_CONSUMER_HEADER` | Optional | — | Header name for consumer application ID |
| `ENTERPRISE_LLM_CONSUMER_APPLICATION` | Optional | — | Consumer application identifier value |
| `ENTERPRISE_LLM_EXTRA_HEADERS_JSON` | Optional | — | JSON map of additional per-call headers |
| `ENTERPRISE_LLM_MODEL_MAP_JSON` | Optional | — | JSON map from canonical to gateway-native model names |
| `ENTERPRISE_LLM_DEFAULT_MODEL` | Yes (gateway) | — | Default model name (after mapping) |
| `ENTERPRISE_LLM_CA_BUNDLE` | Optional | system trust | Path to corporate CA bundle PEM file |
| `ENTERPRISE_LLM_VERIFY_SSL` | Optional | `true` | TLS verification; never disable in production |
| `ENTERPRISE_LLM_PROXIES_JSON` | Optional | — | JSON proxy map for outbound connections |
| `ENTERPRISE_LLM_AUTH_TIMEOUT_SECONDS` | Optional | `30` | Timeout for token endpoint requests |
| `ENTERPRISE_LLM_CHAT_TIMEOUT_SECONDS` | Optional | `120` | Timeout for chat completion requests |
| `ENTERPRISE_LLM_MAX_AUTH_RETRIES` | Optional | `2` | Number of auth retries on HTTP 401 |

### 8.11 Model and Pipeline Tuning

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEWSLETTER_DEFAULT_MODEL` | Optional | _(auto-detected)_ | Override model for all pipeline stages. Accepts any LiteLLM model string (e.g. `azure/my-gpt4o-deployment`, `gpt-4o`, `bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0`) |
| `CMBAGENT_DEFAULT_MODEL` | Optional | _(auto-detected)_ | cmbagent-level default model fallback; used when `NEWSLETTER_DEFAULT_MODEL` is not set |
| `CMBAGENT_PLANNER_MODEL` | Optional | — | Override model for the cmbagent planner agent |
| `CMBAGENT_PLAN_REVIEWER_MODEL` | Optional | — | Override model for the plan reviewer agent |
| `CMBAGENT_RESEARCHER_MODEL` | Optional | — | Override model for the researcher agent |
| `CMBAGENT_ORCHESTRATION_MODEL` | Optional | — | Override model for the orchestration / default LLM role |
| `CMBAGENT_FORMATTER_MODEL` | Optional | — | Override model for the response formatter agent |
| `STAGE4_SECTION_MODE` | Optional | `1` | Set to `1` to write the newsletter section-by-section (recommended for long outputs). Set to `0` for legacy single-call generation |
| `STAGE5_EDITOR_MAX_TOKENS` | Optional | `32000` | Maximum output tokens for the Stage 5 editor. Increase if the final draft is being truncated |
| `STAGE5_MODEL` | Optional | _(NEWSLETTER_DEFAULT_MODEL)_ | Override the model used exclusively in Stage 5 (review and editing) |
| `NEWSLETTER_AI_STAGE_TIMEOUT_S` | Optional | `240` | Hard timeout in seconds for any single AI stage call. Minimum enforced value is 60. Increase for complex stages on slow providers |
| `CMBAGENT_MAX_MSG_CONTENT_CHARS` | Optional | `200000` | Per-message character cap passed to cmbagent. Raise for long-form runs; lowering reduces token pressure |

### 8.12 Frontend Variables

These are set in `frontend/.env.local` and are not read by the backend.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | Optional | `http://localhost:8000` | Backend API base URL. Must be reachable from the browser (or use Next.js rewrites) |
| `NEXT_PUBLIC_WS_URL` | Optional | _(derived from `NEXT_PUBLIC_API_URL`)_ | WebSocket base URL. Overrides the auto-derived `ws://`/`wss://` URL |
| `NEXT_PUBLIC_CMBAGENT_WORK_DIR` | Optional | `./cmbdir` | Informational display of the work directory path; must match `NEWSLETTER_DEFAULT_WORK_DIR` |
| `NEXT_PUBLIC_DEBUG` | Optional | `false` | Enable verbose browser console logging |
