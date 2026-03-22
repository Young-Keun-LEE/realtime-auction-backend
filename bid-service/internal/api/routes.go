package api

import "github.com/gin-gonic/gin"

func RegisterRoutes(r *gin.Engine, h *Handler) {
	r.POST("/api/v1/bid", h.PlaceBid)
	r.GET("/health", h.Health)
}
