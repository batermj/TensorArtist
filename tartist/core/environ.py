# -*- coding:utf8 -*-
# File   : environ.py
# Author : Jiayuan Mao
# Email  : maojiayuan@gmail.com
# Date   : 12/21/16
# 
# This file is part of TensorArtist.

from copy import deepcopy
from .utils.meta import dict_deep_update, dict_deep_keys

import contextlib
import multiprocessing
import os

__all__ = ['EnvBox', 'env', 'load_env', 'has_env', 'get_env', 'set_env', 'with_env']


class _Environ(object):
    __env_ext__ = '.env.pkl'

    def __init__(self, envs=None):
        self.envs = dict()
        if envs is not None:
            self.load(envs)

    def __get_envs_from_spec(self, env_spec):
        if isinstance(env_spec, str) and env_spec.endswith(self.__env_ext__):
            raise NotImplementedError('Not implemented loading method.')
        elif isinstance(env_spec, dict):
            return env_spec
        elif isinstance(env_spec, object) and (hasattr(env_spec, 'envs') or hasattr(env_spec, '__envs__')):
            return getattr(env_spec, 'envs', None) or getattr(env_spec, '__envs__')
        else:
            raise TypeError('unsupported env spec: {}.'.format(env_spec))

    def load(self, env_spec, override=False):
        new_envs = self.__get_envs_from_spec(env_spec)
        if override:
            self.envs = deepcopy(new_envs)
        else:
            dict_deep_update(self.envs, new_envs)
        return True

    def update(self, env_spec):
        return self.load(env_spec, override=False)

    def dump(self, path, prefix=None):
        raise NotImplementedError('not supported yet: Env.dump.')

    def as_dict(self):
        return deepcopy(self.envs)

    def as_dict_ref(self):
        return self.envs

    def clone(self):
        new_env = _Environ()
        new_env.envs = deepcopy(self.envs)
        return new_env

    def keys(self, is_flattened=True):
        if is_flattened:
            return dict_deep_keys(self.envs)
        return list(self.envs.keys())

    def has(self, key):
        """
        Check whether a key is in current env object.
        :param key: the key.
        :return: True if the provided key is in current env object.
        """
        return self.get(key, None) is not None

    def get(self, key, default=None):
        """
        Get a value of a environment provided a key. You can provide a default value, but this value will not affect
        the env object.
        :param key: the key, note that dict of dict can (should) be imploded by ``.''.
        :param default: if the given key is not found in current env object, the default value will be returned.
        :return: the value if the env contains the given key, otherwise the default value provided.
        """
        subkeys = key.split('.')
        current = self.envs
        for subkey in subkeys[0:-1]:
            if subkey not in current:
                current[subkey] = dict()
            current = current[subkey]
        if subkeys[-1] in current:
            return current[subkeys[-1]]
        elif default is None:
            return default
        else:
            current[subkeys[-1]] = default
            return default

    def set(self, key, value=None, do_inc=False, do_replace=True, inc_default=0):
        """
        Set an environment value by key-value pair.
        :param key: the key, note that dict of dict can (should) be imploded by ``.''.
        :param value: the value.
        :param do_inc: if True, will perform += instead of =
        :param do_replace: if True, will set the value regardless of its original value
        :param inc_default: the default value for the do_inc operation
        :return: self
        """
        subkeys = key.split('.')
        current = self.envs
        for subkey in subkeys[0:-1]:
            if subkey not in current:
                current[subkey] = dict()
            current = current[subkey]
        if do_inc:
            if subkeys[-1] not in current:
                current[subkeys[-1]] = inc_default
            current[subkeys[-1]] += value
        elif do_replace or subkeys[-1] not in current:
            current[subkeys[-1]] = value
        return self

    def set_default(self, key, default=None):
        """
        Set an environment value by key-value pair. If the key already exists, it will not be overwritten.
        :param key: the key, note that dict of dict can (should) be imploded by ``.''.
        :param default: the ``default'' value.
        :return: self
        """
        self.set(key, default, do_replace=False)

    def inc(self, key, inc=1, default=None):
        """
        Increase the environment value provided a key.
        :param key: the key, note that dict of dict can (should) be imploded by ``.''.
        :param inc: the number to be increased,
        :param default: the default value of the accumulator.
        :return:
        """
        self.set(key, inc, do_inc=True, inc_default=default)
        return self

    def __contains__(self, item):
        return self.has(item)

    def __getitem__(self, item):
        return self.get(item, None)

    def __setitem__(self, key, value):
        self.set(key, value)
        return value


class EnvBox(multiprocessing.Process):
    def __init__(self, *args, env=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._env = env

        from .. import random
        self.__seed = random.gen_seed()

    def run(self):
        if self._env:
            global env
            env = self._env
        from .. import random
        random.reset_rng(self.__seed)
        from . import get_logger
        logger = get_logger(__file__)
        logger.critical('EnvBox pid={} (ppid={}) rng_seed={}.'.format(
            os.getpid(), os.getppid(), self.__seed))

        super().run()

    def __call__(self):
        self.start()
        self.join()


env = _Environ()

load_env = env.load
has_env = env.has
get_env = env.get
set_env = env.set


@contextlib.contextmanager
def with_env(env_spec, override=True):
    if override:
        backup = env.as_dict_ref()
    else:
        backup = env.as_dict()

    env.load(env_spec, override=override)
    yield

    env.envs = backup
