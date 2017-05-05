################################################################################
#  Github: https://github.com/MaxInGaussian/GomPlex
#  Author: Max W. Y. Lam (maxingaussian@gmail.com)
################################################################################

import random
import numpy as np
import numpy.random as npr
from scipy import linalg
from .. import Scaler, Metric, Trainer, Visualizer

class GomPlex(object):
    
    noise_imag, noise_real, kernel_scale, spectral_freqs = 0., 0., None, None
    X, y = None, None
    X_scaler, y_scaler = None, None
    grad_epsilon = 1e-8
    
    def __init__(self, sparsity=20):
        self.M = sparsity
        self.hashed_name = ''.join(npr.choice(list('ABCDEFGH'), 5))+str(self.M)
        self.visualizer = Visualizer(self)
    
    def __str__(self):
        return "GomPlex-%d" % (self.M)
    
    def fit(self, X, y,
        opt_rate=1, max_iter=500, iter_tol=50, cost_tol=1e-4, plot=False):
        trainer = Trainer(self, opt_rate, max_iter, iter_tol, cost_tol)
        self.X_scaler = Scaler('minmax', X)
        self.y_scaler = Scaler('normal', y)
        self.X = self.X_scaler.eval(X)
        self.y = self.y_scaler.eval(y)
        self.D = self.X.shape[1]
        self.init_hyperparams()
        trainer.train(self.visualizer.plot_training() if plot else None)
    
    def predict(self, new_X, scaled=True):
        X = np.array(new_X).copy()
        if(scaled):
            X = self.X_scaler.eval(X)
        X_sparse = X.dot(self.spectral_freqs)
        Phi_const = np.sqrt(self.kernel_scale/self.M)
        Phi = Phi_const*np.exp(-2j*np.pi*X_sparse)
        mu = Phi.dot(self.alpha)
        if(scaled):
            mu = self.y_scaler.eval(mu, inv=True)
        noise = self.noise_real+self.noise_imag*1j
        std = np.sqrt(noise*(1+np.diagonal(
            Phi.dot(self.inv_A.dot(Phi.conj().T)))))[:, None]
        if(scaled):
            std *= (self.y_scaler._r_std_+self.y_scaler._i_std_*1j)
        return mu, std
    
    def init_hyperparams(self, rand_num=1):
        best_cost = np.Infinity
        best_hyperparams = None
        for _ in range(rand_num):
            hyperparams = npr.randn(3+self.D*self.M)
            self.set_hyperparams(hyperparams)
            cost = self.get_cost()
            if(cost < best_cost):
                best_hyperparams = cost
                best_hyperparams = hyperparams
        self.set_hyperparams(best_hyperparams)

    def get_hyperparams(self):
        hyperparams = np.zeros(3+self.D*self.M)
        hyperparams[0] = np.log(self.noise_real.real)
        hyperparams[1] = np.log(self.noise_imag.real)
        hyperparams[2] = np.log(self.kernel_scale.real)
        hyperparams[3:] = np.reshape(self.spectral_freqs.real, (self.D*self.M,))
        return hyperparams

    def set_hyperparams(self, hyperparams):
        self.noise_real = np.exp(hyperparams[0])
        self.noise_imag = np.exp(hyperparams[1])
        self.kernel_scale = np.exp(hyperparams[2])
        self.spectral_freqs = np.reshape(hyperparams[3:], (self.D, self.M))
        self.train()
    
    def train(self, nfft=False):
        self.N = self.X.shape[0]
        X_sparse = self.X.dot(self.spectral_freqs)
        Phi_const = np.sqrt(self.kernel_scale/self.M)
        Phi = Phi_const*np.exp(-2j*np.pi*X_sparse)
        noise = self.noise_real+self.noise_imag*1j
        A = Phi.conj().T.dot(Phi)+noise*np.eye(self.M)
        self.T, Q = linalg.schur(A, 'complex')
        self.inv_A = Q.conj().T.dot(np.eye(self.M))
        self.inv_A = Q.dot(linalg.solve_triangular(self.T, self.inv_A))
        self.alpha = self.inv_A.dot(Phi.conj().T.dot(self.y))
        self.mu = Phi.dot(self.alpha)
    
    def get_cost(self):
        return self.get_cv_metric(1, 'nlml')

    def get_cv_metric(self, n_folds, metric):
        cv_metric = Metric(metric, self)
        cv_results = []
        data = np.hstack((self.X.copy(), self.y.copy()))
        npr.shuffle(data)
        if(n_folds > 1):
            fold_size = self.N//n_folds
            for i in range(n_folds):
                st_ind, ed_ind = fold_size*i, min(fold_size*(i+1), data.shape[0])
                cv_X = data[st_ind:ed_ind, :-1]
                cv_y = data[st_ind:ed_ind, -1][:, None]
                self.X = np.vstack((data[:st_ind, :-1], data[ed_ind:, :-1]))
                self.y = np.hstack((data[:st_ind, -1], data[ed_ind:, -1]))[:, None]
                self.train()
                cv_results.append(self.N*cv_metric.eval(
                    cv_y, *self.predict(cv_X, scaled=False)))
            self.X, self.y = data[:, :-1], data[:, -1][:, None]
            self.train()
        else:
            self.train()
            cv_results.append(self.N*cv_metric.eval(
                self.y, *self.predict(self.X, scaled=False)))
        return np.sum(cv_results)/data.shape[0]

    def get_cost_grad(self):
        self.last_cost = self.get_cost()
        d_cost_d_noise = self.get_d_cost_d_noise()
        g11 = self.noise_real*d_cost_d_noise[0]
        g12 = self.noise_imag*d_cost_d_noise[1]
        d_cost_d_kernel_scale = self.get_d_cost_d_kernel_scale()
        g2 = self.kernel_scale*d_cost_d_kernel_scale.real
        d_cost_d_freqs = self.get_d_cost_d_freqs()
        g3 = np.reshape(d_cost_d_freqs.real, (self.D*self.M,))
        return np.concatenate([[g11, g12, g2], g3])
    
    def get_d_cost_d_noise(self):
        # Warning: naive numerical gradient is used for testing the idea
        self.noise_real += self.grad_epsilon
        self.train()
        cost_plus = self.get_cost()
        self.noise_real -= self.grad_epsilon
        self.noise_imag += self.grad_epsilon
        self.train()
        cost_plus_j = self.get_cost()
        self.noise_imag -= self.grad_epsilon
        return [(cost_plus-self.last_cost)/self.grad_epsilon,
            (cost_plus_j-self.last_cost)/self.grad_epsilon]
    
    def get_d_cost_d_kernel_scale(self):
        # Warning: naive numerical gradient is used for testing the idea
        self.kernel_scale += self.grad_epsilon
        self.train()
        cost_plus = self.get_cost()
        self.kernel_scale -= self.grad_epsilon
        return (cost_plus-self.last_cost)/self.grad_epsilon
    
    def get_d_cost_d_freqs(self):
        # Warning: naive numerical gradient is used for testing the idea
        d_cost_d_freqs = np.zeros_like(self.spectral_freqs)
        for m in range(self.M):
            self.spectral_freqs[:, m] += self.grad_epsilon
            self.train()
            cost_plus = self.get_cost()
            self.spectral_freqs[:, m] -= self.grad_epsilon
            d_cost_d_freqs[:, m] += (cost_plus-self.last_cost)/self.grad_epsilon
        for d in range(self.D):
            self.spectral_freqs[d, :] += self.grad_epsilon
            self.train()
            cost_plus = self.get_cost()
            self.spectral_freqs[d, :] -= self.grad_epsilon
            d_cost_d_freqs[d, :] += (cost_plus-self.last_cost)/self.grad_epsilon
        return d_cost_d_freqs

    def save(self, path):
        save_pack = [self.noise_imag, self.noise_real, self.kernel_scale,
            self.spectral_freqs, self.X_scaler, self.y_scaler, self.T,
            self.inv_A, self.alpha, self.N, self.hashed_name]
        import pickle
        with open(path, "wb") as save_f:
            pickle.dump(save_pack, save_f, pickle.HIGHEST_PROTOCOL)

    def load(self, path):
        import pickle
        with open(path, "rb") as load_f:
            load_pack = pickle.load(load_f)
            i = 0
            self.noise_imag = load_pack[i];i+=1
            self.noise_real = load_pack[i];i+=1
            self.kernel_scale = load_pack[i];i+=1
            self.spectral_freqs = load_pack[i];i+=1
            self.X_scaler = load_pack[i];i+=1
            self.y_scaler = load_pack[i];i+=1
            self.T = load_pack[i];i+=1
            self.inv_A = load_pack[i];i+=1
            self.alpha = load_pack[i];i+=1
            self.N = load_pack[i];i+=1
            self.hashed_name = load_pack[i]
        return self
    
    
    