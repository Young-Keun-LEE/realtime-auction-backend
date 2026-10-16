# ⚡ Real-Time Auction Backend
 
> A distributed, event-driven backend prototype designed to explore concurrency control and asynchronous persistence in real-time auction systems.
 
This project uses Redis Lua scripts for atomic bid validation and price updates, alongside Kafka-based asynchronous persistence and batched PostgreSQL writes. It also includes a bounded Go worker pool, WebSocket notifications, and local load testing to evaluate system behavior under concurrent workloads.
 
---
 
## 🏗️ System Architecture
 
The system utilizes a **polyglot microservices** approach to optimize for specific workloads: **Go** for high-throughput ingestion and **Python (FastAPI)** for asynchronous broadcasting and background processing.
 
```mermaid

graph TD
    Client[Client]
    GoAPI[Go Bid Service]
    Pool[Bounded Go Worker Pool]
    Redis[(Redis)]
    Kafka[(Kafka)]
    Worker[Python Persistence Worker]
    DB[(PostgreSQL)]
    WS[FastAPI WebSocket Server]

    Client -->|Bid Request| GoAPI
    GoAPI -->|Validate Bid| Redis
    GoAPI -->|Submit Task| Pool
    Pool -->|Publish Event| Kafka
    Pool -->|Publish Notification| Redis
    Redis -->|Pub/Sub| WS
    WS -->|Broadcast| Client
    Kafka -->|Consume Events| Worker
    Worker -->|Batch Insert| DB

```

 
---
 
## 🧠 Strategic Engineering Decisions: The "Why"
 
### 1. Why Redis Lua instead of Distributed Locks?
 
In a high-frequency auction, multiple round-trips to acquire and release locks (like Redlock) create massive latency.
 
| | |
|---|---|
| **Intent** | We need Atomic State Transitions. |
| **Choice** | By embedding validation logic in a Lua script, the entire "Check-and-Set" operation happens in a **single atomic step** inside Redis. |
| **Benefit** | Combines bid validation and price updates into a single atomic Redis script execution, preventing concurrent operations from interleaving within the script. |
 
### 2. Why a Polyglot MSA (Go + Python)?
 
One size does not fit all. We decoupled the system to leverage the strengths of different ecosystems.
 
| Service | Role | Reason |
|---|---|---|
| **Go** | Ingestion ("Hot Path") | Lightweight goroutines handle thousands of concurrent HTTP connections with minimal memory footprint. |
| **Python** (FastAPI/Worker) | Notifications & Persistence ("Cold Path") | Rich ecosystem ideal for complex batch processing logic and persistent WebSocket connections. |
 
### 3. Why Go Worker Pool with Bounded Queues?
 
Directly calling Kafka for every request can slow down the API if Kafka experiences a momentary lag.
 
- **Design:** The Go service implements a Worker Pool with a **Bounded Task Queue (Size: 1,000)**.
- **Queue Saturation:** When the queue is full or the request context is canceled, task submission may be dropped. The current implementation logs these events but does not propagate submission failures to the HTTP handler.
- **Decoupling:** Separates bid validation from asynchronous event publishing and downstream processing, reducing the need for the HTTP handler to perform these operations synchronously.
- **Limitation:** Dropped tasks and Kafka publishing failures are not automatically retried by the current worker pool. The system does not guarantee that every accepted bid is persisted.
 
### 4. Why Kafka for Persistence?
 
The database is the slowest part of any high-traffic system.
 
- **Intent:** Shield the Database.
- **Choice:** Kafka acts as a massive buffer. The Go Producer sends validated bids to Kafka, and the Python Consumer fetches them in batches.
- **Duplicate Protection:** A unique bid UUID and ON CONFLICT DO NOTHING prevent duplicate database inserts for the same bid ID.
- **Failure Handling:** The consumer uses manual offset commits, committing after successful database processing. Failed database operations can therefore be retried through message redelivery, subject to consumer behavior and Kafka retention.
- **Limitations:** The current producer configuration does not guarantee partition assignment by auction ID or per-auction message ordering. End-to-end zero-data-loss delivery is not guaranteed because tasks may be dropped before successful publication to Kafka.
 
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
| **CI / CD** | **GitHub Actions** — Builds Go and Python service images and pushes them to Docker Hub on pushes to main. Automated cloud deployment is not currently enabled.* |
| **Local Infrastructure** | **Docker Compose** — Runs the application services and supporting infrastructure locally, including Redis, Kafka, and PostgreSQL. The Compose setup provides a reproducible local development environment. |
| **Observability** | **Prometheus & Grafana** — Exposes application metrics for monitoring and visualizing behavior under load. Health-check endpoints support service health monitoring. |
---
 
