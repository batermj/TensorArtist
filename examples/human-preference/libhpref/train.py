# -*- coding:utf8 -*-
# File   : train.py
# Author : Jiayuan Mao
# Email  : maojiayuan@gmail.com
# Date   : 05/07/2017
# 
# This file is part of TensorArtist.

from tartist.app.rl.train import A3CMaster, A3CTrainer, A3CTrainerEnv
from tartist.core import get_env
from tartist.core.utils.meta import notnone_property

import threading

__all__ = ['HPA3CMaster', 'HPA3CTrainerEnv', 'HPA3CTrainer']


class HPA3CMaster(A3CMaster):
    rpredictor = None

    # MJY(20170706): Add rpredictor access. Keep original version due to backward-compatibility.
    def _make_predictor_thread(self, i, func, daemon=True):
        return threading.Thread(target=self.predictor_func, daemon=daemon,
                                args=(i, self.rpredictor, self.router, self.queue, func))

    def initialize(self):
        # Initialize the rpredictor first to avoid calling wrong function when the workers start.
        self.rpredictor.initialize()
        super().initialize()


class HPA3CTrainerEnv(A3CTrainerEnv):
    _pcollector = None

    @notnone_property
    def pcollector(self):
        return self._pcollector

    def set_pcollector(self, pc):
        self._pcollector = pc
        return self

    def _initialize_a3c_master(self):
        nr_predictors = get_env('a3c.nr_predictors')
        self._player_master = HPA3CMaster(self, 'hpa3c-player', nr_predictors)
        # self._inference_player_master = HPA3CMaster(self, 'hpa3c-inference-player', nr_predictors)


class HPA3CTrainer(A3CTrainer):
    def initialize(self):
        super().initialize()
        self.env.pcollector.initialize()

    def train(self):
        self.trigger_event('initialization:before')
        self.initialize()
        self.trigger_event('initialization:after')
        self.runtime.setdefault('iter', 0)

        self.trigger_event('optimization:before')

        self.runtime['zero_iter'] = True
        while self.runtime['iter'] <= self.nr_iters and not self.stop_signal:
            if self.runtime['iter'] == 0:
                inp, out = {}, {}
                self.trigger_event('epoch:before')
                self.trigger_event('iter:before', inp)
                self.trigger_event('iter:after', inp, out)
                self.trigger_event('epoch:after')
                step_succ = True
            else:
                step_succ = self._wrapped_run_step()

            if step_succ:
                self.runtime['iter'] += 1
                self.runtime['zero_iter'] = False

        self.trigger_event('optimization:after')

        self.trigger_event('finalization:begin')
        self.finalize()
        self.trigger_event('finalization:after')

    def _wrapped_run_step(self):
        if self.env.pcollector.ready_for_step(self.epoch):
            super()._wrapped_run_step()
            return True
        return False
