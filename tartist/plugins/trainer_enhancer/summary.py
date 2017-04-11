# -*- coding:utf8 -*-
# File   : summary.py
# Author : Jiayuan Mao
# Email  : maojiayuan@gmail.com
# Date   : 2/26/17
# 
# This file is part of TensorArtist

from tartist.core import get_logger, get_env, io
from tartist.nn.tfutils import clean_summary_name
import collections
import threading
import os.path as osp
import shutil
import tensorflow as tf

logger = get_logger()

summary_async_lock = threading.Lock()


class SummaryHistoryManager(object):
    def __init__(self):
        self._summaries = {}
        self._summaries_type = {}
        self._summaries_last_query = {}

    @property
    def all_summaries(self):
        return self.get_all_summaries()

    def get_all_summaries(self, type=None):
        if type is None:
            return list(self._summaries_type.keys())
        filt = lambda x: type == x
        return [k for k, v in self._summaries_type.items() if filt(v)]

    def clear_all(self):
        self._summaries = {}

    def clear(self, key):
        self._summaries[key] = []

    def put_scalar(self, key, value):
        value = float(value)
        self._summaries.setdefault(key, []).append(value)

    def put_async_scalar(self, key, value):
        value = float(value)
        with summary_async_lock:
            self._summaries.setdefault(key, []).append(value)

    def put_summaries(self, summaries):
        for val in summaries.value:
            if val.WhichOneof('value') == 'simple_value':
                # XXX: do hacks here
                val.tag = clean_summary_name(val.tag)
                self.put_scalar(val.tag, val.simple_value)
                self.set_type(val.tag, 'scalar')

    def get(self, key):
        return self._summaries.get(key, [])

    def has(self, key):
        return key in self._summaries

    def get_type(self, key):
        return self._summaries_type.get(key, 'unknown')

    def set_type(self, key, value, check=True):
        old_value = self.get_type(key)
        if old_value != 'unknown' and check:
            assert old_value == value, 'summary type mismatched'
        self._summaries_type[key] = value

    def _do_average(self, values, meth):
        assert meth in ['avg', 'max', 'sum']
        if meth == 'avg':
            return sum(values) / (len(values) + 1e-4)
        elif meth == 'max':
            return max(values)
        elif meth == 'sum':
            return sum(values)

    def average(self, key, top_k=None, meth='avg'):
        type = self.get_type(key)
        if type == 'scalar':
            values = self._summaries.get(key, [])
            if top_k is None:
                top_k = len(values)
            values = values[-top_k:]
            return self._do_average(values, meth)
        elif type == 'async_scalar':
            with summary_async_lock:
                values = self._summaries.get(key, [])
                last_query = self._summaries_last_query.get(key, 0)
                values = values[last_query:]

                if len(values):
                    return self._do_average(values, meth)
                return 'N/A'

    def update_last_query(self, key):
        type = self.get_type(key)
        values = self._summaries.get(key, [])
        assert type.startswith('async_'), (type, key)
        self._summaries_last_query[key] = len(values)


def put_summary_history(trainer, summaries):
    mgr = trainer.runtime.get('summary_histories', None)
    assert mgr is not None, 'you should first enable summary history'
    mgr.put_summaries(summaries)


def put_summary_history_scalar(trainer, name, value):
    mgr = trainer.runtime.get('summary_histories', None)
    assert mgr is not None, 'you should first enable summary history'

    mgr.set_type(name, 'scalar')
    mgr.put_scalar(name, value)


