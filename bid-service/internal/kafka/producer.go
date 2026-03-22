package kafka

import (
	"time"

	kafkago "github.com/segmentio/kafka-go"
)

func NewWriter(broker, topic string) *kafkago.Writer {
	return &kafkago.Writer{
		Addr:         kafkago.TCP(broker),
		Topic:        topic,
		Balancer:     &kafkago.LeastBytes{},
		BatchTimeout: 10 * time.Millisecond,
	}
}
