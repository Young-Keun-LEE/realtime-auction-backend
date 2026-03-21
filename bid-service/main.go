package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"strconv"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	_ "github.com/lib/pq"
	"github.com/redis/go-redis/v9"
	"github.com/segmentio/kafka-go"
)

const BidLuaScript = `
local current_price = redis.call('get', KEYS[1])
if current_price then
    if tonumber(ARGV[1]) <= tonumber(current_price) then
        return 0
    end
    redis.call('set', KEYS[1], ARGV[1])
    return 1
else
    return -1
end
`

type BidRequest struct {
	UserID    int `json:"user_id" binding:"required"`
	AuctionID int `json:"auction_id" binding:"required"`
	Amount    int `json:"amount" binding:"required,gt=0"`
}

type Auction struct {
	ID           int
	ItemName     string
	CurrentPrice int
}

// BidTask represents a published bid to be processed by workers
type BidTask struct {
	UserID    int
	AuctionID int
	Amount    int
}

// WorkerPool manages a pool of workers to handle bid tasks
type WorkerPool struct {
	tasks     chan BidTask
	wg        sync.WaitGroup
	rdb       *redis.Client
	kw        *kafka.Writer
	ctx       context.Context
	cancel    context.CancelFunc
	workerCnt int
}

// NewWorkerPool creates a new worker pool
func NewWorkerPool(workerCount int, rdb *redis.Client, kw *kafka.Writer) *WorkerPool {
	ctx, cancel := context.WithCancel(context.Background())
	return &WorkerPool{
		tasks:     make(chan BidTask, 1000), // Buffered channel (queue up to 1000 tasks)
		rdb:       rdb,
		kw:        kw,
		ctx:       ctx,
		cancel:    cancel,
		workerCnt: workerCount,
	}
}

// Start initializes and starts all workers
func (wp *WorkerPool) Start() {
	log.Printf("🚀 Worker Pool started with %d workers", wp.workerCnt)
	for i := 0; i < wp.workerCnt; i++ {
		wp.wg.Add(1)
		go wp.worker(i)
	}
}

// worker processes tasks from the task channel
func (wp *WorkerPool) worker(id int) {
	defer wp.wg.Done()
	log.Printf("👷 Worker %d started", id)

	for task := range wp.tasks {
		wp.processBidTask(task)
	}
	log.Printf("👋 Worker %d finished processing all tasks and stopping", id)
}

// processBidTask publishes bid data to Kafka and Redis Pub/Sub
func (wp *WorkerPool) processBidTask(task BidTask) {
	log.Printf("⚙️  Worker processing: user_id=%d, auction_id=%d, amount=%d",
		task.UserID, task.AuctionID, task.Amount)

	// Prepare bid data
	bidData := map[string]int{
		"user_id":    task.UserID,
		"auction_id": task.AuctionID,
		"amount":     task.Amount,
	}

	// Marshal to JSON
	bidJSON, err := json.Marshal(bidData)
	if err != nil {
		log.Printf("❌ Failed to marshal bid data: %v", err)
		return
	}

	// Publish to Kafka
	err = wp.kw.WriteMessages(wp.ctx, kafka.Message{
		Key:   []byte(strconv.Itoa(task.AuctionID)),
		Value: bidJSON,
	})
	if err != nil {
		log.Printf("❌ Failed to publish to Kafka: %v", err)
	} else {
		log.Printf("📤 Published bid to Kafka: %s", string(bidJSON))
	}

	// Publish to Redis Pub/Sub for WebSocket updates
	err = wp.rdb.Publish(wp.ctx, "auction_channel", string(bidJSON)).Err()
	if err != nil {
		log.Printf("❌ Failed to publish to Redis: %v", err)
	} else {
		log.Printf("📡 Published to Redis Pub/Sub")
	}
}

// Submit adds a task to the worker pool
func (wp *WorkerPool) Submit(task BidTask) {
	select {
	case wp.tasks <- task:
		log.Printf("📋 Task queued: auction_id=%d", task.AuctionID)
	case wp.ctx.Done():
		log.Printf("⚠️  Worker pool is shutting down, task dropped")
	default:
		// Non-blocking send - if channel is full, log warning
		log.Printf("⚠️  Task queue is full, dropping task")
	}
}

// Stop gracefully shuts down the worker pool
func (wp *WorkerPool) Close() {
	log.Println("🛑 Shutting down Worker Pool...")
	close(wp.tasks)
	wp.wg.Wait()
	wp.cancel()
	log.Println("✅ All tasks processed. Worker Pool shut down safely.")
}

