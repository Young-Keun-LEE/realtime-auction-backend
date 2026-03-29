package api

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"time"

	"bid-service/internal/models"
	"bid-service/internal/repository"
	"bid-service/internal/worker"

	"github.com/gin-gonic/gin"
	"github.com/go-playground/validator/v10"
	"github.com/google/uuid"
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
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	var req models.BidRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		log.Printf("⚠️  Invalid request: %v", err)
		status, detail := classifyBindError(err)
		c.JSON(status, gin.H{"detail": detail})
		return
	}

	log.Printf("📥 Received bid: user_id=%d, auction_id=%d, amount=%d",
		req.UserID, req.AuctionID, req.Amount)

	auctionPriceKey := fmt.Sprintf("auction:%d:price", req.AuctionID)

	result, err := repository.EvalBidScript(ctx, h.rdb, models.BidLuaScript, auctionPriceKey, req.Amount)
	if err != nil {
		log.Printf("❌ Redis Lua script error: %v", err)
		if isTemporaryDependencyError(err) {
			c.JSON(http.StatusServiceUnavailable, gin.H{"detail": "Service temporarily unavailable"})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"detail": "Internal server error"})
		return
	}

	if result == -1 {
		log.Printf("🔍 Cache miss for auction %d, querying database...", req.AuctionID)

		auction, err := repository.GetAuctionByID(ctx, h.db, req.AuctionID)
		if err == sql.ErrNoRows {
			log.Printf("❌ Auction %d not found", req.AuctionID)
			c.JSON(http.StatusNotFound, gin.H{"detail": "Auction not found"})
			return
		} else if err != nil {
			log.Printf("❌ Database error: %v", err)
			if isTemporaryDependencyError(err) {
				c.JSON(http.StatusServiceUnavailable, gin.H{"detail": "Database temporarily unavailable"})
				return
			}
			c.JSON(http.StatusInternalServerError, gin.H{"detail": "Database error"})
			return
		}

		if req.Amount <= auction.CurrentPrice {
			log.Printf("⚠️  Bid too low: %d <= %d", req.Amount, auction.CurrentPrice)
			_ = repository.SetAuctionPrice(ctx, h.rdb, auctionPriceKey, auction.CurrentPrice)
			c.JSON(http.StatusConflict, gin.H{
				"detail":        fmt.Sprintf("Bid amount must be higher than current price (%d)", auction.CurrentPrice),
				"auction_id":    req.AuctionID,
				"current_price": auction.CurrentPrice,
			})
			return
		}

		if err := repository.SetAuctionPrice(ctx, h.rdb, auctionPriceKey, req.Amount); err != nil {
			log.Printf("❌ Failed to set Redis cache: %v", err)
		}
	} else if result == 0 {
		currentPrice, _ := repository.GetAuctionPrice(ctx, h.rdb, auctionPriceKey)
		log.Printf("⚠️  Bid rejected: %d <= current price %d", req.Amount, currentPrice)
		c.JSON(http.StatusConflict, gin.H{
			"detail":        fmt.Sprintf("Bid amount must be higher than the current price (%d)", currentPrice),
			"auction_id":    req.AuctionID,
			"current_price": currentPrice,
		})
		return
	}

	log.Printf("✅ Bid accepted: auction_id=%d, amount=%d", req.AuctionID, req.Amount)

	h.pool.Submit(models.BidTask{
		BidID:     uuid.New().String(),
		UserID:    req.UserID,
		AuctionID: req.AuctionID,
		Amount:    req.Amount,
	})

	c.JSON(http.StatusAccepted, gin.H{
		"status":     "accepted",
		"message":    "Bid accepted and is being processed",
		"auction_id": req.AuctionID,
		"amount":     req.Amount,
	})
}

func (h *Handler) Health(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "healthy"})
}

func classifyBindError(err error) (int, string) {
	var syntaxErr *json.SyntaxError
	var typeErr *json.UnmarshalTypeError
	var validationErrs validator.ValidationErrors

	switch {
	case errors.Is(err, io.EOF):
		return http.StatusBadRequest, "Request body is required"
	case errors.As(err, &syntaxErr):
		return http.StatusBadRequest, "Malformed JSON"
	case errors.As(err, &typeErr):
		return http.StatusBadRequest, "Invalid field type in request body"
	case errors.As(err, &validationErrs):
		return http.StatusUnprocessableEntity, "Validation failed for request body"
	default:
		return http.StatusBadRequest, "Invalid request body"
	}
}

func isTemporaryDependencyError(err error) bool {
	return errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled) || errors.Is(err, sql.ErrConnDone)
}
