package api

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var redisAuctionPriceAccessTotal = promauto.NewCounterVec(
	prometheus.CounterOpts{
		Name: "redis_auction_price_access_total",
		Help: "Total Redis accesses for the auction price hot-key path",
	},
	[]string{"operation", "result"},
)