def enable_summary_history(trainer, extra_summary_types=None):
    def check_proto_contains(proto, tag):
        if proto is None:
            return False
        for v in proto.value:
            if v.tag == tag:
                return True
        return False

    def summary_history_on_optimization_before(trainer):
        trainer.runtime['summary_histories'] = SummaryHistoryManager()
        if extra_summary_types is not None:
            for k, v in extra_summary_types.items():
                trainer.runtime['summary_histories'].set_type(k, v)

    def summary_history_on_iter_after(trainer, inp, out):
        mgr = trainer.runtime['summary_histories']

        if 'summaries' in trainer.runtime:
            summaries = trainer.runtime['summaries']
        else:
            summaries = tf.Summary()

        if isinstance(summaries, collections.Iterable):
            for s in summaries:
                mgr.put_summaries(s)
        else:
            if 'loss' in trainer.runtime and not check_proto_contains(summaries, 'train/loss'):
                summaries.value.add(tag='train/loss', simple_value=trainer.runtime['loss'])

            error_summary_key = trainer.runtime.get('error_summary_key', None)
            if mgr.has(error_summary_key):
                if not check_proto_contains(summaries, 'train/error'):
                    for v in summaries.value:
                        if clean_summary_name(v.tag) == error_summary_key:
                            trainer.runtime['error'] = v.simple_value
                    summaries.value.add(tag='train/error', simple_value=trainer.runtime['error'])

            put_summary_history(trainer, summaries)

    trainer.register_event('optimization:before', summary_history_on_optimization_before)
    trainer.register_event('iter:after', summary_history_on_iter_after, priority=8)


def put_tensorboard_summary(trainer, summary, use_internal_gs=False):
    if use_internal_gs:
        gs = trainer.runtime.get('tensorboard_global_step', 0)
        gs += 1
        trainer.runtime['tensorboard_global_step'] = gs
    else:
        gs = trainer.runtime.get('global_step', trainer.iter)
    if hasattr(trainer, '_tensorboard_writer'):
        trainer._tensorboard_writer.add_summary(summary, gs)


def enable_echo_summary_scalar(trainer, summary_spec=None, enable_tensorboard=True, tensorboard_path=None):
    if summary_spec is None:
        summary_spec = {}

    def summary_history_scalar_on_epoch_after(trainer):
        mgr = trainer.runtime['summary_histories']
        extra_summary = tf.Summary()

        log_strs = ['Summaries: epoch = {}'.format(trainer.epoch)]
        for k in sorted(mgr.get_all_summaries('scalar')):
            spec = summary_spec.get(k, ['avg'])

            for meth in spec:
                if not k.startswith('inference'):  # do hack for inference
                    avg = mgr.average(k, trainer.epoch_size, meth=meth)
                else:
                    avg = mgr.average(k, trainer.runtime['inference_epoch_size'], meth=meth)

                if avg != 'N/A':
                    extra_summary.value.add(tag='{}/{}'.format(k, meth), simple_value=avg)
                log_strs.append('  {}/{} = {}'.format(k, meth, avg))

        for k in sorted(mgr.get_all_summaries('async_scalar')):
            spec = summary_spec.get(k, ['avg'])
            for meth in spec:
                avg = mgr.average(k, meth=meth)

                if avg != 'N/A':
                    extra_summary.value.add(tag='{}/{}'.format(k, meth), simple_value=avg)
                log_strs.append('  {}/{} = {}'.format(k, meth, avg))
            mgr.update_last_query(k)

        if len(log_strs) > 1:
            logger.info('\n'.join(log_strs))

        if enable_tensorboard:
            put_tensorboard_summary(trainer, extra_summary)

    def tensorboard_summary_enable(trainer, tb_path=tensorboard_path):
        if tb_path is None:
            tb_path = osp.join(get_env('dir.root'), 'tensorboard')
            if osp.exists(tb_path):
                shutil.rmtree(tb_path)
            io.mkdir(tb_path)
        trainer.runtime['tensorboard_summary_path'] = tb_path
        trainer._tensorboard_writer = tf.summary.FileWriter(tb_path, graph=trainer.env.graph)

    def tensorboard_summary_write(trainer, inp, out):
        if 'summaries' in trainer.runtime:
            summaries = trainer.runtime['summaries']
            if isinstance(summaries, tf.Summary):
                put_tensorboard_summary(trainer, summaries)

    trainer.register_event('epoch:after', summary_history_scalar_on_epoch_after)

    if enable_tensorboard:
        trainer.register_event('optimization:before', tensorboard_summary_enable)
        trainer.register_event('iter:after', tensorboard_summary_write, priority=9)


def set_error_summary_key(trainer, key):
    if not key.startswith('train/'):
        key = 'train/' + key
    trainer.runtime['error_summary_key'] = key

