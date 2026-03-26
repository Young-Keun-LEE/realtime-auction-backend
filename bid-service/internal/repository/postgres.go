package repository

import (
	"context"
	"database/sql"
	"fmt"

	"bid-service/config"
	"bid-service/internal/models"
)

func NewPostgresDB(cfg config.DBConfig) (*sql.DB, error) {
	connStr := fmt.Sprintf("host=%s port=%s user=%s password=%s dbname=%s sslmode=disable",
		cfg.Host, cfg.Port, cfg.User, cfg.Password, cfg.Name)
	return sql.Open("postgres", connStr)
}

func GetAuctionByID(ctx context.Context, db *sql.DB, auctionID int) (models.Auction, error) {
	var auction models.Auction
	err := db.QueryRowContext(
		ctx,
		"SELECT id, item_name, current_price FROM auctions WHERE id = $1",
		auctionID,
	).Scan(&auction.ID, &auction.ItemName, &auction.CurrentPrice)

	return auction, err
}
