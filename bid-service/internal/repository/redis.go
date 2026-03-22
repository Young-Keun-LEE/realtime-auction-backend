package repository

import (
	"context"

	"github.com/redis/go-redis/v9"
)

func NewRedisClient(addr string) *redis.Client {
	return redis.NewClient(&redis.Options{Addr: addr})
}

func EvalBidScript(ctx context.Context, rdb *redis.Client, script string, auctionPriceKey string, amount int) (int, error) {
	return rdb.Eval(ctx, script, []string{auctionPriceKey}, amount).Int()
}

func SetAuctionPrice(ctx context.Context, rdb *redis.Client, key string, price int) error {
	return rdb.Set(ctx, key, price, 0).Err()
}

func GetAuctionPrice(ctx context.Context, rdb *redis.Client, key string) (int, error) {
	return rdb.Get(ctx, key).Int()
}
