"""Caps on NEW model requests, including retries; never a player action quota."""
import contextvars
from world_state import read, clock_time
from goal_sets import store_card

REQUEST_LIMIT = contextvars.ContextVar('feature_request_limit', default=None)

class FeatureQuota(ValueError):
    pass

class LimitedGateway:
    def __init__(self, tx, gateway, category, actor, daily, local=1):
        self.tx, self.gateway = tx, gateway
        self.category, self.actor = category, actor
        self.daily, self.local, self.used = daily, local, 0

    def consume(self):
        cid = 'feature-budget:' + self.category + ':' + self.actor
        day = clock_time(self.tx.state) // 1440 + 1
        value = read(self.tx.state, cid, {})
        count = value.get('requests', 0) if value.get('day') == day else 0
        if self.used >= self.local or count >= self.daily:
            raise FeatureQuota('New model request budget exhausted: ' + self.category)
        self.used += 1
        store_card(self.tx, cid, 'feature_budget', {'owner': self.actor, 'day': day, 'requests': count + 1},
                   self.actor, '新增请求预算')

    def ask(self, role, instructions, payload, max_tokens=900):
        from world_turn import ModelGateway
        token = REQUEST_LIMIT.set(self.consume)
        try:
            if not isinstance(self.gateway, ModelGateway):
                self.consume()
            return self.gateway.ask(role, instructions, payload, max_tokens)
        finally:
            REQUEST_LIMIT.reset(token)

def consume_request():
    callback = REQUEST_LIMIT.get()
    if callback:
        callback()
