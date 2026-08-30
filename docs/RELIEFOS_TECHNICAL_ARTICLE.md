# Building ReliefOS: An AI-Assisted Disaster Reporting and Rescue Coordination Platform on AWS

**By Chandrachood Raveendran**  
*Creator & Lead Architect, ReliefOS*  
[Website: chandrachood.in](https://chandrachood.in) · [LinkedIn](https://www.linkedin.com/in/chandrachoodraveendran) · [GitHub: chandrachood/ReliefOS](https://github.com/chandrachood/ReliefOS)

---

**Tags:** `AWS` · `Amazon Bedrock` · `FastAPI` · `Amazon ECS` · `AWS Strands` · `DynamoDB` · `Disaster Response` · `Cloud Architecture`

---

During a sudden flood or landslide, emergency coordination breaks down in predictable ways. Official helpline phone numbers get overwhelmed within minutes, cell towers drop packets intermittently, and frantic distress calls arrive in fragments: 

> *"Three people are trapped on the upper floor near the old bridge in Wayanad. Water is rising fast. An elderly person is unconscious."*

That single distress message contains several life-critical variables. How many victims are involved? What is the immediate life threat? Are they mobile? Can a standard evacuation vehicle reach them, or is an inflatable rescue boat required? Is the report a duplicate of a call received three minutes ago from a neighbor?

In the current era of generative AI, a foundation model can easily read that paragraph and write a sympathetic, articulate response. But **fluency is not emergency logistics.** 

An AI model that hallucinates coordinates, misinterprets water levels, or silently downgrades a trapped family’s priority can cost human lives. Emergency response requires **deterministic life-safety guarantees**, **strict human authority**, and **fail-safe cloud infrastructure**.

This article explains the engineering principles, AWS cloud architecture, and Python implementation behind **ReliefOS**—an open-source, cloud-native disaster reporting and rescue coordination operating system built on AWS.

---

## 1. The Core Engineering Mandate: Safety Before Synthesis

When designing ReliefOS, we established non-negotiable safety boundaries:

1. **Deterministic Baseline:** P0–P4 priority triage is governed by deterministic rules in application code. If Amazon Bedrock, external APIs, or the worker fleet are completely offline, the system continues to triage cases with 100% reliability.
2. **Asymmetric AI Authority:** An AI agent on Amazon Bedrock can enrich reports and recommend **escalating** a case's priority (e.g., P2 $\rightarrow$ P1 based on subtle medical cues in unstructured text), but it is programmatically **prohibited from downgrading priority, closing a case, or rejecting an appeal.**
3. **No Autonomous Dispatch:** Software never dispatches boats, drones, helicopters, or field personnel. Only verified human coordinators hold operational authority.
4. **Idempotency & Offline Resilience:** Distress calls submitted over fluctuating 2G/3G networks must never create duplicate operational records or fail silently.

---

## 2. The Cloud Architecture on AWS

The architecture separates rapid, synchronous case ingestion from compute-intensive media analysis and asynchronous AI enrichment.

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

### Key AWS Components:
- **Client Tier:** A lightweight, installable Progressive Web App (PWA) equipped with an IndexedDB offline queue and client-side GPS geocoding.
- **Edge & Security:** **Amazon CloudFront** and **AWS WAF** protect the public endpoint against DDoS surges while accelerating global asset delivery. **Amazon Cognito** enforces Role-Based Access Control (`citizen`, `responder`, `medical`, `coordinator`).
- **Compute (API & Worker):** Containerized Python services running on **Amazon ECS with AWS Fargate** (serverless containers).
- **Storage:** **Amazon DynamoDB** serves as the low-latency single-digit millisecond state store, backed by **Amazon S3** for evidence media using presigned URLs.
- **Asynchronous Pipeline:** **Amazon SQS** decouples case intake from AI processing. An asynchronous ECS worker pulls messages and coordinates reasoning through **AWS Strands Agents** on **Amazon Bedrock**.

---

## 3. How an Emergency Case Moves Through ReliefOS

Let’s trace the lifecycle of a rescue request from citizen input to field dispatch.

### Step 1: Offline-First Capture & Idempotent Submission
When a citizen opens the PWA, GPS coordinates and danger indicators are captured. If cellular data cuts out, the report is buffered locally. Upon reconnection, the PWA transmits the payload with a unique `Idempotency-Key` header.

```python
# app/api.py (FastAPI Endpoint)
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

If the database already contains a record matching the `Idempotency-Key`, the stored case is returned immediately with HTTP 200 rather than re-inserting a new ticket.

---

### Step 2: Privacy-Preserving HMAC Access Tokens
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

This token allows the reporter to track status updates, add photos, or cancel the report without exposing sensitive victim records to the broader internet.

---

### Step 3: Immediate Deterministic Safety Triage
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

### Step 4: Asynchronous Bedrock AI Enrichment via Strands
Once the case is durably stored in DynamoDB, an event is placed onto Amazon SQS. The worker process uses **AWS Strands Agents** to invoke **Amazon Bedrock**:

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

### Step 5: Shelter & Responder Matching
Incident coordinators view cases on a live map dashboard. ReliefOS supports capability-based responder matching (e.g., matching inflatable boat rescue teams with submerged flood zones) and proximity-based shelter calculations:

```python
# app/services.py (Haversine Distance Calculator)
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

## 4. Privacy-Safe Family Assistance Search

During major crises, relatives flood networks seeking information on loved ones. ReliefOS includes a dedicated **Missing & Safe Person Registry**.

To prevent exploitation and protect victim dignity, the public search API deliberately sanitizes output:
- **Exposed:** Name, Age, Status (`safe`, `at_shelter`, `hospitalized`), and General Area (e.g., *"Kalpetta District Shelter"*).
- **Redacted:** Exact GPS latitude/longitude, caller phone numbers, medical triage notes, and sensitive recovery photos.

---

## 5. What the Architecture Deliberately Avoids

Engineering for disaster response is defined as much by what you **refuse** to build as what you include:

- **No AI-Autonomous Dispatches:** No bot sends a boat into a raging river; human dispatchers verify team safety.
- **No Synchronous AI in the Critical Path:** Case creation never blocks waiting for an LLM response.
- **No Single Point of Failure:** In-memory fallback adapters allow the entire stack to run locally during simulated drills or offline field deployments.
- **No Unencrypted Evidence:** Photos and audio upload directly to S3 via presigned PUT URLs with byte-size caps, preventing server memory starvation.

---

## 6. The Production & Enterprise Roadmap

While the MVP (v0.1.0) is complete and tested with an 80%+ unit coverage gate, enterprise disaster management requires continuous evolution:

1. **Amazon Location Service & Dynamic GIS:** Integrating real-time flood polygons and road closure layers to verify evacuation route safety.
2. **Two-Way SMS / IVR (AWS End User Messaging):** Enabling citizens with basic feature phones or zero-data connections to submit reports via interactive voice response in regional languages (Malayalam, Tamil, Hindi, Bengali).
3. **Multi-Modal Aerial Reconnaissance:** Ingesting drone and satellite footage via Bedrock Multi-modal and Amazon Rekognition for damage heatmapping.
4. **Active-Active Multi-Region Resilience:** DynamoDB Global Tables and Route 53 latency routing for nationwide continuity.

---

## 7. The Standard for Success in Disaster Tech

In consumer software, success is measured by daily active users, session length, and engagement metrics. 

In disaster response software, success is measured by:
- **Resilience under degraded conditions:** Did the report get through over 2G packet loss?
- **Zero false confidence:** Did the system clearly state what is known versus what is unverified?
- **Human empowerment:** Did coordinators get structured, prioritized intelligence faster?

ReliefOS was built to ensure that when disaster strikes, technology serves as an unwavering, transparent lifeline.

---

### Open-Source Repository & Contributions

ReliefOS is open-source under the **Apache 2.0 License**.

- **GitHub:** [https://github.com/chandrachood/ReliefOS.git](https://github.com/chandrachood/ReliefOS.git)
- **Architect & Maintainer:** Chandrachood Raveendran ([chandrachood.in](https://chandrachood.in))
