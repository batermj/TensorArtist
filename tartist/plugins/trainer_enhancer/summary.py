# -*- coding:utf8 -*-
# File   : summary.py
# Author : Jiayuan Mao
# Email  : maojiayuan@gmail.com
# Date   : 2/26/17
# 
# This file is part of TensorArtist

from tartist.core import get_logger, register_event
from tartist.nn.tfutils import clean_summary_name
import collections
import threading

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

        summaries = None
        if 'summaries' in trainer.runtime:
            summaries = trainer.runtime['summaries']
            if isinstance(summaries, collections.Iterable):
                for s in summaries:
                    mgr.put_summaries(s)
            else:
                mgr.put_summaries(summaries)
        if 'loss' in trainer.runtime and not check_proto_contains(summaries, 'loss'):
            put_summary_history_scalar(trainer, 'loss', trainer.runtime['loss'])

        error_summary_key = trainer.runtime.get('error_summary_key', None)
        if mgr.has(error_summary_key):
            trainer.runtime['error'] = mgr.get(error_summary_key)[-1]
            if not check_proto_contains(summaries, 'error'):
                put_summary_history_scalar(trainer, 'error', trainer.runtime['error'])

    register_event(trainer, 'optimization:before', summary_history_on_optimization_before)
    register_event(trainer, 'iter:after', summary_history_on_iter_after)


def enable_echo_summary_scalar(trainer, summary_spec=None):
    if summary_spec is None:
        summary_spec = {}

    def summary_history_scalar_on_epoch_after(trainer):
        mgr = trainer.runtime['summary_histories']

        log_strs = ['Summaries: epoch = {}'.format(trainer.epoch)]
        for k in sorted(mgr.get_all_summaries('scalar')):
            spec = summary_spec.get(k, ['avg'])

            for meth in spec:
                if not k.startswith('inference'): # do hack for inference
                    avg = mgr.average(k, trainer.epoch_size, meth=meth)
                else:
                    avg = mgr.average(k, trainer.runtime['inference_epoch_size'], meth=meth)
                log_strs.append('  {}/{} = {}'.format(k, meth, avg))

        for k in sorted(mgr.get_all_summaries('async_scalar')):
            spec = summary_spec.get(k, ['avg'])
            for meth in spec:
                avg = mgr.average(k, meth=meth)
                log_strs.append('  {}/{} = {}'.format(k, meth, avg))
            mgr.update_last_query(k)

        if len(log_strs) > 1:
            logger.info('\n'.join(log_strs))

    register_event(trainer, 'epoch:after', summary_history_scalar_on_epoch_after)


def set_error_summary_key(trainer, key):
    trainer.runtime['error_summary_key'] = key

