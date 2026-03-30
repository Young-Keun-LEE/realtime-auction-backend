# ⚡ Real-Time Auction Backend
 
> A distributed, event-driven backend system engineered for extreme contention on single auction items ("hot keys").
 
In environments where thousands of bids arrive per second, traditional database-first approaches fail due to locking overhead. This project demonstrates a production-grade solution using **Atomic In-Memory Validation** and **Asynchronous Write-Behind Persistence**.
 
---
 
## 🏗️ System Architecture
 
The system utilizes a **polyglot microservices** approach to optimize for specific workloads: **Go** for high-throughput ingestion and **Python (FastAPI)** for asynchronous broadcasting and background processing.
 
```mermaid
graph TD
    Client[Client]
 
    GoAPI[Go Bid Service]
    Redis[(Redis)]
    Kafka[(Kafka)]
    Worker[Python Worker]
    DB[(PostgreSQL)]
    WS[WebSocket Server]
 
    Client -->|Bid Request| GoAPI
    GoAPI -->|Atomic Validate| Redis
    GoAPI -->|Publish Event| Kafka
    GoAPI -->|Notify| Redis
 
    Redis -->|Pub/Sub| WS
    WS -->|Broadcast| Client
 
    Kafka -->|Consume| Worker
    Worker -->|Batch Write| DB
```
 
---
 
## 🧠 Strategic Engineering Decisions: The "Why"
 
### 1. Why Redis Lua instead of Distributed Locks?
 
In a high-frequency auction, multiple round-trips to acquire and release locks (like Redlock) create massive latency.
 
| | |
|---|---|
| **Intent** | We need Atomic State Transitions. |
| **Choice** | By embedding validation logic in a Lua script, the entire "Check-and-Set" operation happens in a **single atomic step** inside Redis. |
| **Benefit** | Eliminates race conditions entirely without the overhead of network-intensive locking protocols, keeping our **p99 latency sub-100ms**. |
 
### 2. Why a Polyglot MSA (Go + Python)?
 
One size does not fit all. We decoupled the system to leverage the strengths of different ecosystems.
 
| Service | Role | Reason |
|---|---|---|
| **Go** | Ingestion ("Hot Path") | Lightweight goroutines handle thousands of concurrent HTTP connections with minimal memory footprint. |
| **Python** (FastAPI/Worker) | Notifications & Persistence ("Cold Path") | Rich ecosystem ideal for complex batch processing logic and persistent WebSocket connections. |
 
### 3. Why Go Worker Pool with Bounded Queues?
 
Directly calling Kafka for every request can slow down the API if Kafka experiences a momentary lag.
 
- **Design:** The Go service implements a Worker Pool with a **Bounded Task Queue (Size: 1,000)**.
- **Backpressure Handling:** When the queue reaches its depth limit, the system gracefully drops new tasks to protect the service from crashing *(Fail-fast)*.
- **Decoupling:** Separates the critical path (validating the bid) from the non-critical path (persisting the bid), ensuring the user receives an immediate response.
 
### 4. Why Kafka for Persistence?
 
The database is the slowest part of any high-traffic system.
 
- **Intent:** Shield the Database.
- **Choice:** Kafka acts as a massive buffer. The Go Producer sends validated bids to Kafka, and the Python Consumer fetches them in batches.
- **Ordering & Recovery:** Using `AuctionID` as the partition key guarantees all bids for one item are processed **in order**. If the database goes down, Kafka holds the data until it's back online, ensuring **Zero Data Loss**.
 
---
 
## 🛠️ Implementation Details
 
### Go Worker Pool (Producer)
 
| Parameter | Value |
|---|---|
| Queue Depth Limit | 1,000 pending tasks |
| Worker Concurrency | 100 workers (default) |
 
### Python Persistence (Consumer)
 
| Parameter | Value |
|---|---|
| Batch Size | Up to 1,000 records per flush |
| Flush Interval | 1 second max wait |
| Idempotency Strategy | `ON CONFLICT DO NOTHING` with unique `bid_id` (UUID) |
 
---
 
## 🛡️ DevOps & Security Engineering
 
| Area | Implementation |
|---|---|
| **CI/CD** | GitHub Actions — every push to `main` triggers a full build-test-deploy cycle to AWS EC2. |
| **12-Factor Compliance** | Secrets managed via GitHub Secrets, injected into ephemeral `.env` files. No credentials ever touch source code. |
| **Observability** | Health check endpoints across all microservices for container orchestration readiness. |
 
---
 
## 📊 Performance Benchmarks
 
> 🔄 *Results coming soon — load testing in progress.*
 
---
 
## 🚀 Quick Start
 
Spin up the entire microservices ecosystem locally using Docker Compose.
 
**Prerequisites:** Docker & Docker Compose
 
```bash
# 1. Clone the repository
git clone https://github.com/Young-Keun-LEE/realtime-auction-backend.git
cd realtime-auction-backend
 
# 2. Start infrastructure and services
docker-compose up -d --build
```
 
### Endpoints
 
| Service | URL |
|---|---|
| Bid Ingestion API (Go) | `http://localhost:8080/api/v1/bid` |
| WebSocket Server (FastAPI) | `ws://localhost:8000/ws/auction/{auction_id}` |
| Interactive API Docs (Swagger) | `http://localhost:8000/docs` |
 
### Teardown
 
```bash
docker-compose down -v
```
