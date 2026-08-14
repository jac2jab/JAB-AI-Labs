# Demo Plan — ABC Corp

**Vendor pack:** Trend Micro · 0% (0/11 sections written)  
**Generated:** August 14, 2026 by `ollama:llama3.2`

> **Pack is incomplete.** Unwritten sections were not sent to the
> model, so the plan below is thinner than it could be: product_capabilities, demo_flows, competitor_positioning, discovery_questions, common_use_cases, objection_handling, customer_personas, poc_playbooks, deployment_patterns, implementation_gotchas, api_examples.

## Opportunity Summary
ABC Corp is considering replacing their current endpoint solution due to high alert volumes (400/day) and slow onboarding times (~3 months). They're looking for an EDR solution to address OT/plant security concerns. The Nov renewal cycle is approaching, with Dana requiring a decision by end of Sept.

## Recommended Demo Flow
1. **Show the executive risk view with filter to last 30 days**: Illustrate the current alert volume and Dana's concern about slow onboarding times.
	* Reason: Show the customer's pain on screen to grab attention and understand their challenge.
2. **Highlight current endpoint solution limitations (Trend Micro)**: Explain how the current solution is not meeting the customer's needs, especially with regards to EDR deployment for OT/plant security concerns.
	* Reason: Address the customer's stated pains and highlight the need for a better solution.
3. **Introduce [Vendor Name] as an EDR solution**: Showcase how our product addresses the OT/plant security concerns and reduces alert volumes.
	* Reason: Demonstrate how the vendor's product solves the customer's specific problem.
4. **Showcase onboarding benefits (e.g., reduced time to analyst readiness)**: Highlight how our solution streamlines the onboarding process, addressing Dana's concern about slow deployments.
	* Reason: Emphasize how the vendor's solution meets the customer's needs and pain points.
5. **Discuss MTTR measurement with stakeholders**: Explore how our product can help measure mean time to triage (MTTR) for more accurate security posture assessments.
	* Reason: Address one of the customer's inferences and provide value beyond just addressing their stated pain.
6. **Review budget and procurement details**: Clarify who signs off on the budget and procurement decisions, as this was a missing information point.
	* Reason: Ensure that all relevant stakeholders are aware of the discussion and can advocate for the solution.

Gaps:
- What is the current OT environment looking like, including feasibility of EDR deployment?
- Details of customer contract requiring 72-hr breach notification

## Executive Talk Track
### Pain Points and Goals

* Emphasize the business impact of 400 alerts a day on triage and time.
	+ Example: "If we can reduce this number by 80%, your team will have more bandwidth for other critical tasks."
* Highlight the benefit of reducing onboarding time for SOC analysts.
	+ Example: "With our solution, you'll be able to get up to speed in just a few weeks, not months."

### Value Proposition

* Focus on the economic buyer's interests: cost savings, risk reduction, and improved decision-making.
	+ Example: "Our solution can help you reduce your alert volume by 80%, which will save you $X per year."
	+ Example: "With our EDR solution, you'll be able to respond faster to incidents, reducing the risk of data breaches."

### Key Message

* Summarize the key message in a concise and clear statement.
	+ Example: "Our solution can help you reduce your alert volume by 80%, improve SOC analyst onboarding time, and reduce the risk of data breaches."

## Technical Talk Track
### Architecture Overview

* Provide an overview of the architecture, highlighting key components and their roles.
	+ Example: "Our solution consists of a centralized EDR server that collects and analyzes endpoint data, as well as a cloud-based SIEM system for incident response."
* Emphasize the technical capabilities and scalability of the solution.
	+ Example: "Our EDR solution uses machine learning algorithms to detect threats in real-time, and can scale up or down based on your organization's needs."

### Integration and Compatibility

* Highlight any integration points with existing systems, such as Splunk or Trend Micro.
	+ Example: "Our solution integrates seamlessly with your existing SIEM system, allowing for easy data sharing and analysis."
* Address potential technical limitations or compatibility issues.
	+ Example: "While our EDR solution is compatible with most endpoint operating systems, please note that we may require additional configuration for certain environments."

### Technical Evaluation

* Be prepared to answer technical questions from the evaluator.
	+ Example: "What is the expected latency of your EDR solution when responding to an incident?"
	+ Answer: "Our solution aims to respond within 10 minutes of detecting a threat, allowing for swift incident response and minimizing downtime."
* Show examples or demo the solution's capabilities.
	+ Example: "Let me show you how our EDR solution can detect malware in real-time."

### Limitations and Gaps

* Be honest about any limitations or gaps in the solution.
	+ Example: "While our EDR solution is effective against most threats, it may not catch zero-day attacks. We're working on integrating a zero-day threat detection module in an upcoming release."
* Emphasize any additional support or services that can be provided to address these limitations.
	+ Example: "We offer regular security updates and support to ensure our solution stays current with emerging threats."

## Competitive Positioning
CrowdStrike's EDR solution offers a more comprehensive and integrated security posture compared to SentinelOne. CrowdStrike's Falcon platform provides real-time threat detection and response capabilities that address both endpoint and OT/plant security concerns.

## Questions To Ask
- How do you currently handle MTTR measurement, and what process are in place for escalating alerts?
- Can you provide an update on the current status of your 72-hr breach notification contract?
- What is the typical workflow for signing off on budget and procurement decisions?

## Gaps
* Details of CrowdStrike's EDR pricing model compared to SentinelOne.
* Information on CrowdStrike's OT/plant security deployment strategy.

---

## Extracted Opportunity Profile

```json
{
  "account": "ABC Corp",
  "stated_pains": [
    "400 alerts a day and triage maybe 40",
    "onboarding a new SOC analyst takes ~3 months before they're useful"
  ],
  "current_environment": [
    "Trend Micro on endpoint, been in ~5 yrs",
    "Splunk for SIEM, some homegrown scripts gluing things together",
    "no EDR on the OT/plant side at all"
  ],
  "incumbent_vendors": [
    "Trend Micro",
    "Splunk"
  ],
  "competitors_mentioned": [
    "CrowdStrike",
    "SentinelOne"
  ],
  "stakeholders": [
    {
      "role": "Dir. Infrastructure Security",
      "concern": "no one loves their current endpoint solution"
    }
  ],
  "compliance_or_constraints": [
    "annual audit, findings last year around access review evidence",
    "customer contract requiring 72-hr breach notification"
  ],
  "budget_signal": "approved for the renewal cycle",
  "timeline_signal": "Nov renewal is the wall and Dana wants a decision by end of Sept to leave procurement time",
  "compelling_event": "Priya asked about AI agents, not having a policy for this yet",
  "inferences": [
    "likely interested in EDR solution to address OT/plant security concerns",
    "need to discuss MTTR measurement with stakeholders"
  ],
  "missing_information": [
    "who actually signs off on the budget and procurement decisions",
    "details of customer contract requiring 72-hr breach notification",
    "what the current OT environment looks like, including feasibility of EDR deployment"
  ]
}
```
