# -*- coding:utf8 -*-
# File   : impl.py
# Author : Jiayuan Mao
# Email  : maojiayuan@gmail.com
# Date   : 2/27/17
# 
# This file is part of TensorArtistS

import functools
import tensorflow as tf

__all__ = ['tensor', 'scalar', 'histogram', 'audio', 'image']


def migrate_summary(tf_func):
    @functools.wraps(tf_func)
    def new_func(name, *args, **kwargs):
        if hasattr(name, 'name'):
            name, tensor = name.name, name
            return tf_func(name, tensor, *args, **kwargs)
        return tf_func(name, *args, **kwargs)

    return new_func

tensor = migrate_summary(tf.summary.tensor_summary)
scalar = migrate_summary(tf.summary.scalar)
histogram = migrate_summary(tf.summary.histogram)
audio = migrate_summary(tf.summary.audio)
image = migrate_summary(tf.summary.image)

