# -*- coding:utf8 -*-
# File   : a3c.py
# Author : Jiayuan Mao
# Email  : maojiayuan@gmail.com
# Date   : 3/19/17
# 
# This file is part of TensorArtist

from ...core import EnvBox, get_env, get_logger
from ...core.utils.meta import notnone_property
from ...data.rflow.query_pipe import QueryReqPipe, QueryRepPipe
from ...nn.graph import select_device, reuse_context, Env
from ...nn.train import TrainerBase, TrainerEnv, SimpleTrainer

import queue
import threading
import tensorflow as tf

logger = get_logger(__file__)

__all__ = ['A3CTrainerEnv', 'A3CTrainer']


class A3CTrainerEnv(TrainerEnv):
    _players = None
    _players_router = None
    _predictors = None
    _predictors_queue = None
    _data_queue = None

    owner_trainer = None
    network_maker = None

    player_func = None
    predictor_func = None
    on_data_func = None
    on_stat_func = None

    @property
    def players_router(self):
        return self._players_router

    @property
    def predictors_queue(self):
        return self._predictors_queue

    @property
    def data_queue(self):
        return self._data_queue

    def initialize_all_peers(self):
        def on_data(router, identifier, inp):
            return self.on_data_func(self, router, identifier, inp)

        def on_stat(router, identifier, inp):
            if self.on_stat_func:
                self.on_stat_func(self, inp)
            router.send(identifier, {'type': 'stat-rep'})

        self._players_router = QueryRepPipe('a3c-player-master')
        self._players_router.dispatcher.register('data', on_data)
        self._players_router.dispatcher.register('stat', on_stat)
        self._predictors_queue = queue.Queue()
        self._data_queue = queue.Queue(get_env('trainer.batch_size') * get_env('a3c.data_queue_length_factor', 16))

        self._players_router.initialize()
        nr_players = get_env('a3c.nr_players')
        self._players = []
        for i in range(nr_players):
            req = QueryReqPipe('ac3-player-%d' % i, self._players_router.conn_info)
            prc = EnvBox(target=self.player_func, args=(i, req), daemon=True)
            self._players.append(prc)
        for p in self._players:
            p.start()

        nr_predictors = get_env('a3c.nr_predictors')
        all_devices = self.slave_devices
        if len(all_devices) == 0:
            all_devices = self.all_devices
        self._predictors = []
        for i in range(nr_predictors):
            dev = all_devices[i % len(all_devices)]
            func = self._make_predictor_net_func(i, dev)
            prc = threading.Thread(target=self.predictor_func, args=(i, self._predictors_queue, func), daemon=True)
            self._predictors.append(prc)
        for p in self._predictors:
            p.start()


    def finialize_all_peers(self):
        self._players_router.finalize()

    def _make_predictor_net_func(self, i, dev):
        def prefix_adder(feed_dict):
            for k in list(feed_dict.keys()):
                feed_dict['predictor/{}/{}'.format(i, k)] = feed_dict.pop(k)

        outputs_name = get_env('a3c.predictor.outputs_name')
        new_env = Env(master_dev=dev, flags=self.flags, dpflags=self.dpflags, graph=self.graph, session=self.session)
        with new_env.as_default():
            with tf.name_scope('predictor/{}'.format(i)), reuse_context(True):
                self.network_maker(new_env)
            new_env.initialize_all_variables()
            outs = {k: new_env.network.outputs[k] for k in outputs_name}
            f = new_env.make_func()
            f.extend_extra_kw_modifiers([prefix_adder])
            f.compile(outputs=outs)
        return f


class A3CTrainer(SimpleTrainer):
    def initialize(self):
        super().initialize()
        self.env.network_maker = self.desc.make_network
        self.env.owner_trainer = self
        self.desc.make_a3c_configs(self.env)
        self.env.initialize_all_peers()