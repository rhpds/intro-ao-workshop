# Module 01 — Overview and Interface Tour

### Brief Overview

This module introduces participants to the Ansible Automation Orchestrator (AO) environment they will use throughout the lab. Participants log in to the pre-deployed AO instance, confirm the environment is accessible, and take a structured tour of the AO interface to identify the canvas, node palette, workflow list, and monitoring views. By the end of this module learners have enough orientation to begin building workflows with confidence in subsequent modules.

### Audience and Time

- **Target personas:** System Administrators, Automation Administrators, DevOps engineers
- **Experience level:** Beginner — basic awareness of Ansible Automation Platform is all that is required; no prior AO or AI experience expected
- **Prerequisites for this module:** Access to a web browser; lab environment credentials provided at session start
- **Estimated duration:** 20 minutes

### Learning Objectives

- Log in to the Ansible Automation Orchestrator web console using provided credentials
- Identify the main regions of the AO interface: the workflow canvas, the node palette, the workflow list, and the monitoring/activity views
- Distinguish AO's role within the broader Ansible Automation Platform ecosystem, including its relationship to Event-Driven Ansible and AAP job templates

### Lab Structure

| Section | Title | Duration |
|---------|-------|----------|
| 1 | Log in and orient yourself | 8 min |
| 2 | Navigate the AO interface | 12 min |

### Detailed Steps

**Section 1 — Log in and orient yourself**

1. Open a web browser and navigate to the AO console URL provided in the lab environment details.
2. Enter the provided username and password and click **Log in**.
3. Confirm the AO dashboard loads without errors.
4. Note the top-level navigation items visible after login and observe the overall page structure.

**Section 2 — Navigate the AO interface**

5. Locate the **Workflows** list in the main navigation and click it to view the workflow inventory.
6. Click **Create workflow** (or the equivalent primary action button) to open a blank workflow canvas.
7. Identify the **node palette** on the left or right side of the canvas — the panel that lists available node types (trigger, agent, approval, switch, job template, etc.).
8. Identify the **canvas area** where nodes are placed and connected into a workflow.
9. Close or cancel the blank workflow without saving and return to the workflow list.
10. Locate the **Monitoring** or **Activity** view and observe the available columns and filters — execution history will be populated after the workflow runs in Module 4.
11. Return to the main dashboard and note any summary tiles or status indicators shown.

### Key Takeaways

- AO provides a unified, visual workflow canvas that combines task-based, event-driven, and AI-driven automation in a single interface
- The node palette is the starting point for selecting the building blocks of any AO workflow
- The monitoring view gives real-time and historical visibility into workflow executions
- AO operates alongside — and integrates with — the existing AAP job templates and Event-Driven Ansible components participants may already know

### Infrastructure Notes

- The AO operator is pre-installed on the SNO OCP 4.20 cluster; participants do not need to install or configure the operator
- Lab environment credentials (URL, username, password) are displayed in the learner's Showroom environment panel
- No AAP or AO configuration changes are made in this module — it is observation only
