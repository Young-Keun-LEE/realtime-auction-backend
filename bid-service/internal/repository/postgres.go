package repository

import (
	"database/sql"
	"fmt"

	"bid-service/internal/models"
)

func NewPostgresDB(host, port, user, password, dbName string) (*sql.DB, error) {
	connStr := fmt.Sprintf("host=%s port=%s user=%s password=%s dbname=%s sslmode=disable",
		host, port, user, password, dbName)
	return sql.Open("postgres", connStr)
}

func GetAuctionByID(db *sql.DB, auctionID int) (models.Auction, error) {
	var auction models.Auction
	err := db.QueryRow(
		"SELECT id, item_name, current_price FROM auctions WHERE id = $1",
		auctionID,
	).Scan(&auction.ID, &auction.ItemName, &auction.CurrentPrice)
	return auction, err
}
