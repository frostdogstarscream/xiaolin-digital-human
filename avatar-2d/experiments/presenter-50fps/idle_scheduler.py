"""Seedable three-segment scheduling; standalone and testable without CUDA."""
import random

class IdleScheduler:
    def __init__(self,segments,distance,seed=None):
        self.segments=segments;self.distance=distance;self.rng=random.Random(seed)
        self.current=None;self.index=None;self.completed=0;self.history=[]

    def select(self,previous):
        allowed=[i for i in range(len(self.segments)) if i!=self.current]
        costs=[max(0.,float(self.distance(previous,self.segments[i]['start']))) for i in allowed]
        best=min(costs)
        # Prefer closer posture but retain randomness among similar candidates.
        weights=[1/(1+(cost-best)**2) for cost in costs]
        self.current=self.rng.choices(allowed,weights=weights,k=1)[0]
        self.index=self.segments[self.current]['start'];self.history.append(self.current)

    def next(self,previous,from_action=False):
        if self.index is None or from_action:self.select(previous)
        result=self.index;self.index+=1
        if self.index>=self.segments[self.current]['end']:
            self.completed+=1;self.index=None
        return result

    def seek(self, index):
        for current, segment in enumerate(self.segments):
            if segment['start'] <= index < segment['end']:
                self.current = current
                self.index = index
                return
        raise ValueError('Idle entry outside the available segments')