func getEnv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func main() {
	// Initialize Gin router
	r := gin.Default()

	// Initialize Redis
	redisAddr := getEnv("REDIS_ADDR", "redis:6379")
	rdb := redis.NewClient(&redis.Options{
		Addr: redisAddr,
	})
	ctx := context.Background()

	// Test Redis connection
	if err := rdb.Ping(ctx).Err(); err != nil {
		log.Fatalf("❌ Failed to connect to Redis: %v", err)
	}
	log.Printf("✅ Connected to Redis at %s", redisAddr)

	// Initialize Kafka Writer
	kafkaBroker := getEnv("KAFKA_BROKER", "kafka:9092")
	kafkaTopic := getEnv("KAFKA_TOPIC", "auction-bids")
	kw := &kafka.Writer{
		Addr:         kafka.TCP(kafkaBroker),
		Topic:        kafkaTopic,
		Balancer:     &kafka.LeastBytes{},
		BatchTimeout: 10 * time.Millisecond,
	}
	defer kw.Close()
	log.Printf("✅ Kafka Writer initialized for broker %s and topic %s", kafkaBroker, kafkaTopic)

	// Initialize Database connection
	dbHost := getEnv("DB_HOST", "db")
	dbPort := getEnv("DB_PORT", "5432")
	dbUser := getEnv("POSTGRES_USER", "postgres")
	dbPassword := getEnv("POSTGRES_PASSWORD", "postgres")
	dbName := getEnv("POSTGRES_DB", "auction_db")

	connStr := fmt.Sprintf("host=%s port=%s user=%s password=%s dbname=%s sslmode=disable",
		dbHost, dbPort, dbUser, dbPassword, dbName)
	db, err := sql.Open("postgres", connStr)
	if err != nil {
		log.Fatalf("❌ Failed to connect to database: %v", err)
	}
	defer db.Close()

	// Test DB connection
	if err := db.Ping(); err != nil {
		log.Fatalf("❌ Failed to ping database: %v", err)
	}
	log.Println("✅ Database connected")

	// Initialize Worker Pool
	workerCount := 100 // Number of concurrent workers
	if envWorkers := os.Getenv("WORKER_COUNT"); envWorkers != "" {
		if n, err := strconv.Atoi(envWorkers); err == nil {
			workerCount = n
		}
	}
	pool := NewWorkerPool(workerCount, rdb, kw)
	pool.Start()
	defer pool.Close()

	// Bid endpoint
	r.POST("/api/v1/bid", func(c *gin.Context) {
		var req BidRequest
		if err := c.ShouldBindJSON(&req); err != nil {
			log.Printf("⚠️  Invalid request: %v", err)
			c.JSON(400, gin.H{"detail": "Invalid request body"})
			return
		}

		log.Printf("📥 Received bid: user_id=%d, auction_id=%d, amount=%d",
			req.UserID, req.AuctionID, req.Amount)

		// Redis key for auction price
		auctionPriceKey := fmt.Sprintf("auction:%d:price", req.AuctionID)

		// Execute Lua script to atomically check and update bid
		result, err := rdb.Eval(ctx, BidLuaScript,
			[]string{auctionPriceKey},
			req.Amount,
		).Int()

		if err != nil {
			log.Printf("❌ Redis Lua script error: %v", err)
			c.JSON(500, gin.H{"detail": "Internal server error"})
			return
		}

		// Case 1: Redis key doesn't exist (first bid or cache miss)
		if result == -1 {
			log.Printf("🔍 Cache miss for auction %d, querying database...", req.AuctionID)

			// Query database for auction
			var auction Auction
			err := db.QueryRow(
				"SELECT id, item_name, current_price FROM auctions WHERE id = $1",
				req.AuctionID,
			).Scan(&auction.ID, &auction.ItemName, &auction.CurrentPrice)

			if err == sql.ErrNoRows {
				log.Printf("❌ Auction %d not found", req.AuctionID)
				c.JSON(404, gin.H{"detail": "Auction not found"})
				return
			} else if err != nil {
				log.Printf("❌ Database error: %v", err)
				c.JSON(500, gin.H{"detail": "Database error"})
				return
			}

			// Validate bid amount against DB price
			if req.Amount <= auction.CurrentPrice {
				log.Printf("⚠️  Bid too low: %d <= %d", req.Amount, auction.CurrentPrice)
				// Initialize Redis cache with current DB price
				rdb.Set(ctx, auctionPriceKey, auction.CurrentPrice, 0)
				c.JSON(400, gin.H{
					"detail": fmt.Sprintf("Bid amount must be higher than current price (%d)", auction.CurrentPrice),
				})
				return
			}

			// Set the new bid price in Redis cache
			if err := rdb.Set(ctx, auctionPriceKey, req.Amount, 0).Err(); err != nil {
				log.Printf("❌ Failed to set Redis cache: %v", err)
			}

			// Case 2: Bid amount is not higher than current cached price
		} else if result == 0 {
			currentPrice, _ := rdb.Get(ctx, auctionPriceKey).Int()
			log.Printf("⚠️  Bid rejected: %d <= current price %d", req.Amount, currentPrice)
			c.JSON(400, gin.H{
				"detail": fmt.Sprintf("Bid amount must be higher than the current price (%d)", currentPrice),
			})
			return
		}

		// Bid accepted (result == 1)
		log.Printf("✅ Bid accepted: auction_id=%d, amount=%d", req.AuctionID, req.Amount)

		// Submit task to worker pool instead of creating a new goroutine
		task := BidTask{
			UserID:    req.UserID,
			AuctionID: req.AuctionID,
			Amount:    req.Amount,
		}
		pool.Submit(task)

		c.JSON(200, gin.H{
			"status":     "success",
			"message":    "Bid placed successfully",
			"auction_id": req.AuctionID,
			"amount":     req.Amount,
		})
	})

	// Health check endpoint
	r.GET("/health", func(c *gin.Context) {
		c.JSON(200, gin.H{"status": "healthy"})
	})

	log.Println("🚀 Go Bid Service starting on :8080")
	if err := r.Run(":8080"); err != nil {
		log.Fatalf("❌ Failed to start server: %v", err)
	}
}
