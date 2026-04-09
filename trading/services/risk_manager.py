from trading.utils.config import MAX_POSITION_SIZE, MAX_RISK_PCT, DEFAULT_ATR_MULTIPLIER
from trading.utils.database import log_event


class RiskManager:
    def __init__(self, max_risk_pct=MAX_RISK_PCT, atr_multiplier=DEFAULT_ATR_MULTIPLIER, max_position_pct=MAX_POSITION_SIZE):
        self.max_risk_pct = max_risk_pct
        self.atr_multiplier = atr_multiplier
        self.max_position_pct = max_position_pct
        self.kill_switch_active = False

    def activate_kill_switch(self):
        self.kill_switch_active = True
        log_event("risk", "KILL SWITCH ACTIVATED — all trading halted", "warning")

    def deactivate_kill_switch(self):
        self.kill_switch_active = False
        log_event("risk", "Kill switch deactivated — trading resumed", "info")

    def approve_trade(self, action, symbol, qty, price, account_equity, current_positions):
        if self.kill_switch_active:
            return False, "Kill switch is active — trading halted"

        if action == "hold":
            return False, "Action is HOLD — no trade needed"

        if qty <= 0:
            return False, f"Invalid quantity: {qty}"

        position_value = qty * price
        max_allowed = account_equity * self.max_position_pct
        if position_value > max_allowed:
            return False, f"Position too large: ${position_value:,.0f} > max ${max_allowed:,.0f} ({self.max_position_pct:.0%} of equity)"

        total_exposure = sum(abs(p.get("market_value", 0)) for p in current_positions)
        if total_exposure + position_value > account_equity * 0.95:
            return False, f"Total exposure too high: ${total_exposure + position_value:,.0f} would exceed 95% of equity"

        return True, "Trade approved"

    def calculate_shares(self, account_equity, atr, confidence=1.0):
        if atr <= 0:
            return 0
        risk_dollars = account_equity * self.max_risk_pct * confidence
        stop_distance = atr * self.atr_multiplier
        shares = int(risk_dollars / stop_distance)
        return max(1, shares)

    def calculate_stop_loss(self, entry_price, atr, side):
        if side == "buy":
            return entry_price - (atr * self.atr_multiplier)
        else:
            return entry_price + (atr * self.atr_multiplier)

    def get_status(self):
        return {
            "kill_switch": self.kill_switch_active,
            "max_risk_pct": self.max_risk_pct,
            "atr_multiplier": self.atr_multiplier,
            "max_position_pct": self.max_position_pct,
        }
