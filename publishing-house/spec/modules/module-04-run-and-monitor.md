# Module 04 — Run and Monitor

### Brief Overview

With the workflow built and saved, this module puts it into motion. Participants simulate an incoming incident by sending a test payload to the workflow's webhook trigger URL, then follow the execution through the AO monitoring view in real time — watching the AI triage agent assess the incident, pausing at the approval gate to make a human decision, and observing the AAP job template run to completion. The module closes with a review of the final execution results and incident resolution status. This module reinforces what AO's end-to-end execution experience looks like for an operator on call.

### Audience and Time

- **Target personas:** System Administrators, Automation Administrators, DevOps engineers
- **Experience level:** Beginner
- **Prerequisites for this module:** Completion of Module 3; the incident triage workflow must be saved and in a valid state; the webhook trigger URL from Module 3 must be available
- **Estimated duration:** 20 minutes

### Learning Objectives

- Trigger the incident triage workflow by sending a test event payload to the webhook trigger URL
- Monitor real-time workflow execution progress in the AO monitoring view, identifying node-by-node status updates
- Respond to the approval gate as a human approver within the running workflow execution
- Inspect the final execution results, including the AI agent's triage output, the approval decision, and the AAP job template run outcome

### Lab Structure

| Section | Title | Duration |
|---------|-------|----------|
| 1 | Trigger the workflow | 4 min |
| 2 | Monitor real-time execution | 6 min |
| 3 | Handle the approval | 5 min |
| 4 | Inspect final results | 5 min |

### Detailed Steps

**Section 1 — Trigger the workflow**

1. Retrieve the webhook trigger URL generated in Module 3 (visible in the workflow's trigger node configuration panel).
2. Open a terminal or use the browser-based tool provided in the lab environment.
3. Send a test incident event payload to the webhook URL using `curl` or the equivalent method specified in the lab instructions. The payload simulates an incoming alert (for example, a disk full or service down event on the RHEL managed node).
4. Observe that the AO interface shows the workflow transitioning to a running state.

**Section 2 — Monitor real-time execution**

5. Navigate to the **Monitoring** or **Activity** view in the AO interface and locate the in-progress execution of the incident triage workflow.
6. Click the execution entry to open the detailed execution view.
7. Observe the status of each node as execution progresses: the webhook trigger node should show as completed, and the AI triage agent node should show as running or completed.
8. Wait for the AI triage agent node to complete and review the agent's output (triage assessment and recommended action) displayed in the node's result panel.
9. Observe the execution reaching the approval node and pausing — the workflow should show a "waiting for approval" or equivalent status.

**Section 3 — Handle the approval**

10. In the execution view, locate the approval node that is in a waiting state.
11. Review the information presented at the approval step — this should include the AI agent's triage output and recommended remediation action.
12. Click **Approve** to authorize the workflow to proceed with remediation.
13. Observe the execution resuming past the approval node, the switch node routing to the approved branch, and the AAP job template node transitioning to a running state.
14. Wait for the AAP job template node to complete and confirm it shows a success status.

**Section 4 — Inspect final results**

15. Once the workflow execution reaches the resolve node and completes, observe the final execution status (for example, "Completed" or "Resolved").
16. Click through each node in the completed execution view to inspect individual node outputs:
    - Webhook trigger: the raw event payload received
    - AI triage agent: the full agent reasoning and triage result
    - Approval node: the timestamp and identity of the approver
    - Switch node: the branch taken
    - AAP job template node: the link to the job run in AAP and its result
    - Resolve node: the final resolution status
17. Navigate to the AAP job run (via the link in the AAP job template node result or directly in the AAP UI) and confirm the job completed successfully against the RHEL managed node.
18. Return to the AO workflow list and observe that the workflow shows a completed execution count.

### Key Takeaways

- A single webhook POST is all that is needed to initiate a fully automated end-to-end AO workflow — no manual steps are required to start the chain
- The AO monitoring view provides node-level granularity into execution progress, making it straightforward to identify where a workflow is, where it paused, and what each node produced
- The approval gate integrates seamlessly into the execution flow — approvers act directly in the AO interface without switching to a separate ticketing or notification system
- The AAP job template node links AO orchestration back to existing Ansible automation assets, so teams can adopt AO incrementally without rewriting existing playbooks
- Observing the full execution end to end — from event receipt through AI triage, human approval, automated remediation, and resolution — demonstrates the unified value AO delivers over running these steps separately

### Infrastructure Notes

- The test event payload format (JSON structure and field names) is provided in the lab instructions; participants do not need to author the payload from scratch
- The curl command or browser-based HTTP tool for sending the webhook is specified in the lab instructions; no additional tooling installation is required
- The AAP job run triggered by the job template node targets the pre-registered RHEL managed node; participants can observe but do not need to access the RHEL node directly
- Assessment is trust-based — successful observation of the completed execution and resolved incident status in the AO monitoring view is the completion criterion for this module and the lab overall
