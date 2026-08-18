# Module 02 — Set Up Integrations and Credentials

### Brief Overview

Before a workflow can call an AI agent or connect to an MCP server, AO must be given the credentials and integration endpoints it needs. In this module participants configure the three foundational connections the incident triage workflow depends on: an AAP credential, the MCP server integration that enables tool-use for the AI agent, and the LLM provider integration that points AO to the MaaS (Model-as-a-Service) endpoint. Completing this module leaves the environment ready for workflow construction in Module 3.

### Audience and Time

- **Target personas:** System Administrators, Automation Administrators, DevOps engineers
- **Experience level:** Beginner
- **Prerequisites for this module:** Completion of Module 1 (familiarity with AO navigation); MCP server URL and LLM provider endpoint URL are provided in the lab environment details
- **Estimated duration:** 20 minutes

### Learning Objectives

- Create and save a credential in AO that will be used to authenticate job template calls to AAP
- Create an MCP server integration in AO that enables the AI triage agent to invoke tools via the Model Context Protocol
- Create an LLM provider integration in AO that connects the AI triage agent to the pre-deployed open-source MaaS endpoint

### Lab Structure

| Section | Title | Duration |
|---------|-------|----------|
| 1 | Create credentials | 8 min |
| 2 | Create the MCP server integration | 6 min |
| 3 | Create the LLM provider integration | 6 min |

### Detailed Steps

**Section 1 — Create credentials**

1. In the AO interface, navigate to the **Credentials** section (found under Settings or Integrations, depending on the AO version in the lab environment).
2. Click **Add credential** or the equivalent create action.
3. Select the credential type appropriate for authenticating to AAP (for example, an AAP or Ansible Controller credential type).
4. Enter a descriptive name for the credential (for example, `aap-lab-credential`).
5. Fill in the required fields using the AAP URL, username, and password provided in the lab environment details.
6. Click **Save** and confirm the credential appears in the credentials list without errors.

**Section 2 — Create the MCP server integration**

7. Navigate to the **Integrations** section of the AO interface.
8. Click **Add integration** and select the **MCP server** integration type.
9. Enter a descriptive name for the integration (for example, `lab-mcp-server`).
10. Enter the MCP server URL provided in the lab environment details.
11. Configure any required authentication fields as specified in the lab environment details.
12. Click **Save** and verify the integration is listed and shows a healthy or connected status.

**Section 3 — Create the LLM provider integration**

13. Still in the **Integrations** section, click **Add integration** and select the **LLM provider** integration type.
14. Enter a descriptive name (for example, `lab-llm-provider`).
15. Enter the MaaS endpoint URL provided in the lab environment details.
16. Select or confirm the model name as specified in the lab environment details.
17. Configure any required authentication fields (API key or token) using the values provided.
18. Click **Save** and verify the integration is listed and shows a healthy or connected status.

### Key Takeaways

- AO separates credentials from integrations — credentials store authentication secrets, integrations define the endpoint and protocol for connecting to external services
- The MCP server integration enables AO's AI agent nodes to use tools via the Model Context Protocol, extending what the agent can do beyond language generation alone
- The LLM provider integration decouples the workflow from any specific hosted AI service — in this lab an open-source model is used via MaaS, which can be swapped without rebuilding the workflow
- Both integrations created here are reusable across multiple workflows in the same AO environment

### Infrastructure Notes

- The MCP server instance and MaaS endpoint are pre-deployed and accessible from the AO environment; participants do not need to deploy or configure them
- MCP server URL, LLM provider endpoint URL, and any required API keys or tokens are provided in the Showroom environment panel
- If an integration shows an unhealthy status after saving, verify the URL was copied without trailing spaces; the lab facilitator can also confirm connectivity from the AO pod
