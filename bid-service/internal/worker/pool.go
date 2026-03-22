package worker

import (
	"context"
	"encoding/json"
	"log"
	"strconv"
	"sync"

	"bid-service/internal/models"

	"github.com/redis/go-redis/v9"
	kafkago "github.com/segmentio/kafka-go"
)

type Pool struct {
	tasks     chan models.BidTask
	wg        sync.WaitGroup
	rdb       *redis.Client
	kw        *kafkago.Writer
	ctx       context.Context
	cancel    context.CancelFunc
	workerCnt int
}

func New(workerCount int, rdb *redis.Client, kw *kafkago.Writer) *Pool {
	ctx, cancel := context.WithCancel(context.Background())
	return &Pool{
		tasks:     make(chan models.BidTask, 1000),
		rdb:       rdb,
		kw:        kw,
		ctx:       ctx,
		cancel:    cancel,
		workerCnt: workerCount,
	}
}

func (wp *Pool) Start() {
	log.Printf("🚀 Worker Pool started with %d workers", wp.workerCnt)
	for i := 0; i < wp.workerCnt; i++ {
		wp.wg.Add(1)
		go wp.worker(i)
	}
}

func (wp *Pool) worker(id int) {
	defer wp.wg.Done()
	log.Printf("👷 Worker %d started", id)

	for task := range wp.tasks {
		wp.processBidTask(task)
	}
	log.Printf("👋 Worker %d finished processing all tasks and stopping", id)
}

func (wp *Pool) processBidTask(task models.BidTask) {
	log.Printf("⚙️  Worker processing: user_id=%d, auction_id=%d, amount=%d",
		task.UserID, task.AuctionID, task.Amount)

	bidData := map[string]int{
		"user_id":    task.UserID,
		"auction_id": task.AuctionID,
		"amount":     task.Amount,
	}

	bidJSON, err := json.Marshal(bidData)
	if err != nil {
		log.Printf("❌ Failed to marshal bid data: %v", err)
		return
	}

	err = wp.kw.WriteMessages(wp.ctx, kafkago.Message{
		Key:   []byte(strconv.Itoa(task.AuctionID)),
		Value: bidJSON,
	})
	if err != nil {
		log.Printf("❌ Failed to publish to Kafka: %v", err)
	} else {
		log.Printf("📤 Published bid to Kafka: %s", string(bidJSON))
	}

	err = wp.rdb.Publish(wp.ctx, "auction_channel", string(bidJSON)).Err()
	if err != nil {
		log.Printf("❌ Failed to publish to Redis: %v", err)
	} else {
		log.Printf("📡 Published to Redis Pub/Sub")
	}
}

func (wp *Pool) Submit(task models.BidTask) {
	select {
	case wp.tasks <- task:
		log.Printf("📋 Task queued: auction_id=%d", task.AuctionID)
	case <-wp.ctx.Done():
		log.Printf("⚠️  Worker pool is shutting down, task dropped")
	default:
		log.Printf("⚠️  Task queue is full, dropping task")
	}
}

func (wp *Pool) Close() {
	log.Println("🛑 Shutting down Worker Pool...")
	close(wp.tasks)
	wp.wg.Wait()
	wp.cancel()
	log.Println("✅ All tasks processed. Worker Pool shut down safely.")
}
