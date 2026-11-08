"""Structured operational events without request bodies, secrets or headers."""
import json
import logging


class EventFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            'time': self.formatTime(record),
            'level': record.levelname,
            'logger': record.name,
            'event': record.getMessage(),
        })
