"""Host-side work limits shared by all operations in a world transaction."""
from contextvars import ContextVar
import time

ACTIVE = ContextVar('world_work_budget', default=None)
class BudgetExceeded(RuntimeError):
    pass

class WorkBudget:
    def __init__(self, cancel=None, seconds=180, boundaries=1024, modules=64, models=64):
        self.cancel=cancel; self.deadline=time.monotonic()+seconds
        self.limits={'boundary':boundaries,'module':modules,'model':models}
        self.used={key:0 for key in self.limits}
    def check(self, kind=None):
        if self.cancel is not None and self.cancel.is_set():
            raise BudgetExceeded('本轮已取消，未提交新的世界状态。')
        if time.monotonic()>self.deadline:
            raise BudgetExceeded('本轮处理超过时间预算，未提交新的世界状态。请缩短等待或拆分行动。')
        if kind:
            self.used[kind]+=1
            if self.used[kind]>self.limits[kind]:
                raise BudgetExceeded('本轮处理超过工作量预算，未提交新的世界状态。请拆分行动或缩短等待。')

def consume(kind=None, budget=None):
    value=budget or ACTIVE.get()
    if value is not None:value.check(kind)
