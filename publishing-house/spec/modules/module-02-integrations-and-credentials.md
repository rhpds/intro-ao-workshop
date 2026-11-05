# Module 02 — Getting Started: Integrations and Credentials

### Brief Overview

Participants build the two integrations that the rest of the lab depends on: an MCP Server integration pointing at the AAP MCP server (which lets task agent steps list job templates and read inventory) and an LLM Provider integration pointing at the shared model service (qwen3-235b via Models-as-a-Service). Along the way they create an AAP API token and two AO credentials — one HTTP Bearer Token and one LLM Provider — and validate that both integrations report Available before moving on. All objects are created in the default project.

### Audience and Time

- **Target personas:** System Administrators, Automation Administrators, DevOps engineers
- **Experience level:** Beginner — no prior AO experience required
- **Prerequisites for this module:** Module 01 complete; AO and AAP accessible from the browser
- **Estimated duration:** 15 minutes

### Learning Objectives

- Create an AAP API token and explain why it is needed for the MCP server connection
- Create an HTTP Bearer Token credential and an LLM Provider credential in AO's default project
- Configure an MCP Server integration pointing at the AAP MCP server endpoint and test the connection
- Configure an LLM Provider integration pointing at the MaaS endpoint and test the connection
- Validate both integrations to confirm they report Available status

### Lab Structure

| Section | Title | Duration |
|---------|-------|----------|
| 1 | Create an AAP API token | 3 min |
| 2 | Create the AAP MCP credential | 3 min |
| 3 | Create the LLM credential | 2 min |
| 4 | Create the AAP MCP Server integration | 4 min |
| 5 | Create the LLM Provider integration | 3 min |

### Detailed Steps

**Section 1 — Create an AAP API token**

1. Open the AAP tab and log in with the provided admin credentials.
2. Expand Access Management → API Tokens and click Create API token.
3. Set Description to Student AAP MCP Token and Scope to Write; leave OAuth application empty.
4. Click Create token, copy the token value from the dialog, and paste it somewhere accessible (it is shown only once).

**Section 2 — Create the AAP MCP credential**

5. Log in to AO with the provided admin credentials.
6. Expand Configuration → Credentials. Confirm the Project selector reads default.
7. Click Create credential. Set Name to Student AAP MCP Credential, Project to default, and Credential type to HTTP Bearer Token.
8. Paste the AAP API token into the Token field and click Create credential.

**Section 3 — Create the LLM credential**

9. Click Create credential again. Set Name to Student LLM Credential, Project to default, and Credential type to LLM Provider (not HTTP Bearer Token).
10. Paste the LLM API key into the API Key field and click Create credential.

**Section 4 — Create the AAP MCP Server integration**

11. Expand Configuration → Integrations and click Configure integration.
12. On Integration details: set Integration type to MCP Server, Server name / ID to Student AAP MCP Server, and API URL to the AAP MCP server endpoint (including the /mcp suffix). Leave Scope set to Global. Click Next.
13. On Connection credential: select Student AAP MCP Credential from the Health check credential dropdown and click Test connection.
14. Confirm a green Connection tested notification appears and 144 tools are discovered. Leave all tools enabled on step 3 and click Save integration.

**Section 5 — Create the LLM Provider integration**

15. Click Configure integration again. Set Integration type to LLM Provider, Provider type to Red Hat AI, Name to Student LLM, and API URL to the LiteLLM endpoint. Click Next.
16. Select Student LLM Credential and click Test connection. Confirm 1 model (qwen3-235b) is discovered. Click Save integration.
17. Validate both integrations: click ⋮ → Validate integration for Student LLM, then repeat for Student AAP MCP Server. Confirm both show Available status.

### Key Takeaways

- Integrations are connections; credentials are secrets — they are separate objects so a credential can serve multiple integrations and rotating a secret does not require rebuilding a connection
- Credentials are scoped to a single project; a credential in solutions cannot be used by a workflow in default
- The credential type must match what the integration expects — an LLM Provider integration will not list an HTTP Bearer Token credential
- Enabling all 144 MCP tools in the integration does not hand them all to task agent steps; it makes them available to pick from in later modules

### Infrastructure Notes

- The AAP MCP server endpoint includes a required /mcp suffix; connections fail without it
- The LLM API key and model service URL are pre-provisioned in the lab environment; participants use these values directly
- All objects created in this module must be in the default project; they cannot be moved after creation
