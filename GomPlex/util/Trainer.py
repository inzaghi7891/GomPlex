################################################################################
#  Github: https://github.com/MaxInGaussian/GomPlex
#  Author: Max W. Y. Lam (maxingaussian@gmail.com)
################################################################################

import numpy as np

__all__ = [
    "Trainer"
]

class Trainer(object):
    
    def __init__(self, gp, opt_rate, max_iter, iter_tol, early_stopping):
        self.gp = gp
        self.opt_rate = opt_rate
        self.max_iter = max_iter
        self.iter_tol = iter_tol
        self.early_stopping = early_stopping

    def train(self, animate=None):
        self.learned_hyperparams = None
        self.iter, self.div_count, self.min_cost = 0, 0, np.Infinity
        N = self.gp.N
        self.cost_records, self.min_cost_records = [], []
        while(True):
            grad = self.gp.get_cost_grad()
            hyperparams = self.gp.get_hyperparams()
            if(self.div_count % self.iter_tol//2 == self.iter_tol//4):
                hyperparams = self.learned_hyperparams.copy()
            hyperparams = self.apply_update_rule(hyperparams, grad)
            self.gp.set_hyperparams(hyperparams)
            self.iter += 1
            if(animate is not None):
                animate(self)
            cost = self.gp.get_cost()
            self.cost_records.append(cost)
            print("  iter %d - best %.8f - update %.8f - %d/%d"%(
                self.iter, self.min_cost, cost, self.div_count, self.iter_tol))
            if(cost < self.min_cost):
                self.min_cost = cost
                self.min_cost_records.append(cost)
                if(np.mean(self.cost_records[-self.early_stopping:]) > 
                    np.mean(self.min_cost_records[-self.early_stopping//2:])):
                    self.div_count += 1
                else:
                    self.div_count = 0
                self.learned_hyperparams = hyperparams.copy()
            else:
                self.div_count += 1
            if(self.stop_condition()):
                self.gp.set_hyperparams(self.learned_hyperparams)
                break
    
    def stop_condition(self):
        if(self.iter==self.max_iter or self.div_count == self.iter_tol):
            return True
        return False

    def apply_update_rule(self, hyperparams, grad):
        if('mem' not in self.__dict__.keys()):
            self.mem = np.ones(hyperparams.shape)
            self.g = np.zeros(hyperparams.shape)
            self.g2 = np.zeros(hyperparams.shape)
        r = 1/(self.mem+1)
        self.g = (1-r)*self.g+r*grad
        self.g2 = (1-r)*self.g2+r*grad**2
        rate1 = self.g*self.g/(self.g2+1e-16)
        self.mem *= 1-rate1
        rate2 = self.opt_rate/(max(self.div_count, 7))
        self.mem += 1
        self.rate = np.minimum(rate1, rate2)/(np.sqrt(self.g2)+1e-16)
        return hyperparams-grad*self.rate
