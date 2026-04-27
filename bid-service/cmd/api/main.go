package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"bid-service/config"
	"bid-service/internal/api"
	kafkainfra "bid-service/internal/kafka"
	"bid-service/internal/repository"
	"bid-service/internal/worker"

	"github.com/gin-gonic/gin"
	_ "github.com/lib/pq"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

func main() {
	// Load configuration
	cfg := config.Load()

	// Create context
	ctx := context.Background()

	// Initialize Redis
	rdb := repository.NewRedisClient(cfg.RedisAddr)
	defer rdb.Close()
	if err := rdb.Ping(ctx).Err(); err != nil {
		log.Fatalf("❌ Failed to connect to Redis: %v", err)
	}
	log.Printf("✅ Connected to Redis at %s", cfg.RedisAddr)

	// Initialize Kafka Writer
	kw := kafkainfra.NewWriter(cfg.KafkaBroker, cfg.KafkaTopic)
	defer kw.Close()
	log.Printf("✅ Kafka Writer initialized for broker %s and topic %s", cfg.KafkaBroker, cfg.KafkaTopic)

	// Initialize Database
	db, err := repository.NewPostgresDB(cfg.DB)
	if err != nil {
		log.Fatalf("❌ Failed to connect to database: %v", err)
	}
	defer db.Close()
	if err := db.Ping(); err != nil {
		log.Fatalf("❌ Failed to ping database: %v", err)
	}
	log.Println("✅ Database connected")

	// Initialize Worker Pool
	pool := worker.New(cfg.WorkerCount, rdb, kw)
	pool.Start()
	defer pool.Close()

	// Setup Router and API routes
	r := gin.Default()
	h := api.NewHandler(db, rdb, pool)
	api.RegisterRoutes(r, h)

	r.GET("/metrics", gin.WrapH(promhttp.Handler()))

	// Create HTTP server
	server := &http.Server{
		Addr:    ":8080",
		Handler: r,
	}

	// Graceful shutdown setup
	shutdownDone := make(chan struct{})
	go func() {
		sigChan := make(chan os.Signal, 1)
		signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
		sig := <-sigChan
		log.Printf("📢 Received signal: %v", sig)

		// Graceful shutdown with timeout
		shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer shutdownCancel()

		log.Println("🛑 Starting graceful shutdown...")

		if err := server.Shutdown(shutdownCtx); err != nil {
			log.Printf("⚠️  Error during graceful shutdown: %v", err)
		}

		close(shutdownDone)
	}()

	// Start server
	log.Println("🚀 Go Bid Service starting on :8080")
	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("❌ Server error: %v", err)
	}

	// Wait for graceful shutdown to complete
	<-shutdownDone
	log.Println("✅ Server stopped gracefully. Cleaning up resources...")
}
