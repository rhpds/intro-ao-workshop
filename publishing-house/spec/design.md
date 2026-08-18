# Introduction to Ansible Automation Orchestrator

## Overview

This lab introduces Ansible Automation Orchestrator (AO), the add-on to Red Hat Ansible Automation Platform that unifies task-based, event-driven, and AI-driven automation into a single visual workflow experience. AO is a new capability — practitioners with existing AAP knowledge need guided onboarding to connect AO to the job templates and platform they already use.

Participants log in to a pre-deployed environment, explore the AO interface, configure MCP server and LLM provider integrations, and build a complete incident triage workflow on AO's drag-and-drop canvas. The workflow chains a webhook trigger, an AI triage agent, an approval gate, conditional (switch) routing, and AAP job template nodes to automatically detect, assess, approve, and remediate an incident end to end.

## Target Audience

- **Role:** System Administrators, Automation Administrators, DevOps engineers
- **Experience level:** Beginner
- **What they already know:** Basic awareness of what Ansible Automation Platform does — familiarity with job templates is helpful but not required; no AI experience needed
- **What they don't know:** How to build, configure, and operate workflows in Ansible Automation Orchestrator

## Prerequisites

- Access to a web browser
- Basic awareness of what Ansible Automation Platform does (prior hands-on experience is not required)
- Can the lab validate these automatically? No — trust-based; no automated prerequisite check

## Learning Objectives

1. Explore the Ansible Automation Orchestrator interface and identify its key components
2. Configure credentials and integrations required for AI-powered and event-driven workflows
3. Build an automated incident triage workflow using AO's drag-and-drop canvas
4. Implement approval gates and conditional routing within an AO workflow
5. Integrate an Event-Driven Ansible webhook trigger to initiate an automated workflow
6. Monitor workflow execution in real time and inspect end-to-end results

## Content Type

Lab (hands-on)

## Products & Technologies

- Red Hat Ansible Automation Platform 2.7
- Ansible Automation Orchestrator (GA, deployed as an OCP operator)
- Event-Driven Ansible
- Red Hat OpenShift Container Platform 4.20 (SNO)
- Red Hat Enterprise Linux (managed node)
- Model Context Protocol (MCP) — integrated via AO MCP server node

## Module Map

| Module | Title | Duration |
|--------|-------|----------|
| 1 | Overview and Interface Tour | 20 min |
| 2 | Set Up Integrations and Credentials | 20 min |
| 3 | Build the Workflow | 40 min |
| 4 | Run and Monitor | 20 min |
| — | **Total hands-on** | **100 min** |
| — | Intro / presentation | ~20 min |
| — | **Total lab** | **~120 min** |

## Difficulty Level

Beginner

## Environment

**Learner view:** Participants access a pre-deployed environment consisting of an SNO (Single Node OpenShift) OCP 4.20 cluster running the AO operator and AAP 2.7. A set of AAP job templates for incident remediation scenarios are pre-loaded — participants do not write playbooks. A RHEL managed node is pre-registered in the AAP inventory as the target for job template execution. Participants interact entirely through the AO canvas and AAP UI in a web browser.

**Automation needed:** Yes — the following must be provisioned before the lab starts:
- SNO OCP 4.20 cluster with AO operator installed
- AAP 2.7 with pre-built job templates loaded
- RHEL managed node registered in AAP inventory
- MaaS endpoint (open-source LLM) accessible from AO
- MCP server instance accessible from the AO environment
- Webhook endpoint for EDA trigger simulation

## Infrastructure Requirements

- **Cloud provider:** CNV
- **Cluster type:** SNO (Single Node OpenShift)
- **OCP version:** 4.20
- **Topology:** Per-student (each participant gets an isolated SNO environment)
- **Sizing:** 1 SNO control plane node — 32 vCPU, 128GB RAM; 1 RHEL managed node per student — 2 vCPU, 8GB RAM (pre-registered in AAP inventory as job template target)
- **Automation approach:** Ansible
- **AI/MaaS:** MaaS, open-source model (no justification required)
- **External services:** quay.io, registry.redhat.io, RHDP MaaS endpoint
- **AAP version:** 2.7
- **Non-GA products:** None (AO is GA on 8/21/2026)

## Assessment Strategy (Optional)

Trust-based — no automated solve/validate buttons. Participants confirm success by observing workflow execution results and the final incident resolution status in the AO monitoring view.
