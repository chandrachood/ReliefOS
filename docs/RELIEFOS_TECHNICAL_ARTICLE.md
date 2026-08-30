# Building ReliefOS: An AI-Assisted Disaster Reporting and Rescue Coordination Platform on AWS

**By [Chandrachood Raveendran](https://medium.com/@chandrachoodraveendran)**  
*12 min read* · *Creator & Lead Architect, ReliefOS*  
[Website: chandrachood.in](https://chandrachood.in) · [LinkedIn](https://www.linkedin.com/in/chandrachoodraveendran) · [GitHub: chandrachood/ReliefOS](https://github.com/chandrachood/ReliefOS)

---

**Tags:** `AWS` · `Amazon Bedrock` · `FastAPI` · `Amazon ECS` · `AWS Strands` · `DynamoDB` · `Disaster Response` · `Cloud Architecture`

---

What’s happening in Nepal is a wake-up call for all humanity. Natural disasters are becoming an inevitable, escalating reality of modern human existence. Within minutes, flash floods and debris flows claim hundreds of lives. Infrastructure built over hundreds of years is wiped out in seconds by raging torrents of water and mud. Families are separated, international travelers go missing, and citizens find themselves stranded with zero visibility into who can help or when relief will arrive.

We witnessed this exact tragedy in Wayanad—one of the most breathtaking regions in Kerala—where massive landslides destroyed entire villages and took more than 420 lives. The recurring Kerala floods reflected the exact same painful patterns:

- **People lose track of loved ones**, with families desperately searching for missing relatives across chaotic communication channels.
- **Governments and rescue teams struggle to locate and identify stranded individuals** amid failing phone lines and fragmented distress calls.
- **Victims are unable to access emergency medical support** or reach the right specialized response units in time.
- **Displaced citizens cannot locate active, safe government shelters** or determine if nearby routes are passable.
- **Rescue organizations face logistical paralysis**, lacking a shared operational map to assign teams, coordinate boats, and manage supplies.

During such catastrophic events, we need a **centralized, resilient coordination platform** that can be activated immediately—a system that leverages cloud technology and artificial intelligence to assist governments, first responders, and citizens in navigating chaos. 

We built **ReliefOS** on AWS to solve this exact problem: a cloud-native platform designed to be spun up instantly by disaster management authorities when a calamity strikes, scale elastically to handle massive distress traffic, and scale down when recovery is achieved.

---

## What ReliefOS Provides

ReliefOS is not a generic chatbot or a passive dashboard. It is an end-to-end disaster operations engine engineered to connect every stakeholder across six core capabilities:

1. **Offline-Resilient Citizen Emergency Reporting (Progressive Web App):**
   - Enables victims and bystanders to report emergencies even on degraded 2G connections or intermittent signals.
   - Captures GPS coordinates, number of affected individuals, immediate danger indicators (*rising water*, *unconscious victim*, *building collapse*), and required rescue assistance (*boat*, *medical*, *food/water*).
   - Guarantees **idempotent submissions** so poor-network retries never create duplicate rescue tickets.

2. **Privacy-Preserving HMAC Case Access Tokens:**
   - Issues cryptographically signed, time-decaying tokens to reporting citizens so they can track case updates and upload evidence without having to create formal accounts or exposing their records publicly.

3. **Deterministic Safety Triage Baseline (P0–P4):**
   - Automatically classifies incoming cases into priority tiers (P0 Life-Critical to P4 Informational) using pure-Python deterministic rules that execute in milliseconds and never fail, even if external AI models or networks are down.

4. **Asynchronous AI Triage Enrichment (Amazon Bedrock & AWS Strands):**
   - Evaluates complex, unstructured Malayalam, Tamil, Hindi, or English distress descriptions to extract unstated operational hazards.
   - **Enforces strict safety guardrails:** The AI can escalate a case's priority based on hidden medical cues, but is programmatically prohibited from downgrading priority, closing cases, or rejecting appeals.

5. **Privacy-Safe Missing & Safe Person Registry:**
   - Provides a family assistance portal where relatives can search for displaced loved ones by name or status (*safe*, *at_shelter*, *hospitalized*).
   - Intentionally redacts exact GPS coordinates, phone numbers, and sensitive recovery photos to protect victim safety and prevent exploitation.

6. **Verified Volunteer & Responder Network with Capability Matching:**
   - Manages responder registration, vetting, and capability tracking (*boat rescue*, *medical trauma*, *rope evacuation*).
   - Allows incident commanders to dispatch specialized teams to matching incidents with real-time mission state tracking.

7. **Proximity-Based Government Shelter Directory:**
   - Provides geographic search and capacity monitoring for active relief camps and shelters, assisting displaced families in reaching the nearest safe sanctuary.

8. **Unified Incident Command Operations Dashboard:**
   - Delivers a live, geocoded map and priority case feed with status filtering, operational metrics, and complete audit logging for government coordinators.

---

## The AWS Cloud Architecture

The architecture is built on AWS serverless and container services, keeping case creation lightweight and synchronous while offloading heavy AI and media analysis to asynchronous background workers.

```mermaid
flowchart TB
    subgraph Client Tier
        PWA["Citizen & Responder PWA (Offline-capable)"]
        DASH["Operations Dashboard (Incident Command)"]
    end

    subgraph Edge & Security Tier
        CF["Amazon CloudFront CDN"]
        WAF["AWS WAF (Rate-limiting & DDoS mitigation)"]
        COG["Amazon Cognito (RBAC & User Pools)"]
    end

    subgraph Compute & Ingestion Tier
        ALB["Application Load Balancer"]
        API["FastAPI Backend (Amazon ECS Fargate)"]
    end

    subgraph Asynchronous Worker Tier
        SQS["Amazon SQS + Dead-Letter Queue (DLQ)"]
        WORKER["Triage & Media Worker (Amazon ECS Fargate)"]
        BEDROCK["Amazon Bedrock (Strands Agents Framework)"]
    end

    subgraph Storage & Evidence Tier
        DDB["Amazon DynamoDB (Cases, Responders, Shelters, Audits)"]
        S3["Amazon S3 (Encrypted Photos, Videos, Audio)"]
    end

    Client Tier --> CF --> WAF --> ALB --> API
    Client Tier -. Auth .-> COG
    API --> DDB
    API --> S3
    API --> SQS
    SQS --> WORKER
    WORKER --> BEDROCK
    WORKER --> DDB
```

### AWS Stack Components:
- **Compute:** **Amazon ECS on AWS Fargate** running containerized FastAPI API services and asynchronous background workers.
- **Database:** **Amazon DynamoDB** providing low-latency operational state storage with point-in-time recovery (PITR) and in-memory local fallback for drills.
- **Generative AI:** **Amazon Bedrock** (Foundation models through AWS Strands Agents) with Bedrock Guardrails.
- **Media Evidence:** **Amazon S3** for evidence photos, audio, and video via short-lived presigned URLs.
- **Messaging:** **Amazon SQS** with Dead-Letter Queues (DLQ) for non-blocking task decoupling.
- **Edge & Security:** **Amazon CloudFront**, **AWS WAF**, and **Amazon Cognito** for role-based access control (`citizen`, `responder`, `medical`, `coordinator`).
- **Infrastructure as Code (IaC):** **AWS CDK v2 (Python)** for rapid one-command deployment.

---

## How a Rescue Case Moves Through the System

Let’s trace how a citizen report moves from a low-connectivity phone in a disaster zone to the incident command center.

### 1. Offline-First Capture & Idempotent Submission
When a citizen submits a report, the browser records GPS coordinates, danger indicators, and required assistance. If the connection drops, the report is saved to an IndexedDB offline queue and automatically re-transmitted upon reconnection with a unique `Idempotency-Key` header.

```python
# app/api.py
from fastapi import APIRouter, Header, HTTPException, status
from app.models import CaseCreateRequest, CaseResponse
from app.services import CaseService

router = APIRouter(prefix="/v1/cases", tags=["Cases"])

@router.post("", response_model=CaseResponse, status_code=status.HTTP_201_CREATED)
async def create_emergency_case(
    payload: CaseCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_actor_id: str | None = Header(default="anonymous"),
) -> CaseResponse:
    """
    Synchronously creates or retrieves an emergency case.
    Guarantees that poor network retries never duplicate tickets.
    """
    return await CaseService.create_or_get_case(
        payload=payload,
        idempotency_key=idempotency_key,
        reporter_id=x_actor_id,
    )
```

If a case with that idempotency key already exists in DynamoDB, the API returns the original record immediately without duplicating tickets.

---

### 2. Privacy-Preserving HMAC Access Tokens
To avoid forcing victims in crisis to create usernames and passwords, ReliefOS generates a signed, time-decaying **HMAC-SHA256 Case Access Token**:

```python
# app/auth.py
import hmac
import hashlib
import time

def generate_case_access_token(case_id: str, secret: str, ttl_seconds: int = 86400 * 7) -> str:
    """Generates an HMAC-SHA256 token permitting public case tracking without data leakage."""
    expires_at = int(time.time()) + ttl_seconds
    message = f"case:{case_id}:{expires_at}"
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return f"{message}:{signature}"
```

The reporter can check rescue status and add photos using this token without exposing the ticket to the public search index.

---

### 3. Immediate Deterministic Safety Triage
Before any background job or AI model is contacted, the synchronous API executes pure-Python deterministic safety triage:

```python
# app/triage.py
from app.models import DangerIndicator, PriorityLevel

CRITICAL_INDICATORS = {
    DangerIndicator.CANNOT_BREATHE,
    DangerIndicator.UNCONSCIOUS,
    DangerIndicator.STRUCTURAL_COLLAPSE,
    DangerIndicator.RISING_WATER,
}

def evaluate_deterministic_triage(
    danger_indicators: list[DangerIndicator],
    affected_count: int,
    description: str,
) -> PriorityLevel:
    """
    Deterministic P0-P4 rules executed in-memory. Zero external latency.
    """
    has_critical = any(ind in CRITICAL_INDICATORS for ind in danger_indicators)
    
    if has_critical and DangerIndicator.PEOPLE_TRAPPED in danger_indicators:
        return PriorityLevel.P0  # Life-critical immediate response
    if has_critical or affected_count >= 10:
        return PriorityLevel.P1  # High danger
    if DangerIndicator.PEOPLE_TRAPPED in danger_indicators or affected_count >= 3:
        return PriorityLevel.P2  # Moderate risk
        
    return PriorityLevel.P3  # Standard assistance
```

---

### 4. Asynchronous Bedrock AI Enrichment via Strands
Once the case is stored in DynamoDB, an event is placed onto Amazon SQS. The worker process uses **AWS Strands Agents** to invoke **Amazon Bedrock**:

```python
# app/agent.py
import os
from strands import Agent
from strands.models import BedrockModel
from app.models import BedrockTriageResult

TRIAGE_SYSTEM_PROMPT = """
You are ReliefOS Emergency Triage AI.
Analyze the incident description, extract missing operational facts, assess hazards,
and evaluate if priority escalation is required.
You CANNOT downgrade priority or close cases.
"""

def create_triage_agent() -> Agent:
    model = BedrockModel(
        model_id=os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"),
        temperature=0.1,
    )
    return Agent(
        model=model,
        system_prompt=TRIAGE_SYSTEM_PROMPT,
        output_schema=BedrockTriageResult,
    )
```

#### The Safety Merge Policy
When the Strands agent returns a structured JSON evaluation, the worker enforces the merge policy:

```python
# app/services.py
def merge_triage_assessment(stored_priority: PriorityLevel, ai_priority: PriorityLevel) -> PriorityLevel:
    # Priority enum: P0 (0), P1 (1), P2 (2), P3 (3), P4 (4)
    if ai_priority.value < stored_priority.value:
        logger.info(f"AI escalated priority from {stored_priority.name} to {ai_priority.name}")
        return ai_priority
    # Downgrade attempts are strictly ignored
    return stored_priority
```

---

### 5. Shelter & Responder Capability Matching
ReliefOS pairs verified responder capabilities (e.g., *boat rescue*, *medical trauma*, *rope evacuation*) with case requirements and calculates nearby shelter capacity using in-memory Haversine distance over coarse geographic DynamoDB cells:

```python
# app/services.py
import math

def calculate_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0  # Earth's radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
```

---

## What the Architecture Deliberately Avoids

Engineering for disaster response is defined as much by what you **refuse** to build as what you include:

- **No AI-Autonomous Dispatches:** No bot sends a boat into a raging river; human dispatchers verify team safety.
- **No Synchronous AI in the Critical Path:** Case creation never blocks waiting for an LLM response.
- **No Single Point of Failure:** In-memory fallback adapters allow the entire stack to run locally during simulated drills or offline field deployments.
- **No Unencrypted Evidence:** Photos and audio upload directly to S3 via presigned PUT URLs with byte-size caps, preventing server memory starvation.

---

## The Production & Enterprise Roadmap

While the MVP (v0.1.0) is complete and tested with an 80%+ unit coverage gate, enterprise disaster management requires continuous evolution:

1. **Amazon Location Service & Dynamic GIS:** Integrating real-time flood polygons and road closure layers to verify evacuation route safety.
2. **Two-Way SMS / IVR (AWS End User Messaging):** Enabling citizens with basic feature phones or zero-data connections to submit reports via interactive voice response in regional languages (Malayalam, Tamil, Hindi, Bengali).
3. **Multi-Modal Aerial Reconnaissance:** Ingesting drone and satellite footage via Bedrock Multi-modal and Amazon Rekognition for damage heatmapping.
4. **Active-Active Multi-Region Resilience:** DynamoDB Global Tables and Route 53 latency routing for nationwide continuity.

---

## The Standard for Success in Disaster Tech

In consumer software, success is measured by daily active users, session length, and engagement metrics.

In disaster response software, success is measured by:
- **Resilience under degraded conditions:** Did the report get through over 2G packet loss?
- **Zero false confidence:** Did the system clearly state what is known versus what is unverified?
- **Human empowerment:** Did coordinators get structured, prioritized intelligence faster?

The purpose of ReliefOS is not to replace human rescuers with autonomous algorithms. It is to bring fragmented, chaotic emergency signals together into a structured, dependable lifeline.

---

### Open-Source Repository & Contributions

ReliefOS is an open-source project released under the **Apache 2.0 License**.

- **GitHub:** [https://github.com/chandrachood/ReliefOS.git](https://github.com/chandrachood/ReliefOS.git)
- **Creator & Maintainer:** Chandrachood Raveendran ([chandrachood.in](https://chandrachood.in))
