# Module 03 — Build the Workflow

### Brief Overview

This is the core build module of the lab. Participants construct a complete incident triage workflow on the AO canvas by placing and configuring seven node types in sequence: a webhook trigger that receives the incoming incident event, an AI triage agent that assesses the incident using the LLM and MCP integrations configured in Module 2, an approval gate that holds execution pending human review, a switch node that routes execution based on the approval outcome, an AAP job template node that triggers the remediation playbook, and a resolve node that closes the incident. By the end of this module the workflow is fully assembled, connected, and ready to execute.

### Audience and Time

- **Target personas:** System Administrators, Automation Administrators, DevOps engineers
- **Experience level:** Beginner
- **Prerequisites for this module:** Completion of Module 2; credentials and integrations must be saved and healthy before this module begins
- **Estimated duration:** 40 minutes

### Learning Objectives

- Place and configure an Event-Driven Ansible webhook trigger node to initiate the workflow on an incoming event
- Add and configure an AI triage agent node, attaching the MCP server and LLM provider integrations created in Module 2
- Implement an approval gate node that pauses workflow execution and requires a human decision before proceeding
- Add a switch node to route workflow execution conditionally based on the approval outcome
- Add an AAP job template node and bind it to a pre-built remediation job template in AAP
- Add a resolve node to mark the incident as resolved after successful remediation
- Connect all nodes on the canvas and validate the workflow structure

### Lab Structure

| Section | Title | Duration |
|---------|-------|----------|
| 1 | Add the webhook trigger | 5 min |
| 2 | Add the AI triage agent | 7 min |
| 3 | Add the approval node | 5 min |
| 4 | Add the switch node | 5 min |
| 5 | Add the AAP job template node | 8 min |
| 6 | Resolve the incident | 5 min |
| 7 | Connect and review the workflow | 5 min |

### Detailed Steps

**Section 1 — Add the webhook trigger**

1. From the AO workflow list, click **Create workflow** and give the workflow a descriptive name (for example, `incident-triage-workflow`).
2. From the node palette, drag a **Webhook trigger** node onto the canvas.
3. In the node configuration panel, note the generated webhook URL — you will use this in Module 4 to send a test event.
4. Set any required fields (for example, expected payload schema or event filter) as specified in the lab instructions.
5. Click **Save** or **Apply** on the node configuration panel.

**Section 2 — Add the AI triage agent**

6. From the node palette, drag an **AI agent** node onto the canvas and position it to the right of the webhook trigger node.
7. Open the node configuration panel for the AI agent node.
8. In the **LLM provider** field, select the LLM provider integration created in Module 2.
9. In the **MCP server** field, select the MCP server integration created in Module 2.
10. Enter the agent's system prompt or role description as specified in the lab instructions (for example, a prompt that instructs the agent to assess the incident severity and recommend a remediation action).
11. Click **Save** or **Apply** on the node configuration panel.

**Section 3 — Add the approval node**

12. From the node palette, drag an **Approval** node onto the canvas and position it after the AI triage agent node.
13. Open the node configuration panel and configure the approval step name and any notification or timeout settings specified in the lab instructions.
14. Click **Save** or **Apply** on the node configuration panel.

**Section 4 — Add the switch node**

15. From the node palette, drag a **Switch** node onto the canvas and position it after the approval node.
16. Open the node configuration panel and define the conditions for each branch — for example, one branch for an approved outcome and one branch for a rejected outcome.
17. Click **Save** or **Apply** on the node configuration panel.

**Section 5 — Add the AAP job template node**

18. From the node palette, drag an **AAP job template** node onto the canvas on the approved branch path.
19. Open the node configuration panel.
20. In the **Credential** field, select the AAP credential created in Module 2.
21. In the **Job template** field, select the pre-built remediation job template from the list (the available templates are pre-loaded in AAP).
22. Review any extra variables or limit fields and configure them as specified in the lab instructions.
23. Click **Save** or **Apply** on the node configuration panel.

**Section 6 — Resolve the incident**

24. From the node palette, drag a **Resolve** node (or equivalent end/close node) onto the canvas after the AAP job template node.
25. Open the node configuration panel and configure the resolution status or message as specified in the lab instructions.
26. Click **Save** or **Apply** on the node configuration panel.

**Section 7 — Connect and review the workflow**

27. Draw a connection from the **Webhook trigger** node to the **AI triage agent** node by dragging from the output port of the trigger to the input port of the agent.
28. Connect the **AI triage agent** output to the **Approval** node input.
29. Connect the **Approval** node output to the **Switch** node input.
30. Connect the approved branch output of the **Switch** node to the **AAP job template** node input.
31. Connect the **AAP job template** node output to the **Resolve** node input.
32. Connect the rejected branch output of the **Switch** node to an appropriate end state (for example, a second Resolve node with a rejected status, or as specified in the lab instructions).
33. Review the fully connected workflow on the canvas and confirm all nodes show a valid (no-error) state.
34. Save the workflow.

### Key Takeaways

- AO workflows are built by composing discrete node types on a visual canvas — each node encapsulates a specific capability (triggering, AI reasoning, approval, routing, execution, resolution)
- The webhook trigger node creates an EDA-compatible endpoint that receives events without requiring participants to write any EDA rulebook code
- The AI triage agent node uses the MCP protocol to give the LLM access to tools, making it capable of taking structured actions rather than only generating text
- Approval gates are first-class workflow nodes in AO, enabling human-in-the-loop control within an otherwise automated pipeline
- The switch node provides conditional routing based on structured data (such as the approval outcome), enabling a single workflow to handle multiple paths
- AAP job template nodes reuse existing automation assets — participants connect to pre-built playbooks rather than writing new automation

### Infrastructure Notes

- All AAP job templates used in this module are pre-loaded in the lab AAP instance; participants select them from a dropdown and do not need to create or modify playbooks
- The RHEL managed node is pre-registered in the AAP inventory and is the implicit target of the remediation job template
- The webhook URL generated by the trigger node is unique to the workflow instance; participants copy it for use in Module 4
- Assessment is trust-based — the workflow save succeeding without validation errors is the primary success indicator for this module