## 📊 Performance Benchmarks

> Load test conducted with **Locust** (1,000 concurrent users) against the Go Bid Ingestion API.  
> Infrastructure monitored in real-time via **Grafana + Prometheus**.  
> ⚠️ **Test Environment**: All benchmarks were conducted on a local machine (not a production-grade
> cloud environment). Results reflect the system's architectural efficiency rather than absolute
> throughput capacity. Cloud deployment benchmarks are planned.
### Benchmark Screenshots

### Grafana Monitoring Dashboard

![Grafana Dashboard](./images/Grafana.png)

### Locust Load Test

![Locust Benchmark](./images/Locust.png)
### Load Test Summary

| Metric | Result |
|---|---|
| **Concurrent Users** | 1,000 |
| **Sustained RPS** | ~300.9 req/s |
| **Failure Rate** | 0% |
| **p99 Latency (Go Bid API)** | ~4.95 ms |
| **p95 Latency (Go Bid API)** | ~4.75 ms |
| **p95 Ramp-up Spike** | ~32 ms (stabilizes within ~2 min) |
| **Avg Response Time (stable)** | < 2 ms |
| **Redis Hot-Key Throughput** | ~595–610 ops/s |
| **Kafka Consumer Lag (max)** | 4 messages |
| **PostgreSQL Active Connections** | ≤ 2 |
| **PostgreSQL TPS** | ~100 tps |
| **5xx Error Rate** | 0 |

### Key Observations

- **Zero failures** across the entire ~8-minute sustained load test at 1,000 concurrent users.
- **Sub-5ms p99** held consistently after ramp-up, validating that atomic Lua + in-memory
  validation is not the bottleneck at this load level.
- **Ramp-up spike reduced to ~32ms** (from ~40ms in previous run) — consistent with Go Worker
  Pool saturation resolving as goroutines catch up, not a Redis or DB issue.
- **Kafka Consumer Lag capped at 4 messages** — Python worker maintained pace with the Go
  producer under sustained 300+ RPS.
- **PostgreSQL shielded entirely from bid traffic** — only ≤2 active connections and ~100 TPS
  observed, confirming the Kafka write-behind buffer absorbed all load as designed.
- **Redis memory stable** at 1.58–1.64 MB with no unbounded growth throughout the test.

### Bottleneck Analysis

| Component | Assessment | Rationale |
|---|---|---|
| **Go Worker Pool → Kafka produce** | Primary bottleneck candidate | Bounded queue (1,000) triggers fail-fast under burst; visible as p95 spike (~32ms) during ramp-up before stabilizing |
| **Python Worker → PostgreSQL** | Secondary bottleneck | Batch flush interval (1s) couples DB write latency to Kafka lag oscillation (0–4 msgs) |
| **Redis Lua hot-key** | Not a bottleneck | Throughput stable at ~595–610 ops/s; single-step atomic operation completes in microseconds |

> The ramp-up spike followed by rapid stabilization under 5ms is the key signal:
> it indicates Worker Pool saturation at burst onset — not a systemic bottleneck.

**Next steps for production hardening:**
- Tune Worker Pool size and queue depth based on target cloud instance CPU cores
- Add Kafka producer retry with exponential backoff instead of hard fail-fast drop
- Benchmark on AWS EC2 to establish absolute throughput ceiling
- Instrument Python worker with Prometheus metrics to measure DB flush latency directly

### Test Configuration

| Parameter | Value |
|---|---|
| Tool | Locust |
| Target Host | `http://localhost:8000` |
| Peak Users | 1,000 |
| Ramp-up Duration | ~2 min |
| Sustained Test Duration | ~8 min |
| Endpoint Under Test | `POST /api/v1/bid` |

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
