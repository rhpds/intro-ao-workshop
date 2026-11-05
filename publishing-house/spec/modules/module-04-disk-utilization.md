# Module 04 — Disk Utilization Remediation

### Brief Overview

Participants complete a partially built Disk Utilization Remediation workflow that uses a webhook trigger, an AAP job template to check disk usage, and a switch step to route execution down one of four paths based on the utilization percentage. Three of the four switch routes are already configured; participants add the two missing steps in the critical (>95%) route — a remediation job template step and a Mattermost notification step — by using the adjacent 80–95% route as a reference. The workflow is published before any alert is fired so the webhook trigger is active, and participants run all routes to confirm correct branching and Mattermost notifications.

### Audience and Time

- **Target personas:** System Administrators, Automation Administrators, DevOps engineers
- **Experience level:** Beginner
- **Prerequisites for this module:** Module 03 complete; Disk Utilization Remediation workflow present in the default project
- **Estimated duration:** 15 minutes

### Learning Objectives

- Explain how a webhook trigger integrates with an external system (AAP) to start a workflow
- Read an existing switch step configuration and understand how route conditions are evaluated
- Add an AAP job template step to an incomplete route, referencing output from an upstream step
- Add a Mattermost notification step to complete the remediation route
- Publish a workflow before firing a webhook and explain why the order matters
- Run a workflow through multiple switch routes and verify the correct path is taken for each utilization threshold

### Lab Structure

| Section | Title | Duration |
|---------|-------|----------|
| 1 | Publish the workflow | 2 min |
| 2 | Fire a healthy alert and inspect output | 3 min |
| 3 | Add the critical-route remediation step | 5 min |
| 4 | Add the critical-route notification step | 3 min |
| 5 | Run the workflow through all routes | 2 min |

### Detailed Steps

**Section 1 — Publish the workflow**

1. Log in to AO, open Workflows, confirm Project selector reads default, and click Disk Utilization Remediation.
2. Click Publish workflow. Confirm the Draft badge becomes Published.

**Section 2 — Fire a healthy alert and inspect output**

3. Switch to the AAP tab. Open Automation Execution → Templates and find Disk Utilization Simulate Alert.
4. Launch the template with the scenario variable set to simulate a healthy (<80%) disk reading. This fires a webhook to the AO workflow and runs the healthy route.
5. Return to AO, open the workflow run, and inspect the disk check step's output. Note the utilization fields — these will be available to reference when configuring the critical route steps.

**Section 3 — Add the critical-route remediation step**

6. Return to the canvas. Locate the switch step and find the >95% (critical) route — the one with two steps missing.
7. Examine the 80–95% route directly above it; note its two-step pattern: a remediation AAP job template step followed by a Mattermost notification step.
8. On the critical route, click the + to add a step. Choose AAP Execution → Launch AAP job template.
9. Configure the step following the same pattern as the 80–95% remediation step: set Integration to AAP, connect the AAP credential, choose the appropriate Linux job template for critical disk cleanup, and reference the upstream disk check output fields in Extra variables.

**Section 4 — Add the critical-route notification step**

10. Click the + after the remediation step on the critical route. Add a Mattermost notification step.
11. Configure the notification following the pattern of the 80–95% notification step: set the Mattermost channel and compose a message referencing the disk check output and the remediation result.
12. Click Save workflow.

**Section 5 — Run the workflow through all routes**

13. In AAP, run Disk Utilization Simulate Alert with a warning (80–95%) scenario and confirm the workflow takes the warning route and posts a notification to Mattermost.
14. Run the template again with a critical (>95%) scenario. Confirm the workflow takes the critical route, executes the remediation, and posts a notification.
15. In Mattermost, verify that notifications from both runs have arrived in the expected channel.

### Key Takeaways

- A webhook trigger only starts answering requests once the workflow is published; publishing before firing any alert is a required step
- A switch step evaluates a value from an upstream step and directs execution down the first route whose condition matches; unmatched cases fall to the fallback route
- Existing, running steps produce real output that becomes available to reference in new steps; firing a healthy alert first makes the disk check fields available when configuring the critical route
- The remediate-then-notify pattern used in every route separates the operational action (fix the problem) from the communication action (tell someone it happened)

### Infrastructure Notes

- The Disk Utilization Remediation workflow is pre-deployed in the default project with three of four routes configured; participants only add steps to the critical route
- Disk Utilization Simulate Alert is a pre-built AAP job template; participants launch it but do not modify it
- Mattermost is pre-deployed and accessible from the Showroom tab; the channel and credentials are provided in the lab environment details
