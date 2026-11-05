# Module 01 — Lab Overview

### Brief Overview

This module introduces participants to the Ansible Automation Orchestrator (AO) lab environment and the core concepts behind AO workflows before any hands-on configuration begins. Participants read about the AO canvas, its building blocks (triggers, task agents, switch steps, approval gates, and AAP job template steps), and what they will build across the six modules. The module also provides the credential reference they will need throughout the lab: AO, AAP, MCP server, OpenFlake, LLM, Red Hat Lightspeed, Gitea, and Mattermost. By the end of this module participants know what the lab covers, understand the conceptual model, and have all credentials bookmarked.

### Audience and Time

- **Target personas:** System Administrators, Automation Administrators, DevOps engineers
- **Experience level:** Beginner — basic awareness of Ansible Automation Platform is all that is required; no prior AO or AI experience expected
- **Prerequisites for this module:** Access to a web browser; lab environment credentials provided at session start
- **Estimated duration:** 5 minutes

### Learning Objectives

- Describe the role of Automation Orchestrator within the Ansible Automation Platform ecosystem
- Identify the five types of building blocks used in AO workflows: triggers, task agents, switch steps, approval gates, and AAP job template steps
- Locate the credentials and URLs for all systems used in the lab (AO, AAP, MCP server, OpenFlake, LLM, Lightspeed, Gitea, Mattermost)
- Understand the sequence of workflows that will be built across the six lab modules

### Lab Structure

| Section | Title | Duration |
|---------|-------|----------|
| 1 | Introduction and concepts | 3 min |
| 2 | Credential reference | 2 min |

### Detailed Steps

**Section 1 — Introduction and concepts**

1. Read the introduction explaining what Automation Orchestrator is and how it relates to AAP.
2. Review the five workflow building blocks: triggers (manual, webhook, EDA), task agents, switch steps, approval gates, and AAP job template steps.
3. Read the module map to understand what will be built in each of the six modules.
4. Review the list of Red Hat products and supporting applications in the environment.

**Section 2 — Credential reference**

5. Locate and note the AO console URL and credentials.
6. Locate and note the AAP URL and credentials.
7. Locate and note the AAP MCP server endpoint.
8. Locate and note the OpenFlake URL and credentials.
9. Locate and note the LLM API URL, key, and model name.
10. Locate and note the Red Hat Lightspeed URL and credentials (shared account; filter by GUID tag).
11. Locate and note the Gitea URL, credentials, and playbook repository.
12. Locate and note the Mattermost URL and credentials.

### Key Takeaways

- Automation Orchestrator provides a visual canvas that connects existing AAP job templates with AI-powered task agents, conditional routing, and human-in-the-loop approvals
- Triggers, task agents, switches, approval gates, and AAP job template steps are the building blocks of every workflow in this lab
- All credentials needed for the lab are on the lab overview page and persist across modules
- The solutions project in AO holds a complete, working copy of every workflow; it is available as a reference at any point

### Infrastructure Notes

- The AO operator is pre-installed on the SNO OCP 4.20 cluster; no installation or operator configuration is required
- Lab environment credentials are displayed in the learner's Showroom environment panel
- OpenFlake, Gitea, and Mattermost are pre-deployed supporting applications; no setup is required
