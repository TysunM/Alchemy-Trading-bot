import os
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from trading.utils.config import DB_PATH, DB_URL


os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class TradeLog(Base):
    __tablename__ = "trade_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)
    qty = Column(Float, nullable=False)
    price = Column(Float, nullable=True)
    order_id = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    pnl = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)


class ReasoningLedger(Base):
    __tablename__ = "reasoning_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    symbol = Column(String(20), nullable=False)
    action = Column(String(20), nullable=False)
    signal_type = Column(String(50), nullable=True)
    confidence = Column(Float, nullable=True)
    reasoning = Column(Text, nullable=False)
    indicators_snapshot = Column(Text, nullable=True)
    outcome = Column(String(20), nullable=True)


class Annotation(Base):
    __tablename__ = "annotations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    symbol = Column(String(20), nullable=False)
    price_level = Column(Float, nullable=False)
    annotation_type = Column(String(20), nullable=False, default="support")
    notes = Column(Text, nullable=True)


class SystemEvent(Base):
    __tablename__ = "system_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    event_type = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    severity = Column(String(10), nullable=False, default="info")


class SnapshotCheckpoint(Base):
    __tablename__ = "snapshot_checkpoints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    session_id = Column(String(64), nullable=False, index=True)
    positions_json = Column(Text, nullable=True)
    open_orders_json = Column(Text, nullable=True)
    market_context_json = Column(Text, nullable=True)
    reasoning_summary = Column(Text, nullable=True)
    token_usage = Column(Integer, nullable=True, default=0)
    cycle_count = Column(Integer, nullable=True, default=0)
    account_equity = Column(Float, nullable=True)
    metadata_json = Column(Text, nullable=True)


class DailySummary(Base):
    __tablename__ = "daily_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String(10), nullable=False, index=True)
    session_id = Column(String(64), nullable=True)
    summary_text = Column(Text, nullable=False)
    trades_count = Column(Integer, nullable=True, default=0)
    total_pnl = Column(Float, nullable=True, default=0.0)
    key_decisions_json = Column(Text, nullable=True)
    token_budget_used = Column(Integer, nullable=True, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ToolCallLog(Base):
    __tablename__ = "tool_call_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    session_id = Column(String(64), nullable=True, index=True)
    tool_name = Column(String(100), nullable=False)
    input_json = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    success = Column(Integer, nullable=True, default=1)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def log_trade(symbol, side, qty, price=None, order_id=None, status="submitted", notes=None):
    db = SessionLocal()
    try:
        trade = TradeLog(
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            order_id=order_id,
            status=status,
            notes=notes,
        )
        db.add(trade)
        db.commit()
        return trade.id
    finally:
        db.close()


def log_reasoning(symbol, action, reasoning, signal_type=None, confidence=None, indicators=None):
    db = SessionLocal()
    try:
        entry = ReasoningLedger(
            symbol=symbol,
            action=action,
            signal_type=signal_type,
            confidence=confidence,
            reasoning=reasoning,
            indicators_snapshot=str(indicators) if indicators else None,
        )
        db.add(entry)
        db.commit()
        return entry.id
    finally:
        db.close()


def log_event(event_type, message, severity="info"):
    db = SessionLocal()
    try:
        event = SystemEvent(event_type=event_type, message=message, severity=severity)
        db.add(event)
        db.commit()
    finally:
        db.close()


def get_recent_trades(limit=50):
    db = SessionLocal()
    try:
        return db.query(TradeLog).order_by(TradeLog.timestamp.desc()).limit(limit).all()
    finally:
        db.close()


def get_recent_reasoning(limit=20):
    db = SessionLocal()
    try:
        return (
            db.query(ReasoningLedger)
            .order_by(ReasoningLedger.timestamp.desc())
            .limit(limit)
            .all()
        )
    finally:
        db.close()


def get_recent_events(limit=30):
    db = SessionLocal()
    try:
        return (
            db.query(SystemEvent).order_by(SystemEvent.timestamp.desc()).limit(limit).all()
        )
    finally:
        db.close()


def get_trade_stats():
    db = SessionLocal()
    try:
        from sqlalchemy import func
        total = db.query(func.count(TradeLog.id)).scalar() or 0
        buys = db.query(func.count(TradeLog.id)).filter(TradeLog.side == "buy").scalar() or 0
        sells = db.query(func.count(TradeLog.id)).filter(TradeLog.side == "sell").scalar() or 0
        total_pnl = db.query(func.sum(TradeLog.pnl)).scalar() or 0.0
        winning = db.query(func.count(TradeLog.id)).filter(TradeLog.pnl > 0).scalar() or 0
        losing = db.query(func.count(TradeLog.id)).filter(TradeLog.pnl < 0).scalar() or 0
        win_rate = (winning / (winning + losing) * 100) if (winning + losing) > 0 else 0.0
        return {
            "total_trades": total,
            "buys": buys,
            "sells": sells,
            "total_pnl": float(total_pnl),
            "winning": winning,
            "losing": losing,
            "win_rate": win_rate,
        }
    finally:
        db.close()


def get_error_events(limit=10):
    db = SessionLocal()
    try:
        return (
            db.query(SystemEvent)
            .filter(SystemEvent.severity.in_(["error", "warning"]))
            .order_by(SystemEvent.timestamp.desc())
            .limit(limit)
            .all()
        )
    finally:
        db.close()


def save_annotation(symbol, price_level, annotation_type="support", notes=None):
    db = SessionLocal()
    try:
        ann = Annotation(
            symbol=symbol,
            price_level=price_level,
            annotation_type=annotation_type,
            notes=notes,
        )
        db.add(ann)
        db.commit()
        return ann.id
    finally:
        db.close()


def get_annotations_for_symbol(symbol):
    db = SessionLocal()
    try:
        return (
            db.query(Annotation)
            .filter(Annotation.symbol == symbol)
            .order_by(Annotation.timestamp.desc())
            .all()
        )
    finally:
        db.close()


def delete_annotation(annotation_id):
    db = SessionLocal()
    try:
        ann = db.query(Annotation).filter(Annotation.id == annotation_id).first()
        if ann:
            db.delete(ann)
            db.commit()
            return True
        return False
    finally:
        db.close()


def get_all_active_annotations():
    db = SessionLocal()
    try:
        return db.query(Annotation).order_by(Annotation.symbol, Annotation.timestamp.desc()).all()
    finally:
        db.close()
