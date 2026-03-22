package config

import (
	"log"
	"os"
	"strconv"
)

type DBConfig struct {
	Host     string
	Port     string
	User     string
	Password string
	Name     string
}

type Config struct {
	RedisAddr   string
	KafkaBroker string
	KafkaTopic  string
	DB          DBConfig
	WorkerCount int
}

func GetEnv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func Load() *Config {
	workerCount := 100
	if envWorkers := os.Getenv("WORKER_COUNT"); envWorkers != "" {
		if n, err := strconv.Atoi(envWorkers); err == nil {
			workerCount = n
		}
	}

	cfg := &Config{
		RedisAddr:   GetEnv("REDIS_ADDR", "redis:6379"),
		KafkaBroker: GetEnv("KAFKA_BROKER", "kafka:9092"),
		KafkaTopic:  GetEnv("KAFKA_TOPIC", "auction-bids"),
		DB: DBConfig{
			Host:     GetEnv("DB_HOST", "db"),
			Port:     GetEnv("DB_PORT", "5432"),
			User:     GetEnv("POSTGRES_USER", "postgres"),
			Password: GetEnv("POSTGRES_PASSWORD", "postgres"),
			Name:     GetEnv("POSTGRES_DB", "auction_db"),
		},
		WorkerCount: workerCount,
	}

	log.Printf("✅ Configuration loaded: Redis=%s, Kafka=%s:%s, DB=%s:%s, Workers=%d",
		cfg.RedisAddr, cfg.KafkaBroker, cfg.KafkaTopic, cfg.DB.Host, cfg.DB.Port, cfg.WorkerCount)

	return cfg
}
