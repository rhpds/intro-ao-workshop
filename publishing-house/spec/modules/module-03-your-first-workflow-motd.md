# Module 03 — Your First Workflow: Message of the Day

### Brief Overview

Participants build a three-step workflow from an empty canvas: a manual trigger that collects a note from the person running it, a task agent that turns the note into properly worded banner text (headline, notice, owning team), and an AAP job template step that writes the agent's output into /etc/motd on a real RHEL host. The module demonstrates the core AO workflow authoring loop — configure a step, run it in isolation to get real output, copy output expressions into the next step — and ends with participants SSHing into a managed node to see the banner in place. The workflow is then published.

### Audience and Time

- **Target personas:** System Administrators, Automation Administrators, DevOps engineers
- **Experience level:** Beginner
- **Prerequisites for this module:** Module 02 complete; Student LLM and Student AAP MCP Server integrations in Available status; Student LLM Credential and Student AAP MCP Credential in the default project
- **Estimated duration:** 15 minutes

### Learning Objectives

- Create a workflow from an empty canvas and assign it to a project
- Configure a manual trigger with a typed input field and understand how trigger input is referenced downstream using the ${trigger.<field>} expression
- Configure a task agent step with an LLM model, a credential, a natural-language prompt referencing trigger input, and a JSON response schema
- Run a step in isolation to produce real output and explain why this is required before wiring steps together
- Add an AAP job template step, configure its credential and integration, and wire task agent output fields into job template extra variables using copied expressions
- Run the full workflow end to end and confirm the MOTD banner appears on the managed RHEL node
- Publish a workflow and distinguish the Published state from a Draft

### Lab Structure

| Section | Title | Duration |
|---------|-------|----------|
| 1 | Create the workflow and configure the trigger | 3 min |
| 2 | Add and configure the task agent | 4 min |
| 3 | Run the agent in isolation | 2 min |
| 4 | Add the AAP job template step and wire inputs | 4 min |
| 5 | Run the workflow and verify the banner | 2 min |

### Detailed Steps

**Section 1 — Create the workflow and configure the trigger**

1. Log in to AO, open Workflows, and click Create workflow. Name the workflow Message of the Day and set Project to default.
2. Select Manual trigger to open the trigger configuration panel.
3. In the trigger's Input schema (set to Simple), click Add field. Set Field name to banner_request, Type to String, and tick Required. Click Create.

**Section 2 — Add and configure the task agent**

4. Click the + on the right edge of the Trigger step and choose Task Agent.
5. Open the Model dropdown and select Student LLM / qwen3-235b.
6. In the Credential section click Set up connection and select Student LLM Credential.
7. Type the prompt, referencing trigger input with ${trigger.banner_request}. Leave Tools set to No tools selected.
8. Paste the response schema defining three required string fields: headline, notice, owner. Click Create.

**Section 3 — Run the agent in isolation**

9. Open the Task Agent step and click Run step. Click Set mock data.
10. Paste a sample banner note into the banner_request field and click Run.
11. After the agent completes, review the final_answer block in the Output panel to confirm headline, notice, and owner fields are present. Click Update.

**Section 4 — Add the AAP job template step and wire inputs**

12. Click the + on the right edge of the Task Agent step, choose AAP Execution → Launch AAP job template.
13. Set Integration to AAP, click Set up connection, and select Ansible Automation Platform.
14. Set Organization to Default and choose the Linux - Set Message of the Day job template.
15. In Extra variables, type a skeleton JSON object with motd_headline, motd_notice, and motd_owner keys and empty values.
16. Open the Input panel on the Launch AAP job template step. Hover over headline and click the copy icon. Paste the copied expression between the quotes after motd_headline. Repeat for notice → motd_notice and owner → motd_owner. Click Update.
17. Click Save workflow.

**Section 5 — Run the workflow and verify the banner**

18. Click Run → Run now. Supply a banner note when the trigger prompts for input and click Run.
19. Watch the run details panel: trigger finishes immediately, task agent takes ~20 s, AAP job takes ~10 more. All three steps should end Successful.
20. Switch to the Terminal tab and run ssh node1. After accepting the host fingerprint and entering the lab password, confirm the MOTD banner prints before the shell prompt, displaying the agent's headline and notice alongside the host's own facts.
21. Return to the canvas and click Publish workflow. Confirm in the dialog. The Draft badge becomes Published.

### Key Takeaways

- A workflow is a trigger plus steps; the trigger lives on the canvas with everything else and ${trigger.<field>} reaches its input from anywhere in the workflow
- A response schema turns an agent from something that writes prose into something the next step can consume; the field names chosen in the schema are the output contract
- Run a step before connecting its output: once a step has produced real output, AO lets you copy the expressions you need instead of typing them manually
- Automation Orchestrator decides; Ansible Automation Platform executes — the agent chose the words, a deterministic AAP job template put them on a real server next to facts it measured itself

### Infrastructure Notes

- The Linux - Set Message of the Day job template and the RHEL managed nodes are pre-provisioned; participants do not write or modify any playbook
- The Student AAP MCP Credential and Student LLM Credential created in Module 02 must be in the default project; the job template and agent steps require them
- SSH access to node1 and node2 is available from the Showroom terminal tab using lab-user credentials
