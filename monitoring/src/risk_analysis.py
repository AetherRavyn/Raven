import logging
from typing import Dict
from datetime import datetime

logger = logging.getLogger(__name__)

class RiskAnalysisService:
    """Consumes events.detected, applies Suspicion Scoring AI, and publishes HIGH/CRITICAL to alerts.generated."""

    def __init__(self, bus, config: Dict = None):
        self.bus = bus
        self.config = config or {}
        self.bus.subscribe("events.detected", self.process_event)
        
    def process_event(self, event_payload: Dict):
        try:
            event_id = event_payload.get("event_id")
            if not event_id:
                return
                
            score = self._calculate_suspicion_score(event_payload)
            severity = self._map_score_to_severity(score)
            
            # Update event with calculated risk
            event_payload["suspicion_score"] = score
            event_payload["severity"] = severity
            
            logger.info(f"Risk analysis for {event_id}: Score {score:.2f} ({severity})")
            
            # Only generate alerts for HIGH and CRITICAL severities
            if severity in ["HIGH", "CRITICAL"]:
                self.bus.publish("alerts.generated", event_payload)
                logger.info(f"Published alert for {event_id} to alerts.generated")
                
        except Exception as e:
            logger.error(f"Error in risk analysis: {e}")

    def _calculate_suspicion_score(self, event: Dict) -> float:
        """
        Implementation of the Suspicion Scoring AI:
        A strict 0.0 -> 1.0 scoring formula mapping based on identity, time, weapon presence, and context.
        """
        score = 0.0
        
        event_type = event.get("anomaly_type", "")
        identity = event.get("identity", "")
        is_unknown = identity.startswith("unknown_") or identity.lower() == "unknown"
        
        # Base scores by event type
        if event_type == "weapon_detected":
            score += 0.8
        elif event_type == "restricted_entry":
            score += 0.6
        elif event_type == "fight":
            score += 0.7
        elif event_type == "fall":
            score += 0.5
        elif event_type == "pet_escape":
            score += 0.4
        elif event_type == "abandoned_baggage":
            score += 0.3
        elif event_type in ["loitering", "static_object", "unknown_person"]:
            score += 0.2
            
        # Identity multiplier
        if is_unknown and event_type != "unknown_person":
            score += 0.2  # Penalty for unknown identities doing other anomalous things
            
        # Time constraints (e.g. higher risk at night)
        timestamp = event.get("timestamp")
        if timestamp:
            try:
                if isinstance(timestamp, (int, float)):
                    dt = datetime.fromtimestamp(timestamp)
                else:
                    # simplistic parse attempt if it's a string
                    dt = datetime.fromisoformat(str(timestamp).replace('Z', '+00:00'))
                
                # If between 10 PM and 6 AM, increase suspicion by 0.2
                if dt.hour >= 22 or dt.hour <= 6:
                    score += 0.2
            except Exception as e:
                logger.debug(f"Could not parse timestamp for time-based scoring: {e}")
                
        # Limit to 1.0
        return min(max(score, 0.0), 1.0)
        
    def _map_score_to_severity(self, score: float) -> str:
        """Maps 0.0-1.0 score to LOW, MEDIUM, HIGH, CRITICAL based on spec."""
        if score < 0.2:
            return "LOW"
        elif score < 0.5:
            return "MEDIUM"
        elif score < 0.8:
            return "HIGH"
        else:
            return "CRITICAL"

    def start(self):
        import time
        logger.info("Risk Analysis Service started")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.bus.stop()
        logger.info("Risk Analysis Service stopped")


if __name__ == "__main__":
    from monitoring.src.message_bus import MessageBus
    logging.basicConfig(level=logging.INFO)
    bus = MessageBus()
    service = RiskAnalysisService(bus)
    service.start()
