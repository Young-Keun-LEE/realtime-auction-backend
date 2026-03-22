package models

const BidLuaScript = `
local current_price = redis.call('get', KEYS[1])
if current_price then
    if tonumber(ARGV[1]) <= tonumber(current_price) then
        return 0
    end
    redis.call('set', KEYS[1], ARGV[1])
    return 1
else
    return -1
end
`

type BidRequest struct {
	UserID    int `json:"user_id" binding:"required"`
	AuctionID int `json:"auction_id" binding:"required"`
	Amount    int `json:"amount" binding:"required,gt=0"`
}

type Auction struct {
	ID           int
	ItemName     string
	CurrentPrice int
}

type BidTask struct {
	UserID    int
	AuctionID int
	Amount    int
}
