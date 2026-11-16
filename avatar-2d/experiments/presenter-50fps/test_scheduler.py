import unittest
from idle_scheduler import IdleScheduler

class Scheduling(unittest.TestCase):
    def test_duration_and_no_repeat(self):
        s=IdleScheduler([dict(start=0,end=500),dict(start=500,end=1000),dict(start=1000,end=1500)],lambda p,i:0,42)
        output=[s.next(('idle',0)) for _ in range(500*20)]
        self.assertEqual(s.completed,20)
        self.assertTrue(all(a!=b for a,b in zip(s.history,s.history[1:])))
        self.assertEqual(set(s.history),{0,1,2})
        for i in range(20):self.assertEqual(output[i*500:(i+1)*500],list(range(output[i*500],output[i*500]+500)))
    def test_action_return_selects_close_posture(self):
        s=IdleScheduler([dict(start=0,end=500),dict(start=500,end=1000),dict(start=1000,end=1500)],lambda p,i:0 if i==1000 else 10000,5)
        self.assertEqual(s.next(('wave',300),True),1000)
        self.assertEqual(s.next(('idle',1000)),1001)

if __name__=='__main__':unittest.main()
