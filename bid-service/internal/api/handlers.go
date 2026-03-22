package api

import (
	"context"
	"database/sql"
	"fmt"
	"log"

	"bid-service/internal/models"
	"bid-service/internal/repository"
	"bid-service/internal/worker"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
)

type Handler struct {
	db   *sql.DB
	rdb  *redis.Client
	pool *worker.Pool
}

func NewHandler(db *sql.DB, rdb *redis.Client, pool *worker.Pool) *Handler {
	return &Handler{db: db, rdb: rdb, pool: pool}
}

func (h *Handler) PlaceBid(c *gin.Context) {
	var req models.BidRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		log.Printf("⚠️  Invalid request: %v", err)
		c.JSON(400, gin.H{"detail": "Invalid request body"})
		return
	}

	log.Printf("📥 Received bid: user_id=%d, auction_id=%d, amount=%d",
		req.UserID, req.AuctionID, req.Amount)
	
	reqCtx := c.Request.Context()

	auctionPriceKey := fmt.Sprintf("auction:%d:price", req.AuctionID)

	result, err := repository.EvalBidScript(reqCtx, h.rdb, models.BidLuaScript, auctionPriceKey, req.Amount)
	if err != nil {
		log.Printf("❌ Redis Lua script error: %v", err)
		c.JSON(500, gin.H{"detail": "Internal server error"})
		return
	}

	if result == -1 {
		log.Printf("🔍 Cache miss for auction %d, querying database...", req.AuctionID)

		auction, err := repository.GetAuctionByID(reqCtx, h.db, req.AuctionID)
		if err == sql.ErrNoRows {
			log.Printf("❌ Auction %d not found", req.AuctionID)
			c.JSON(404, gin.H{"detail": "Auction not found"})
			return
		} else if err != nil {
			log.Printf("❌ Database error: %v", err)
			c.JSON(500, gin.H{"detail": "Database error"})
			return
		}

		if req.Amount <= auction.CurrentPrice {
			log.Printf("⚠️  Bid too low: %d <= %d", req.Amount, auction.CurrentPrice)
			_ = repository.SetAuctionPrice(reqCtx, h.rdb, auctionPriceKey, auction.CurrentPrice)
			c.JSON(400, gin.H{
				"detail": fmt.Sprintf("Bid amount must be higher than current price (%d)", auction.CurrentPrice),
			})
			return
		}

		if err := repository.SetAuctionPrice(reqCtx, h.rdb, auctionPriceKey, req.Amount); err != nil {
			log.Printf("❌ Failed to set Redis cache: %v", err)
		}
	} else if result == 0 {
		currentPrice, _ := repository.GetAuctionPrice(reqCtx, h.rdb, auctionPriceKey)
		log.Printf("⚠️  Bid rejected: %d <= current price %d", req.Amount, currentPrice)
		c.JSON(400, gin.H{
			"detail": fmt.Sprintf("Bid amount must be higher than the current price (%d)", currentPrice),
		})
		return
	}

	log.Printf("✅ Bid accepted: auction_id=%d, amount=%d", req.AuctionID, req.Amount)

	h.pool.Submit(models.BidTask{
		UserID:    req.UserID,
		AuctionID: req.AuctionID,
		Amount:    req.Amount,
	})

	c.JSON(200, gin.H{
		"status":     "success",
		"message":    "Bid placed successfully",
		"auction_id": req.AuctionID,
		"amount":     req.Amount,
	})
}

func (h *Handler) Health(c *gin.Context) {
	c.JSON(200, gin.H{"status": "healthy"})
}
